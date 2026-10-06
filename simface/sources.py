"""Where player headshots come from, and a small download cache.

In priority order for each player:
  1. photo_url from the roster (URL or local file path)
  2. a known ID column: espn_id (ESPN CDN), mlbam_id (MLB's image server), nba_id (NBA's CDN)
  3. --lookup espn: match by name (and team) against ESPN's public team rosters, which include headshot links

These are the free, public endpoints the leagues' and ESPN's own sites use. They are not official APIs, can change
without notice, and the photos belong to their owners; keep generated portraits for personal use.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ESPN_SPORT = {"mlb": "baseball", "nba": "basketball", "nfl": "football"}
ESPN_TEAMS = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams"
ESPN_ROSTER = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams/{team_id}/roster"
ESPN_HEADSHOT = "https://a.espncdn.com/i/headshots/{league}/players/full/{espn_id}.png"
MLB_HEADSHOT = "https://img.mlbstatic.com/mlb-photos/image/upload/w_426,q_auto:best/v1/people/{mlbam_id}/headshot/67/current"
NBA_HEADSHOT = "https://cdn.nba.com/headshots/nba/latest/1040x760/{nba_id}.png"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) simface/0.1"


def direct_url(rec, league: str | None) -> str | None:
    """A headshot URL from the roster itself (photo_url or an ID column), if any."""
    if rec.photo_url:
        return rec.photo_url
    if rec.espn_id and league in ESPN_SPORT:
        return ESPN_HEADSHOT.format(league=league, espn_id=rec.espn_id)
    if rec.mlbam_id:
        return MLB_HEADSHOT.format(mlbam_id=rec.mlbam_id)
    if rec.nba_id:
        return NBA_HEADSHOT.format(nba_id=rec.nba_id)
    return None


class Fetcher:
    """Downloads with an on-disk cache, a polite delay, and a retry."""

    def __init__(self, cache_dir: str | Path, max_age_days: float = 30, delay: float = 0.15):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.max_age = max_age_days * 86400
        self.delay = delay
        self._last = 0.0

    def _path(self, url: str) -> Path:
        return self.cache / hashlib.sha1(url.encode()).hexdigest()

    def get(self, url: str, max_age: float | None = None) -> bytes | None:
        """Bytes at url (or a local path), or None if it can't be fetched."""
        if not re.match(r"^https?://", url):
            p = Path(url.removeprefix("file://")).expanduser()
            return p.read_bytes() if p.is_file() else None
        p = self._path(url)
        age_limit = self.max_age if max_age is None else max_age
        if p.exists() and time.time() - p.stat().st_mtime < age_limit:
            data = p.read_bytes()
            return data or None  # an empty file records a miss
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(2):
            self._last = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                p.write_bytes(data)
                return data
            except urllib.error.HTTPError as e:
                if e.code in (404, 403, 410):
                    p.write_bytes(b"")
                    return None
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
            time.sleep(1.0 + attempt)
        return None

    def get_json(self, url: str, max_age: float | None = None):
        data = self.get(url, max_age=max_age)
        return json.loads(data) if data else None


def name_key(name: str) -> str:
    """'José Ramírez Jr.' -> 'joseramirez'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


class EspnDirectory:
    """Name -> headshot index built from ESPN's public team rosters for one league."""

    def __init__(self, fetcher: Fetcher, league: str, max_age_days: float = 3):
        if league not in ESPN_SPORT:
            raise ValueError(f"ESPN lookup supports {', '.join(ESPN_SPORT)}, not {league!r}")
        self.fetcher = fetcher
        self.league = league
        self.max_age = max_age_days * 86400
        self._index: dict[str, list[dict]] | None = None
        self.reachable = True

    def _load(self) -> dict[str, list[dict]]:
        sport = ESPN_SPORT[self.league]
        teams_json = self.fetcher.get_json(ESPN_TEAMS.format(sport=sport, league=self.league), self.max_age)
        index: dict[str, list[dict]] = {}
        if not teams_json:
            self.reachable = False
            return index
        for entry in _teams_from(teams_json):
            team = entry.get("team", entry)
            roster = self.fetcher.get_json(
                ESPN_ROSTER.format(sport=sport, league=self.league, team_id=team.get("id")), self.max_age
            )
            for athlete in _athletes_from(roster or {}):
                href = (athlete.get("headshot") or {}).get("href")
                if not href and athlete.get("id"):
                    href = ESPN_HEADSHOT.format(league=self.league, espn_id=athlete["id"])
                info = {
                    "espn_id": str(athlete.get("id", "")),
                    "name": athlete.get("fullName") or athlete.get("displayName") or "",
                    "team": team.get("abbreviation", ""),
                    "team_name": team.get("displayName", ""),
                    "headshot": href,
                }
                index.setdefault(name_key(info["name"]), []).append(info)
        return index

    def load(self) -> int:
        """Builds the index now; returns how many players it holds (0 if ESPN couldn't be reached)."""
        if self._index is None:
            self._index = self._load()
        return sum(len(v) for v in self._index.values())

    def find(self, name: str, team: str | None = None) -> dict | None:
        self.load()
        hits = self._index.get(name_key(name), [])
        if len(hits) > 1 and team:
            t = re.sub(r"[^a-z]", "", str(team).lower())
            hits = [h for h in hits if t == h["team"].lower() or t in re.sub(r"[^a-z]", "", h["team_name"].lower())]
        # Two players with the same name and no way to tell them apart: better no photo than the wrong one.
        return hits[0] if len(hits) == 1 else None


def _teams_from(data: dict) -> list[dict]:
    try:
        return data["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError, TypeError):
        return data.get("teams", []) if isinstance(data, dict) else []


def _athletes_from(data: dict) -> list[dict]:
    """ESPN rosters are either a flat list (NBA) or grouped by position (NFL, MLB)."""
    out = []
    for item in data.get("athletes", []):
        if isinstance(item, dict) and isinstance(item.get("items"), list):
            out.extend(a for a in item["items"] if isinstance(a, dict))
        elif isinstance(item, dict):
            out.append(item)
    return out
