"""Output presets: which uniform, picture size and file naming each game expects."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Preset:
    name: str
    league: str  # mlb | nba | nfl: which real teams to match and which US mix to use
    uniform: str
    headwear: str
    size: tuple[int, int]
    filename: str
    fmt: str = "png"
    default_bmi: float = 25.5
    weight_unit: str = "lb"
    description: str = ""

    def with_overrides(self, **kw) -> "Preset":
        return replace(self, **{k: v for k, v in kw.items() if v is not None})


PRESETS: dict[str, Preset] = {
    "ootp": Preset("ootp", "mlb", "baseball", "cap", (90, 135), "player_{id}.png", default_bmi=26.5,
                   description="OOTP Baseball: player_<id>.png at 90x135 for the league's photos folder"),
    "baseball": Preset("baseball", "mlb", "baseball", "cap", (300, 450), "{id}.png", default_bmi=26.5,
                       description="Baseball sims: cap and button-front jersey"),
    "basketball": Preset("basketball", "nba", "tank", "none", (300, 450), "{id}.png", default_bmi=24.5,
                         description="Basketball sims: tank-top jersey"),
    "football": Preset("football", "nfl", "pads", "none", (300, 450), "{id}.png", default_bmi=29.5,
                       description="Football sims: jersey over shoulder pads, no helmet"),
}


def get_preset(name: str) -> Preset:
    try:
        return PRESETS[name.lower()]
    except KeyError:
        raise KeyError(f"unknown preset {name!r}; choose from {', '.join(PRESETS)}") from None
