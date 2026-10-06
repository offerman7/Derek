"""OOTP-style world: nations -> ethnicities -> facial types.

Same model as OOTP: each nation has a mix of ethnicities, and each ethnicity is a mix of facial types out of 1000.
A player's facial type is drawn from that chain; sometimes a second type is blended in for a mixed look.
"""

from __future__ import annotations

import copy
import json
import random
import re
import unicodedata
from importlib import resources
from pathlib import Path

from .genome import FACIAL_TYPE_PRIORS, OOTP_FACIAL_TYPES

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
    "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
CA_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}


def _key(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


class World:
    def __init__(self, data: dict):
        self.data = data
        self.blend_chance = float(data.get("blend_chance", 0.3))
        self.default_nation = data.get("default_nation", "USA")
        self.priors = copy.deepcopy(FACIAL_TYPE_PRIORS)
        for name, spec in data.get("facial_types", {}).items():
            spec = dict(spec)
            base = spec.pop("base", name if name in self.priors else "caucasian")
            merged = copy.deepcopy(self.priors.get(base, {}))
            merged.update({k: tuple(v) if isinstance(v, list) else v for k, v in spec.items()})
            self.priors[name] = merged
        self.ethnicities = {name: self._mix(v) for name, v in data.get("ethnicities", {}).items()}
        self._eth_keys = {_key(n): n for n in self.ethnicities}
        self.nations = data.get("nations", {})
        self._nation_keys: dict[str, str] = {}
        for name, spec in self.nations.items():
            for alias in [name] + spec.get("aliases", []):
                self._nation_keys.setdefault(_key(alias), name)

    @staticmethod
    def _mix(v) -> dict[str, float]:
        if isinstance(v, list):
            return dict(zip(OOTP_FACIAL_TYPES, (float(x) for x in v)))
        return {k: float(x) for k, x in v.items()}

    @classmethod
    def load(cls, extra: str | Path | None = None) -> "World":
        data = json.loads(resources.files("simface").joinpath("data/world.json").read_text())
        if extra:
            user = json.loads(Path(extra).read_text())
            for section in ("ethnicities", "nations", "facial_types"):
                data.setdefault(section, {}).update(user.get(section, {}))
            for k in ("blend_chance", "default_nation"):
                if k in user:
                    data[k] = user[k]
        return cls(data)

    def resolve_nation(self, text) -> str | None:
        """'Japan', 'JPN', 'Austin, TX', 'Toronto, ON', 'Santo Domingo, Dominican Republic' -> nation name."""
        if text in (None, ""):
            return None
        text = str(text).strip()
        hit = self._nation_keys.get(_key(text))
        if hit:
            return hit
        if "," in text:
            tail = text.rsplit(",", 1)[1].strip()
            if tail.upper() in US_STATES:
                return self._nation_keys.get(_key("USA"))
            if tail.upper() in CA_PROVINCES:
                return self._nation_keys.get(_key("Canada"))
            return self._nation_keys.get(_key(tail))
        return None

    def resolve_ethnicity(self, text) -> str | None:
        return self._eth_keys.get(_key(text)) if text else None

    def facial_mix(self, nation: str | None = None, ethnicity: str | None = None, league: str | None = None) -> dict[str, float]:
        """Facial-type weights for a player, from their ethnicity or nation (league-specific mix if defined)."""
        eth = self.resolve_ethnicity(ethnicity)
        if eth:
            return self.ethnicities[eth]
        nation = self.resolve_nation(nation) or self.default_nation
        spec = self.nations.get(nation, {})
        eth_weights = spec.get("by_league", {}).get(league or "", spec.get("ethnicities", {}))
        if not eth_weights:
            return {t: 200.0 for t in OOTP_FACIAL_TYPES}
        total = sum(eth_weights.values())
        mix: dict[str, float] = {}
        for eth_name, w in eth_weights.items():
            for ft, x in self.ethnicities.get(eth_name, {}).items():
                mix[ft] = mix.get(ft, 0.0) + x * w / total
        return mix

    def pick_types(self, rng: random.Random, mix: dict[str, float]) -> tuple[str, str | None, float]:
        """Primary facial type, optional blend type and blend amount."""
        items = [(k, v) for k, v in mix.items() if v > 0 and k in self.priors]
        if not items:
            return "caucasian", None, 0.0
        primary = _draw(rng, items)
        others = [(k, v) for k, v in items if k != primary]
        if others and rng.random() < self.blend_chance:
            return primary, _draw(rng, others), rng.uniform(0.15, 0.45)
        return primary, None, 0.0


def _draw(rng: random.Random, items: list[tuple[str, float]]) -> str:
    total = sum(v for _, v in items)
    r = rng.random() * total
    for k, v in items:
        r -= v
        if r <= 0:
            return k
    return items[-1][0]
