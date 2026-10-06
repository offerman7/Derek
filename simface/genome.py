"""The face genome: everything about a player's face that stays the same for a whole career.

Like OOTP, a face is drawn from one of a few facial types (african, asian, caucasian, east_indian, hispanic).
Each type is a set of priors (mean and spread per trait, weights per color). A player can also be a blend of
two types. Age and weight are not stored here; they are applied when the face is rendered, so the same genome
ages naturally from season to season.
"""

from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, fields

from .colors import EYE_COLORS, HAIR_COLORS, clamp

# OOTP's column order for facial types in its ethnicity tables.
OOTP_FACIAL_TYPES = ("african", "asian", "caucasian", "east_indian", "hispanic")

# Continuous traits, each 0..1 with 0.5 average. Defaults below apply to any trait a type doesn't override.
SHAPE_TRAITS = (
    "head_width", "head_length", "jaw_width", "jaw_square", "chin_length", "chin_width", "cheekbones",
    "forehead", "eye_size", "eye_spacing", "eye_tilt", "eye_lid", "brow_thickness", "brow_arch",
    "brow_height", "nose_length", "nose_width", "nose_bridge", "nose_tip", "mouth_width", "lip_upper",
    "lip_lower", "ear_size", "ear_protrusion",
)
DEFAULT_SD = 0.19

# Coarse, game-style priors. Tune them or add new types in a world file (see README).
FACIAL_TYPE_PRIORS: dict[str, dict] = {
    "african": {
        "skin_tone": (0.79, 0.09), "undertone": (0.15, 0.3),
        "jaw_width": (0.56, 0.15), "cheekbones": (0.6, 0.15),
        "nose_width": (0.74, 0.12), "nose_bridge": (0.32, 0.12), "nose_length": (0.45, 0.14), "nose_tip": (0.62, 0.15),
        "lip_upper": (0.72, 0.12), "lip_lower": (0.74, 0.12), "mouth_width": (0.6, 0.14),
        "eye_lid": (0.1, 0.08), "eye_size": (0.55, 0.15),
        "beard_density": (0.5, 0.2), "freckles": (0.0, 0.03), "baldness": (0.45, 0.25),
        "hair_color": {"black": 92, "dark_brown": 8},
        "eye_color": {"dark_brown": 86, "brown": 14},
        "hair_texture": {"coily": 84, "curly": 16},
    },
    "asian": {
        "skin_tone": (0.26, 0.07), "undertone": (0.5, 0.25),
        "head_width": (0.6, 0.14), "cheekbones": (0.64, 0.14), "jaw_width": (0.52, 0.15),
        "nose_width": (0.5, 0.12), "nose_bridge": (0.24, 0.12), "nose_length": (0.42, 0.13),
        "lip_upper": (0.48, 0.13), "lip_lower": (0.52, 0.13),
        "eye_lid": (0.72, 0.16), "eye_size": (0.38, 0.14), "eye_tilt": (0.62, 0.14), "brow_height": (0.62, 0.14),
        "brow_thickness": (0.45, 0.15),
        "beard_density": (0.22, 0.14), "freckles": (0.02, 0.05), "baldness": (0.3, 0.2),
        "hair_color": {"black": 86, "dark_brown": 14},
        "eye_color": {"dark_brown": 80, "brown": 20},
        "hair_texture": {"straight": 86, "wavy": 14},
    },
    "caucasian": {
        "skin_tone": (0.09, 0.06), "undertone": (-0.25, 0.3),
        "nose_width": (0.38, 0.13), "nose_bridge": (0.7, 0.14), "nose_length": (0.58, 0.15),
        "lip_upper": (0.34, 0.13), "lip_lower": (0.44, 0.13),
        "eye_lid": (0.12, 0.1),
        "beard_density": (0.64, 0.2), "freckles": (0.22, 0.25), "baldness": (0.55, 0.25),
        "hair_color": {"black": 5, "dark_brown": 24, "brown": 28, "light_brown": 18, "dark_blond": 10,
                       "blond": 9, "red": 4, "auburn": 2},
        "eye_color": {"dark_brown": 10, "brown": 22, "hazel": 16, "green": 10, "blue": 33, "gray": 9},
        "hair_texture": {"straight": 58, "wavy": 34, "curly": 8},
    },
    "east_indian": {
        "skin_tone": (0.55, 0.1), "undertone": (0.3, 0.25),
        "nose_length": (0.62, 0.14), "nose_bridge": (0.58, 0.14), "nose_width": (0.55, 0.13),
        "lip_upper": (0.52, 0.13), "lip_lower": (0.58, 0.13), "eye_size": (0.6, 0.14),
        "brow_thickness": (0.66, 0.15),
        "beard_density": (0.7, 0.18), "freckles": (0.0, 0.03), "baldness": (0.45, 0.25),
        "hair_color": {"black": 80, "dark_brown": 20},
        "eye_color": {"dark_brown": 78, "brown": 18, "hazel": 4},
        "hair_texture": {"straight": 45, "wavy": 45, "curly": 10},
    },
    "hispanic": {
        "skin_tone": (0.37, 0.12), "undertone": (0.25, 0.3),
        "nose_width": (0.52, 0.14), "nose_bridge": (0.5, 0.15),
        "lip_upper": (0.5, 0.14), "lip_lower": (0.56, 0.14),
        "brow_thickness": (0.58, 0.15),
        "beard_density": (0.58, 0.2), "freckles": (0.03, 0.06), "baldness": (0.45, 0.25),
        "hair_color": {"black": 45, "dark_brown": 40, "brown": 12, "light_brown": 3},
        "eye_color": {"dark_brown": 55, "brown": 30, "hazel": 10, "green": 5},
        "hair_texture": {"straight": 42, "wavy": 40, "curly": 14, "coily": 4},
    },
}

HAIR_STYLES_MALE = ("bald", "buzz", "crew", "side_part", "crop", "curly", "afro", "waves", "fade", "long", "dreads")
HAIR_STYLES_FEMALE = ("ponytail", "bun", "long", "curly_long", "bob", "braids")
FACIAL_HAIR_STYLES = ("none", "stubble", "mustache", "goatee", "chin_strap", "short_beard", "full_beard")
HAIR_TEXTURES = ("straight", "wavy", "curly", "coily")

_MALE_STYLE_WEIGHTS = {
    "straight": {"crew": 26, "side_part": 24, "crop": 20, "buzz": 12, "fade": 8, "long": 7, "bald": 3},
    "wavy": {"crew": 20, "side_part": 18, "crop": 20, "curly": 8, "buzz": 10, "fade": 10, "long": 12, "bald": 2},
    "curly": {"curly": 34, "crop": 12, "buzz": 14, "afro": 8, "fade": 18, "long": 8, "bald": 6},
    "coily": {"buzz": 24, "waves": 18, "curly": 16, "afro": 8, "fade": 16, "dreads": 10, "bald": 8},
}
_FEMALE_STYLE_WEIGHTS = {
    "straight": {"ponytail": 34, "bun": 18, "long": 30, "bob": 18},
    "wavy": {"ponytail": 30, "bun": 18, "long": 28, "curly_long": 8, "bob": 16},
    "curly": {"ponytail": 20, "bun": 20, "curly_long": 40, "bob": 10, "braids": 10},
    "coily": {"bun": 26, "curly_long": 30, "braids": 34, "ponytail": 10},
}


@dataclass
class Genome:
    version: int = 1
    sex: str = "male"
    facial_type: str = "caucasian"
    blend_type: str | None = None
    blend: float = 0.0
    # Face structure, 0..1 with 0.5 average.
    head_width: float = 0.5
    head_length: float = 0.5
    jaw_width: float = 0.5
    jaw_square: float = 0.5
    chin_length: float = 0.5
    chin_width: float = 0.5
    cheekbones: float = 0.5
    forehead: float = 0.5
    eye_size: float = 0.5
    eye_spacing: float = 0.5
    eye_tilt: float = 0.5
    eye_lid: float = 0.5  # 0 open lid with a visible crease, 1 monolid/hooded
    brow_thickness: float = 0.5
    brow_arch: float = 0.5
    brow_height: float = 0.5
    nose_length: float = 0.5
    nose_width: float = 0.5
    nose_bridge: float = 0.5
    nose_tip: float = 0.5
    mouth_width: float = 0.5
    lip_upper: float = 0.5
    lip_lower: float = 0.5
    ear_size: float = 0.5
    ear_protrusion: float = 0.5
    # Coloring.
    skin_tone: float = 0.2  # 0 lightest .. 1 darkest
    undertone: float = 0.0  # -1 pink .. +1 olive/golden
    freckles: float = 0.0
    hair_color: str = "brown"
    eye_color: str = "brown"
    # Hair genetics.
    hair_texture: str = "straight"
    baldness: float = 0.4  # how fast the hairline recedes with age (male)
    graying_age: float = 45.0
    beard_density: float = 0.5
    # Grooming: can change during a career (see restyle()).
    hair_style: str = "crew"
    facial_hair: str = "none"
    part_side: int = 1
    smile: float = 0.2
    detail_seed: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Genome":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def with_overrides(self, overrides: dict) -> "Genome":
        """Copy with roster-supplied values (skin_tone, hair_color, hair_style, ...) applied."""
        g = copy.copy(self)
        known = {f.name: f for f in fields(Genome)}
        for key, value in overrides.items():
            if key not in known or value in (None, ""):
                continue
            current = getattr(g, key)
            if isinstance(current, float) and not isinstance(value, float):
                value = float(value)
            setattr(g, key, value)
        return g


def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    items = [(k, w) for k, w in weights.items() if w > 0]
    total = sum(w for _, w in items)
    r = rng.random() * total
    for k, w in items:
        r -= w
        if r <= 0:
            return k
    return items[-1][0]


def _sample(rng: random.Random, prior: dict, trait: str, default: tuple[float, float] = (0.5, DEFAULT_SD)) -> float:
    mean, sd = prior.get(trait, default)
    return rng.gauss(mean, sd)


def _sample_type(rng: random.Random, facial_type: str, sex: str, priors: dict) -> Genome:
    p = priors[facial_type]
    g = Genome(sex=sex, facial_type=facial_type)
    for trait in SHAPE_TRAITS:
        setattr(g, trait, clamp(_sample(rng, p, trait)))
    g.skin_tone = clamp(_sample(rng, p, "skin_tone", (0.4, 0.15)))
    g.undertone = clamp(_sample(rng, p, "undertone", (0.0, 0.3)), -1, 1)
    g.freckles = clamp(_sample(rng, p, "freckles", (0.05, 0.1)))
    g.hair_color = _weighted(rng, p.get("hair_color", {"dark_brown": 1}))
    g.eye_color = _weighted(rng, p.get("eye_color", {"brown": 1}))
    g.hair_texture = _weighted(rng, p.get("hair_texture", {"straight": 1}))
    g.baldness = clamp(_sample(rng, p, "baldness", (0.45, 0.25)))
    g.graying_age = rng.gauss(*p.get("graying_age", (46.0, 7.0)))
    g.beard_density = clamp(_sample(rng, p, "beard_density", (0.5, 0.2)))
    return g


def generate_genome(
    rng: random.Random,
    facial_type: str,
    sex: str = "male",
    blend_type: str | None = None,
    blend: float = 0.0,
    priors: dict | None = None,
) -> Genome:
    """Sample a new face. With blend_type, traits are mixed toward a second facial type by `blend` (0..1)."""
    priors = priors or FACIAL_TYPE_PRIORS
    if facial_type not in priors:
        raise ValueError(f"unknown facial type {facial_type!r}; known: {', '.join(priors)}")
    sex = "female" if str(sex).lower().startswith("f") else "male"
    g = _sample_type(rng, facial_type, sex, priors)
    if blend_type and blend_type != facial_type and blend > 0:
        other = _sample_type(rng, blend_type, sex, priors)
        for trait in SHAPE_TRAITS + ("skin_tone", "undertone", "freckles", "baldness", "graying_age", "beard_density"):
            a, b = getattr(g, trait), getattr(other, trait)
            setattr(g, trait, a + (b - a) * blend)
        for trait in ("hair_color", "eye_color", "hair_texture"):
            if rng.random() < blend:
                setattr(g, trait, getattr(other, trait))
        g.blend_type, g.blend = blend_type, round(blend, 3)
    g.part_side = rng.choice((-1, 1))
    g.smile = clamp(rng.gauss(0.2, 0.25), -0.3, 0.8)
    g.detail_seed = rng.randrange(1 << 30)
    restyle(g, rng)
    return g


def restyle(g: Genome, rng: random.Random) -> Genome:
    """Pick a new haircut and facial hair. Anatomy and coloring are untouched."""
    if g.sex == "female":
        g.hair_style = _weighted(rng, _FEMALE_STYLE_WEIGHTS[g.hair_texture])
        g.facial_hair = "none"
        return g
    g.hair_style = _weighted(rng, _MALE_STYLE_WEIGHTS[g.hair_texture])
    d = g.beard_density
    g.facial_hair = _weighted(rng, {
        "none": 34 + 30 * (1 - d),
        "stubble": 24,
        "mustache": 3 + 4 * d,
        "goatee": 6 + 12 * d,
        "chin_strap": 3 + 5 * d,
        "short_beard": 3 + 18 * d,
        "full_beard": 1 + 12 * d * d,
    })
    return g


def known_values() -> dict[str, tuple]:
    """Allowed values for categorical overrides, for validation and docs."""
    return {
        "hair_color": tuple(HAIR_COLORS),
        "eye_color": tuple(EYE_COLORS),
        "hair_style": HAIR_STYLES_MALE + HAIR_STYLES_FEMALE,
        "facial_hair": FACIAL_HAIR_STYLES,
        "hair_texture": HAIR_TEXTURES,
    }
