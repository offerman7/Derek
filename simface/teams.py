"""Real team colors and uniforms (MLB, NBA, NFL), plus any custom teams you load.

A team's kit is turned into RenderContext fields: jersey, trim, trim2, pinstripes, cap, cap_brim, logo, logo_color,
logo_outline. Each league has defaults (MLB home whites with team-colored trim, NBA/NFL colored home jerseys, ...)
so the data file only lists what is different.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .colors import TEAM_PALETTE, is_color, luminance

LEAGUES = ("mlb", "nba", "nfl")
SPORT_LEAGUE = {"baseball": "mlb", "basketball": "nba", "football": "nfl"}

MLB_HOME_WHITE = "#f6f5f1"
MLB_ROAD_GRAY = "#b9bbbe"


@dataclass
class Team:
    league: str
    abbr: str
    city: str
    name: str
    colors: list[str]
    home: dict = field(default_factory=dict)
    away: dict = field(default_factory=dict)
    cap: dict = field(default_factory=dict)
    espn: str = ""
    aliases: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.city} {self.name}".strip()

    @property
    def primary(self) -> str:
        return self.colors[0]

    @property
    def secondary(self) -> str:
        return self.colors[1] if len(self.colors) > 1 else "#ffffff"

    def keys(self) -> list[str]:
        out = [self.abbr, self.name, self.full_name, f"{self.city}{self.name}"] + self.aliases
        return [_norm(k) for k in out if k]

    def kit(self, which: str = "home") -> dict:
        """RenderContext fields for this team's home or away uniform."""
        p, s = self.primary, self.secondary
        if self.league == "mlb":
            base = {"jersey": MLB_HOME_WHITE if which == "home" else MLB_ROAD_GRAY, "trim": p, "trim2": None, "pinstripes": None}
        elif self.league == "nba":
            # NBA "Association" (white) at home, "Icon" (team color) away.
            base = {"jersey": "#ffffff", "trim": p, "trim2": s} if which == "home" else {"jersey": p, "trim": s, "trim2": None}
        else:
            # NFL: colored jersey at home, white away.
            base = {"jersey": p, "trim": s, "trim2": None} if which == "home" else {"jersey": "#ffffff", "trim": p, "trim2": s}
        base.update({k: v for k, v in (self.home if which == "home" else self.away).items()})
        if which == "away" and self.league == "mlb":
            base["pinstripes"] = None
        cap = {"crown": p, "brim": None, "logo": _default_logo(self), "logo_color": _contrast(s, p), "logo_outline": None}
        cap.update(self.cap)
        return {
            "jersey": base["jersey"],
            "trim": base["trim"],
            "trim2": base.get("trim2"),
            "pinstripes": base.get("pinstripes"),
            "cap": cap["crown"],
            "cap_brim": cap["brim"],
            "logo": cap["logo"],
            "logo_color": cap["logo_color"],
            "logo_outline": cap["logo_outline"],
        }


def _default_logo(team: Team) -> str:
    words = re.findall(r"[A-Za-z]+", team.city)
    if len(words) >= 2:
        return "".join(w[0] for w in words[:2]).upper()
    return (team.city or team.name or team.abbr)[:1].upper()


def _contrast(color: str, against: str) -> str:
    if abs(luminance(color) - luminance(against)) >= 0.25:
        return color
    return "#ffffff" if luminance(against) < 0.5 else "#111111"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


class TeamDB:
    def __init__(self) -> None:
        self.teams: list[Team] = []

    @classmethod
    def load_default(cls) -> "TeamDB":
        db = cls()
        data = json.loads(resources.files("simface").joinpath("data/teams.json").read_text())
        for league in LEAGUES:
            for t in data[league]:
                db.teams.append(Team(league=league, **t))
        return db

    def add_file(self, path: str | Path, league: str = "custom") -> int:
        """Load custom teams from CSV or JSON. Columns: abbr/team_id/name/city, primary, secondary, plus any
        of jersey, trim, trim2, pinstripes, cap, cap_brim, logo, logo_color. Returns how many were loaded."""
        path = Path(path)
        if path.suffix.lower() == ".json":
            raw = json.loads(path.read_text())
            rows = raw if isinstance(raw, list) else raw.get("teams", [])
        else:
            with path.open(newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
        n = 0
        for row in rows:
            row = {_norm(k): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k}
            abbr = row.get("abbr") or row.get("abbreviation") or row.get("teamid") or row.get("id") or row.get("tid") or ""
            name = row.get("name") or row.get("nickname") or row.get("teamname") or ""
            colors = [c if str(c).startswith("#") else f"#{c}" for c in (row.get("primary"), row.get("secondary")) if c]
            colors = [c for c in colors if is_color(c)] or list(_hash_colors(str(abbr or name)))
            home = {k: _hex(row[k]) for k in ("jersey", "trim", "trim2", "pinstripes") if row.get(k)}
            cap = {}
            if row.get("cap"):
                cap["crown"] = _hex(row["cap"])
            if row.get("capbrim"):
                cap["brim"] = _hex(row["capbrim"])
            if row.get("logo"):
                cap["logo"] = row["logo"]
            if row.get("logocolor"):
                cap["logo_color"] = _hex(row["logocolor"])
            aliases = [str(v) for k, v in row.items() if k in ("teamid", "id", "tid", "fullname") and v]
            self.teams.insert(0, Team(league=row.get("league") or league, abbr=str(abbr), city=row.get("city", ""),
                                      name=name, colors=colors, home=home, cap=cap, aliases=aliases))
            n += 1
        return n

    def find(self, key, league: str | None = None) -> Team | None:
        """Match by abbreviation, nickname, full name or alias. Prefers the given league."""
        if key in (None, ""):
            return None
        k = _norm(key)
        pools = [t for t in self.teams if league is None or t.league in (league, "custom")]
        for pool in (pools, self.teams):
            for t in pool:
                if k in t.keys():
                    return t
        return None

    def by_league(self, league: str) -> list[Team]:
        return [t for t in self.teams if t.league == league]


def _hex(v: str) -> str:
    v = str(v).strip()
    return v if v.startswith("#") else f"#{v}"


def _hash_colors(key: str) -> tuple[str, str]:
    h = int(hashlib.sha1(key.encode()).hexdigest(), 16)
    return TEAM_PALETTE[h % len(TEAM_PALETTE)]


def fallback_kit(team_key: str | None, league: str) -> dict:
    """Kit for a team we don't know: stable colors picked from the team key."""
    p, s = _hash_colors(team_key or "free agent")
    t = Team(league=league if league in LEAGUES else "nfl", abbr=str(team_key or ""), city=str(team_key or ""),
             name="", colors=[p, s])
    kit = t.kit("home")
    if not team_key:
        kit["logo"] = ""
    return kit
