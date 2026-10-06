"""Batch automation: roster in, one portrait per player out.

For each player: load their genome from the face bank (or create one, seeded by player ID so reruns match),
apply this season's age, build and team kit, use their real headshot if one is available, render, write.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import random
import re
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .bank import FaceBank
from .genome import Genome, generate_genome, restyle
from .portrait import RenderContext, build_portrait
from .presets import Preset
from .roster import PlayerRecord
from .sources import EspnDirectory, Fetcher, direct_url
from .teams import TeamDB, fallback_kit
from .world import World

PHOTO_CACHE_VERSION = "1"


@dataclass
class BatchOptions:
    out_dir: Path
    preset: Preset
    bank_path: Path | None = None
    seed: str = "simface"
    kit: str = "home"
    photos: str = "auto"  # auto | off | only
    lookup: str | None = None  # "espn" to find headshots by name
    toon: float = 0.7
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "simface")
    only_missing: bool = False
    force: bool = False
    restyle_chance: float = 0.0
    season: int | None = None
    workers: int = 0
    background: str | None = None
    gallery: bool = True


@dataclass
class BatchReport:
    total: int = 0
    photo: int = 0
    generated: int = 0
    no_face: int = 0
    skipped_existing: int = 0
    protected: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    new_genomes: int = 0

    def summary(self) -> str:
        parts = [f"{self.photo + self.generated} written ({self.photo} from photos, {self.generated} generated)"]
        if self.new_genomes:
            parts.append(f"{self.new_genomes} new faces")
        if self.no_face:
            parts.append(f"{self.no_face} photos had no usable face (generated instead)")
        if self.skipped_existing:
            parts.append(f"{self.skipped_existing} already existed")
        if self.protected:
            parts.append(f"{len(self.protected)} existing files not made by SimFace were left alone (use --force)")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return "; ".join(parts)


def player_rng(seed: str, pid: str, salt: str) -> random.Random:
    h = hashlib.sha256(f"{seed}:{pid}:{salt}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def make_genome(rec: PlayerRecord, world: World, league: str, seed: str) -> Genome:
    rng = player_rng(seed, rec.id, "genome")
    if rec.facial_type in world.priors:
        primary, other, blend = rec.facial_type, None, 0.0
    else:
        primary, other, blend = world.pick_types(rng, world.facial_mix(rec.nation, rec.ethnicity, league))
    return generate_genome(rng, primary, rec.sex, other, blend, world.priors)


def filename_for(rec: PlayerRecord, template: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", rec.name.lower()).strip("_") or rec.id
    name = template.format(id=rec.id, first=rec.first, last=rec.last, name=slug, team=rec.team or "")
    return re.sub(r"[\\/:*?\"<>|]", "_", name)


def render_context(rec: PlayerRecord, preset: Preset, teams: TeamDB, kit: str, background: str | None) -> RenderContext:
    league = rec.league or preset.league
    team = teams.find(rec.team, league) if rec.team else None
    colors = team.kit(rec.kit or kit) if team else fallback_kit(rec.team, league)
    return RenderContext(
        age=rec.age if rec.age is not None else 27.0,
        bmi=rec.bmi or preset.default_bmi,
        uniform=preset.uniform,
        headwear=preset.headwear,
        background=background,
        **colors,
    )


def run_batch(records: list[PlayerRecord], opts: BatchOptions, world: World | None = None,
              teams: TeamDB | None = None, log=print) -> BatchReport:
    world = world or World.load()
    teams = teams or TeamDB.load_default()
    preset = opts.preset
    out_dir = Path(opts.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bank = FaceBank(opts.bank_path or out_dir / "simface_bank.json", seed=opts.seed)
    report = BatchReport(total=len(records))
    fetcher = Fetcher(opts.cache_dir / "downloads")
    espn = EspnDirectory(fetcher, preset.league) if opts.lookup == "espn" and opts.photos != "off" else None
    if espn is not None:
        n = espn.load()
        log(f"ESPN {preset.league.upper()} rosters: {n} players" if n else
            "warning: couldn't reach ESPN rosters; using roster photo URLs/IDs only")

    owned = bank.owned_files()
    jobs: list[dict] = []
    for rec in records:
        league = rec.league or preset.league
        genome = bank.genome(rec.id)
        if genome is None:
            genome = make_genome(rec, world, league, bank.seed)
            bank.put(rec.id, genome, rec.name)
            report.new_genomes += 1
        elif opts.restyle_chance > 0:
            rng = player_rng(bank.seed, rec.id, f"restyle:{opts.season}")
            if rng.random() < opts.restyle_chance:
                restyle(genome, rng)
                bank.put(rec.id, genome, rec.name)
        fname = filename_for(rec, preset.filename)
        if opts.preset.fmt == "svg" and fname.lower().endswith(".png"):
            fname = fname[:-4] + ".svg"
        target = out_dir / fname
        if target.exists() and not opts.force:
            if fname not in owned:
                report.protected.append(fname)
                continue
            if opts.only_missing:
                report.skipped_existing += 1
                continue
        url = None
        if opts.photos != "off":
            url = direct_url(rec, league)
            if url is None and espn is not None and rec.name:
                hit = espn.find(rec.name, rec.team)
                url = hit["headshot"] if hit else None
        if opts.photos == "only" and not url:
            continue
        jobs.append({
            "id": rec.id,
            "name": rec.name,
            "team": rec.team or "",
            "file": fname,
            "path": str(target),
            "url": url,
            "genome": genome.with_overrides(rec.overrides).to_dict(),
            "ctx": render_context(rec, preset, teams, opts.kit, opts.background).to_dict(),
            "size": list(preset.size),
            "fmt": preset.fmt,
            "toon": opts.toon,
            "cache": str(opts.cache_dir / "heads"),
        })

    # Download headshots in parallel (I/O bound), then render on all cores (CPU bound).
    urls = sorted({j["url"] for j in jobs if j["url"]})
    if urls:
        log(f"fetching {len(urls)} headshots...")
        lock = threading.Lock()
        got: dict[str, bytes | None] = {}

        def fetch(u):
            data = fetcher.get(u)
            with lock:
                got[u] = data

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(fetch, urls))
        for j in jobs:
            j["photo"] = got.get(j["url"]) if j["url"] else None
    if opts.photos == "only":
        jobs = [j for j in jobs if j.get("photo")]

    workers = opts.workers or min(8, os.cpu_count() or 1)
    log(f"rendering {len(jobs)} portraits...")
    if workers <= 1 or len(jobs) < 8:
        results = [render_job(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(render_job, jobs, chunksize=4))

    by_id = {j["id"]: j for j in jobs}
    for pid, status, note in results:
        job = by_id[pid]
        if status == "failed":
            report.failed.append((pid, note))
            continue
        bank.mark_written(pid, job["file"], status)
        if status == "photo":
            report.photo += 1
        else:
            report.generated += 1
            if note == "no-face":
                report.no_face += 1
    bank.save()
    if opts.gallery:
        write_gallery(out_dir, jobs, results)
    return report


def render_job(job: dict) -> tuple[str, str, str]:
    """Runs in a worker process. Returns (player id, 'photo' | 'generated' | 'failed', note)."""
    try:
        photo, note = None, ""
        if job.get("photo"):
            photo = processed_head(job["photo"], job["toon"], Path(job["cache"]))
            note = "" if photo else "no-face"
        items = build_portrait(Genome.from_dict(job["genome"]), RenderContext.from_dict(job["ctx"]), photo=photo)
        size = tuple(job["size"])
        background = job["ctx"].get("background")
        if job["fmt"] == "svg":
            from .backends import render_svg

            data = render_svg(items, size, background).encode()
        else:
            from .backends import render_png

            data = render_png(items, size, background)
        path = Path(job["path"])
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return job["id"], ("photo" if photo else "generated"), note
    except Exception as e:  # one bad player shouldn't stop the batch
        return job["id"], "failed", f"{type(e).__name__}: {e}"


def processed_head(raw: bytes, toon: float, cache: Path):
    """PhotoHead for these image bytes, cached on disk because face cut-out is the slow step."""
    from .photo import NoFaceFound, PhotoHead, prepare_photo

    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(raw + f"|{toon}|{PHOTO_CACHE_VERSION}".encode()).hexdigest()
    meta_path, png_path, miss_path = cache / f"{key}.json", cache / f"{key}.png", cache / f"{key}.noface"
    if miss_path.exists():
        return None
    if meta_path.exists() and png_path.exists():
        return PhotoHead(png=png_path.read_bytes(), **json.loads(meta_path.read_text()))
    try:
        head = prepare_photo(raw, toon=toon)
    except NoFaceFound:
        miss_path.touch()
        return None
    meta = {k: v for k, v in head.__dict__.items() if k != "png"}
    png_path.write_bytes(head.png)
    meta_path.write_text(json.dumps(meta))
    return head


def write_gallery(out_dir: Path, jobs: list[dict], results: list[tuple[str, str, str]]) -> Path:
    status = {pid: s for pid, s, _ in results}
    cards = []
    for j in jobs:
        s = status.get(j["id"], "failed")
        if s == "failed":
            continue
        cards.append(
            f'<figure><img src="{html.escape(j["file"])}" loading="lazy" alt="">'
            f'<figcaption><b>{html.escape(j["name"] or j["id"])}</b>'
            f'<span>{html.escape(j["team"])} · {"photo" if s == "photo" else "generated"}</span></figcaption></figure>'
        )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SimFace gallery</title><style>
body{{font:14px system-ui,sans-serif;margin:16px;background:#f3f4f6;color:#111}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px}}
figure{{margin:0;background:#fff;border-radius:8px;padding:8px;text-align:center;box-shadow:0 1px 2px #0002}}
img{{width:100%;aspect-ratio:2/3;object-fit:contain;background:#e5e7eb;border-radius:4px}}
figcaption{{display:flex;flex-direction:column;margin-top:6px}} span{{color:#6b7280;font-size:12px}}
@media (prefers-color-scheme:dark){{body{{background:#111827;color:#f9fafb}}figure{{background:#1f2937}}img{{background:#374151}}span{{color:#9ca3af}}}}
</style></head><body><h1>SimFace gallery</h1><main>{"".join(cards)}</main></body></html>"""
    path = out_dir / "index.html"
    path.write_text(page)
    return path
