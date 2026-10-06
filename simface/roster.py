"""Reads rosters from CSV, JSON, or a ZenGM (Basketball/Football/Baseball GM) league export.

Column names are matched loosely (case and punctuation ignored) against the aliases below, so most exports work
without a mapping. Anything else can be mapped with --map field=column.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("player_id", "playerid", "pid", "id", "person_id", "uid", "player"),
    "first": ("first_name", "firstname", "first", "fname", "given_name"),
    "last": ("last_name", "lastname", "last", "lname", "surname", "family_name"),
    "name": ("name", "full_name", "fullname", "player_name", "display_name"),
    "age": ("age",),
    "born": ("date_of_birth", "dob", "birthdate", "birth_date", "born", "birthday", "born_year", "birth_year", "bornyear"),
    "height": ("height", "hgt", "ht", "height_cm", "height_in", "height_inches"),
    "weight": ("weight", "wt", "weight_lbs", "weight_lb", "weight_kg"),
    "nation": ("nation", "nationality", "country", "nation_id", "birth_country", "born_loc", "bornloc", "birthplace", "hometown", "birth_place"),
    "ethnicity": ("ethnicity",),
    "facial_type": ("facial_type", "face_type", "facetype", "facegen_type"),
    "sex": ("sex", "gender"),
    "team": ("team", "team_abbr", "team_name", "abbr", "team_id", "tid", "club", "franchise"),
    "kit": ("kit", "uniform", "jersey_set"),
    "photo_url": ("photo_url", "photo", "headshot", "headshot_url", "image", "image_url", "img_url", "imgurl", "picture", "portrait", "pic"),
    "espn_id": ("espn_id", "espnid", "espn_player_id"),
    "mlbam_id": ("mlbam_id", "mlb_id", "mlbid", "mlbam", "key_mlbam"),
    "nba_id": ("nba_id", "nbaid", "nba_person_id", "person_id_nba"),
    "league": ("league", "league_abbr"),
}
OVERRIDES = ("skin_tone", "hair_color", "eye_color", "hair_style", "facial_hair", "hair_texture")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


@dataclass
class PlayerRecord:
    id: str
    first: str = ""
    last: str = ""
    full_name: str = ""
    age: float | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    nation: str | None = None
    ethnicity: str | None = None
    facial_type: str | None = None
    sex: str = "male"
    team: str | None = None
    league: str | None = None
    kit: str | None = None
    photo_url: str | None = None
    espn_id: str | None = None
    mlbam_id: str | None = None
    nba_id: str | None = None
    overrides: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.full_name or f"{self.first} {self.last}".strip()

    @property
    def bmi(self) -> float | None:
        if self.height_cm and self.weight_kg:
            m = self.height_cm / 100
            return self.weight_kg / (m * m)
        return None


def parse_height_cm(v) -> float | None:
    """'6-2', 6'2", '74' (inches), '188' (cm), 74.0 -> centimeters."""
    if v in (None, ""):
        return None
    s = str(v).strip()
    m = re.match(r"^(\d)\s*['\-’ ]\s*(\d{1,2})", s)
    if m:
        return (int(m.group(1)) * 12 + int(m.group(2))) * 2.54
    try:
        x = float(s)
    except ValueError:
        return None
    if x <= 0:
        return None
    return x if x > 100 else x * 2.54


def parse_weight_kg(v, unit: str = "lb") -> float | None:
    if v in (None, ""):
        return None
    try:
        x = float(re.sub(r"[^0-9.]", "", str(v)))
    except ValueError:
        return None
    return x if unit == "kg" else x * 0.45359237


def parse_age(born, season: int | None) -> float | None:
    """Age at July 1 of `season` (or today) from a date or a birth year."""
    if born in (None, ""):
        return None
    ref = dt.date(season, 7, 1) if season else dt.date.today()
    s = str(born).strip()
    for text in (s, s[:10]):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y%m%d"):
            try:
                d = dt.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
            return round((ref - d).days / 365.25, 1)
    m = re.match(r"^(\d{4})", s)
    if m:
        return float(ref.year - int(m.group(1)))
    return None


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "_"))
        else:
            out[key] = v
    return out


def load_rows(path: str | Path) -> tuple[list[dict], dict]:
    """Rows as dicts, plus metadata (e.g. the season of a ZenGM league)."""
    path = Path(path)
    meta: dict = {}
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            attrs = data.get("gameAttributes")
            if isinstance(attrs, list):
                attrs = {a.get("key"): a.get("value") for a in attrs if isinstance(a, dict)}
            if isinstance(attrs, dict) and isinstance(attrs.get("season"), int):
                meta["season"] = attrs["season"]
            if isinstance(data.get("teams"), list):
                meta["teams"] = {str(t.get("tid")): t for t in data["teams"] if isinstance(t, dict)}
            rows = data.get("players") or data.get("roster") or data.get("athletes") or []
        else:
            rows = data
        return [_flatten(r) for r in rows if isinstance(r, dict)], meta
    with path.open(newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(fh, dialect=dialect)), meta


def read_roster(
    path: str | Path,
    mapping: dict[str, str] | None = None,
    season: int | None = None,
    weight_unit: str = "lb",
    nation_names: dict[str, str] | None = None,
) -> list[PlayerRecord]:
    rows, meta = load_rows(path)
    season = season or meta.get("season")
    if not rows:
        return []
    columns = {_norm(c): c for c in rows[0].keys()}
    resolved: dict[str, str] = {}
    for fld, names in ALIASES.items():
        for n in names:
            if _norm(n) in columns:
                resolved[fld] = columns[_norm(n)]
                break
    for fld, col in (mapping or {}).items():
        if _norm(col) in columns:
            resolved[fld] = columns[_norm(col)]
        else:
            raise KeyError(f"--map {fld}={col}: no column named {col!r}")
    # ZenGM: born.year flattens to born_year, born.loc to born_loc; prefer those over the dict itself.
    if "born_year" in rows[0] and "born" not in resolved:
        resolved["born"] = "born_year"
    over_cols = {o: columns[_norm(o)] for o in OVERRIDES if _norm(o) in columns}
    if "kg" in _norm(resolved.get("weight", "")):
        weight_unit = "kg"
    zengm_teams = meta.get("teams", {})

    def get(row, fld):
        col = resolved.get(fld)
        v = row.get(col) if col else None
        return v.strip() if isinstance(v, str) else v

    records = []
    for i, row in enumerate(rows):
        pid = get(row, "id")
        pid = str(pid) if pid not in (None, "") else str(i + 1)
        age = get(row, "age")
        try:
            age = float(age) if age not in (None, "") else None
        except ValueError:
            age = None
        if age is None:
            age = parse_age(get(row, "born"), season)
        nation = get(row, "nation")
        if nation is not None and nation_names and str(nation) in nation_names:
            nation = nation_names[str(nation)]
        team = get(row, "team")
        if team is not None and zengm_teams.get(str(team)):
            t = zengm_teams[str(team)]
            team = f"{t.get('region', '')} {t.get('name', '')}".strip() or t.get("abbrev")
        rec = PlayerRecord(
            id=pid,
            first=str(get(row, "first") or ""),
            last=str(get(row, "last") or ""),
            full_name=str(get(row, "name") or ""),
            age=age,
            height_cm=parse_height_cm(get(row, "height")),
            weight_kg=parse_weight_kg(get(row, "weight"), weight_unit),
            nation=str(nation) if nation not in (None, "") else None,
            ethnicity=get(row, "ethnicity") or None,
            facial_type=_facial_type(get(row, "facial_type")),
            sex="female" if str(get(row, "sex") or "").lower().startswith("f") else "male",
            team=str(team) if team not in (None, "") else None,
            league=(str(get(row, "league")).lower() or None) if get(row, "league") else None,
            kit=(get(row, "kit") or None),
            photo_url=get(row, "photo_url") or None,
            espn_id=str(get(row, "espn_id")) if get(row, "espn_id") else None,
            mlbam_id=str(get(row, "mlbam_id")) if get(row, "mlbam_id") else None,
            nba_id=str(get(row, "nba_id")) if get(row, "nba_id") else None,
            overrides={k: row[c] for k, c in over_cols.items() if row.get(c) not in (None, "")},
            raw=row,
        )
        # Only keep things that look like a URL or an image path (some exports have an unrelated "picture" flag).
        if rec.photo_url and not re.search(r"^https?://|[/\\]|\.(png|jpe?g|webp|gif)$", rec.photo_url, re.I):
            rec.photo_url = None
        records.append(rec)
    return records


def _facial_type(v) -> str | None:
    """Accepts a name or OOTP's numeric order (0 african, 1 asian, 2 caucasian, 3 east_indian, 4 hispanic)."""
    from .genome import OOTP_FACIAL_TYPES

    if v in (None, ""):
        return None
    s = str(v).strip().lower().replace(" ", "_").replace("-", "_")
    if s.isdigit() and int(s) < len(OOTP_FACIAL_TYPES):
        return OOTP_FACIAL_TYPES[int(s)]
    return {"black": "african", "white": "caucasian", "latino": "hispanic", "indian": "east_indian"}.get(s, s)


def read_nation_names(path: str | Path) -> dict[str, str]:
    """OOTP's nations.csv (nation_id, name, ...) -> {id: name}."""
    rows, _ = load_rows(path)
    out = {}
    for r in rows:
        nr = {_norm(k): v for k, v in r.items()}
        nid = nr.get("nationid") or nr.get("id")
        name = nr.get("name") or nr.get("nation") or nr.get("abbreviation")
        if nid not in (None, "") and name:
            out[str(nid).strip()] = str(name).strip()
    return out
