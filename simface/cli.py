"""Command line: `simface generate`, `simface preview`, `simface lookup-photos`, `simface teams`, `simface world`."""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from .presets import PRESETS, get_preset


def _size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 300x450") from None


def _mapping(items: list[str]) -> dict[str, str]:
    out = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--map expects field=column, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _load_common(args):
    from .roster import read_nation_names, read_roster
    from .teams import TeamDB
    from .world import World

    preset = get_preset(args.preset)
    nation_names = read_nation_names(args.nations) if getattr(args, "nations", None) else None
    records = read_roster(args.roster, _mapping(args.map), season=args.season,
                          weight_unit="kg" if args.metric else preset.weight_unit, nation_names=nation_names)
    if args.limit:
        records = records[: args.limit]
    teams = TeamDB.load_default()
    if args.teams:
        teams.add_file(args.teams, league=preset.league)
    return preset, records, teams, World.load(args.world)


def cmd_generate(args) -> int:
    from .batch import BatchOptions, run_batch

    preset, records, teams, world = _load_common(args)
    preset = preset.with_overrides(size=args.size, fmt=args.format, filename=args.filename,
                                   uniform=args.uniform, headwear=args.headwear)
    if not records:
        print("no players found in roster", file=sys.stderr)
        return 1
    opts = BatchOptions(
        out_dir=Path(args.out), preset=preset, bank_path=Path(args.bank) if args.bank else None, seed=args.seed,
        kit=args.kit, photos=args.photos, lookup=args.lookup, toon=args.toon, only_missing=args.only_missing,
        force=args.force, restyle_chance=args.restyle_chance, season=args.season, workers=args.workers,
        background=args.background, gallery=not args.no_gallery,
    )
    if args.cache:
        opts.cache_dir = Path(args.cache)
    report = run_batch(records, opts, world=world, teams=teams)
    print(report.summary())
    for pid, err in report.failed[:10]:
        print(f"  failed {pid}: {err}", file=sys.stderr)
    if report.protected:
        print(f"  left alone: {', '.join(report.protected[:5])}{' ...' if len(report.protected) > 5 else ''}")
    print(f"output: {Path(args.out).resolve()}")
    return 0 if not report.failed else 2


def cmd_lookup(args) -> int:
    """Find each player's headshot URL on ESPN and write it into a photo_url column, to check or edit by hand."""
    from .roster import load_rows, read_roster
    from .sources import EspnDirectory, Fetcher, direct_url

    preset = get_preset(args.preset)
    rows, _ = load_rows(args.roster)
    records = read_roster(args.roster, _mapping(args.map), season=args.season)
    cache = Path(args.cache) if args.cache else Path.home() / ".cache" / "simface"
    espn = EspnDirectory(Fetcher(cache / "downloads"), preset.league)
    if not espn.load():
        print("warning: couldn't reach ESPN (site.api.espn.com); only photo URLs/IDs already in the roster are used",
              file=sys.stderr)
    found = 0
    for row, rec in zip(rows, records):
        url = direct_url(rec, rec.league or preset.league)
        if not url and rec.name:
            hit = espn.find(rec.name, rec.team)
            if hit:
                url = hit["headshot"]
                row.setdefault("espn_id", hit["espn_id"])
        row["photo_url"] = url or ""
        found += bool(url)
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{found}/{len(rows)} players matched to a headshot; wrote {args.out}")
    return 0


def cmd_preview(args) -> int:
    """A contact sheet of random faces in one team's kit, for tuning the look."""
    from PIL import Image

    from .backends.raster import render_image
    from .batch import make_genome
    from .portrait import RenderContext, build_portrait
    from .roster import PlayerRecord
    from .teams import TeamDB, fallback_kit
    from .world import World

    preset = get_preset(args.preset)
    world, teams = World.load(args.world), TeamDB.load_default()
    team = teams.find(args.team, preset.league) if args.team else None
    kit = team.kit(args.kit) if team else fallback_kit(args.team, preset.league)
    rng = random.Random(args.seed)
    w, h = args.size or (200, 300)
    cols = min(args.count, 8)
    rows = (args.count + cols - 1) // cols
    sheet = Image.new("RGBA", (w * cols, h * rows), (255, 255, 255, 255))
    for i in range(args.count):
        rec = PlayerRecord(id=f"preview-{args.seed}-{i}", nation=args.nation, facial_type=args.facial_type,
                           sex=args.sex)
        g = make_genome(rec, world, preset.league, str(args.seed))
        ctx = RenderContext(age=args.age if args.age else rng.uniform(21, 36), bmi=preset.default_bmi + rng.uniform(-2, 3),
                            uniform=preset.uniform, headwear=preset.headwear, background=args.background or "#e5e7eb", **kit)
        img = render_image(build_portrait(g, ctx), (w, h), background=ctx.background)
        sheet.alpha_composite(img, ((i % cols) * w, (i // cols) * h))
    sheet.convert("RGB").save(args.out)
    print(f"wrote {args.out}")
    return 0


def cmd_teams(args) -> int:
    from .teams import TeamDB

    db = TeamDB.load_default()
    for t in db.teams:
        if args.league and t.league != args.league:
            continue
        print(f"{t.league.upper():4} {t.abbr:5} {t.full_name:32} {' '.join(t.colors)}")
    return 0


def cmd_world(args) -> int:
    from .world import World

    w = World.load(args.world)
    print("Facial types:", ", ".join(w.priors))
    print("\nEthnicities (out of 1000):")
    for name, mix in w.ethnicities.items():
        print(f"  {name:22} " + "  ".join(f"{k} {int(v)}" for k, v in mix.items() if v))
    print("\nNations:", ", ".join(w.nations))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="simface", description="OOTP-style face generator and portrait automater for sports sims.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def roster_args(sp):
        sp.add_argument("roster", help="CSV, JSON, or ZenGM league export")
        sp.add_argument("--preset", default="ootp", choices=sorted(PRESETS), help="game/sport preset (default: ootp)")
        sp.add_argument("--map", action="append", metavar="FIELD=COLUMN", help="map a roster column, e.g. --map id=PlayerID")
        sp.add_argument("--season", type=int, help="season year, for ages computed from birth dates")
        sp.add_argument("--limit", type=int, help="only the first N players")
        sp.add_argument("--cache", help="download/photo cache folder (default ~/.cache/simface)")

    g = sub.add_parser("generate", help="make a portrait for every player in a roster")
    roster_args(g)
    g.add_argument("--out", default="portraits", help="output folder (for OOTP: the league's photos folder)")
    g.add_argument("--bank", help="face bank file (default: <out>/simface_bank.json)")
    g.add_argument("--seed", default="simface", help="league seed; same seed + player id = same face")
    g.add_argument("--size", type=_size, help="picture size, e.g. 300x450")
    g.add_argument("--format", choices=("png", "svg"))
    g.add_argument("--filename", help="file name template, e.g. '{id}.png' or 'player_{id}.png'")
    g.add_argument("--uniform", choices=("baseball", "crew", "pads", "tank", "none"))
    g.add_argument("--headwear", choices=("cap", "none"))
    g.add_argument("--kit", choices=("home", "away"), default="home")
    g.add_argument("--teams", help="extra/custom teams file (CSV or JSON)")
    g.add_argument("--world", help="your own ethnicity/nation tables (e.g. from OOTP), JSON")
    g.add_argument("--nations", help="OOTP nations.csv, to turn nation_id numbers into names")
    g.add_argument("--metric", action="store_true", help="weights are in kg")
    g.add_argument("--photos", choices=("auto", "off", "only"), default="auto",
                   help="auto: real headshot when available, else generated; only: just players with photos")
    g.add_argument("--lookup", choices=("espn",), help="find headshots by player name on ESPN")
    g.add_argument("--toon", type=float, default=0.7, help="cartoon strength for photos, 0..1 (default 0.7)")
    g.add_argument("--only-missing", action="store_true", help="skip players whose picture already exists")
    g.add_argument("--force", action="store_true", help="also overwrite pictures SimFace didn't make")
    g.add_argument("--restyle-chance", type=float, default=0.0, help="chance per player per --season of a new haircut/beard")
    g.add_argument("--background", help="background color (default transparent)")
    g.add_argument("--workers", type=int, default=0, help="render processes (default: CPU count, max 8)")
    g.add_argument("--no-gallery", action="store_true", help="don't write index.html")
    g.set_defaults(func=cmd_generate)

    lk = sub.add_parser("lookup-photos", help="add ESPN headshot URLs to a roster CSV")
    roster_args(lk)
    lk.add_argument("--out", required=True, help="CSV to write")
    lk.set_defaults(func=cmd_lookup)

    pv = sub.add_parser("preview", help="contact sheet of random faces in a team's kit")
    pv.add_argument("--preset", default="baseball", choices=sorted(PRESETS))
    pv.add_argument("--team", help="team abbreviation or name, e.g. NYY, Lakers")
    pv.add_argument("--kit", choices=("home", "away"), default="home")
    pv.add_argument("--count", type=int, default=16)
    pv.add_argument("--nation")
    pv.add_argument("--facial-type", help="african, asian, caucasian, east_indian or hispanic")
    pv.add_argument("--sex", default="male")
    pv.add_argument("--age", type=float)
    pv.add_argument("--seed", type=int, default=1)
    pv.add_argument("--size", type=_size)
    pv.add_argument("--background")
    pv.add_argument("--world")
    pv.add_argument("--out", default="preview.png")
    pv.set_defaults(func=cmd_preview)

    t = sub.add_parser("teams", help="list built-in teams")
    t.add_argument("--league", choices=("mlb", "nba", "nfl"))
    t.set_defaults(func=cmd_teams)

    w = sub.add_parser("world", help="list facial types, ethnicities and nations")
    w.add_argument("--world")
    w.set_defaults(func=cmd_world)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
