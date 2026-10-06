"""Small color helpers. Colors are passed around as '#rrggbb' strings."""

from __future__ import annotations


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def to_rgb(c: str) -> tuple[int, int, int]:
    c = c.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"not a hex color: {c!r}")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def to_hex(rgb) -> str:
    r, g, b = (int(round(clamp(v, 0, 255))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def is_color(c) -> bool:
    try:
        to_rgb(str(c))
        return True
    except ValueError:
        return False


def mix(a: str, b: str, t: float) -> str:
    """Blend from a (t=0) to b (t=1)."""
    ra, rb = to_rgb(a), to_rgb(b)
    return to_hex(lerp(x, y, t) for x, y in zip(ra, rb))


def darken(c: str, amount: float) -> str:
    return to_hex(v * (1 - amount) for v in to_rgb(c))


def lighten(c: str, amount: float) -> str:
    return to_hex(v + (255 - v) * amount for v in to_rgb(c))


def luminance(c: str) -> float:
    r, g, b = (v / 255 for v in to_rgb(c))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# Light to dark. Interpolated by skin_tone in [0, 1].
_SKIN_STOPS = [
    (0.00, (250, 222, 200)),
    (0.12, (240, 200, 170)),
    (0.25, (228, 180, 146)),
    (0.38, (210, 158, 120)),
    (0.50, (188, 134, 98)),
    (0.62, (163, 110, 77)),
    (0.75, (134, 87, 60)),
    (0.88, (102, 66, 46)),
    (1.00, (72, 47, 35)),
]


def skin_color(tone: float, undertone: float = 0.0) -> str:
    """tone: 0 lightest .. 1 darkest. undertone: -1 pink/cool .. +1 olive/golden."""
    tone = clamp(tone)
    for (t0, c0), (t1, c1) in zip(_SKIN_STOPS, _SKIN_STOPS[1:]):
        if tone <= t1:
            k = (tone - t0) / (t1 - t0)
            r, g, b = (lerp(x, y, k) for x, y in zip(c0, c1))
            break
    u = clamp(undertone, -1, 1)
    # Pink pushes red up and green down; olive/golden pushes green up and blue down.
    strength = 10 * (1 - tone * 0.5)
    if u < 0:
        r, g, b = r + strength * -u * 0.6, g - strength * -u, b + strength * -u * 0.2
    else:
        r, g, b = r, g + strength * u * 0.35, b - strength * u
    return to_hex((r, g, b))


HAIR_COLORS = {
    "black": "#1b1715",
    "dark_brown": "#2f2219",
    "brown": "#4b3324",
    "light_brown": "#77563a",
    "dark_blond": "#957149",
    "blond": "#c19a5f",
    "red": "#93421f",
    "auburn": "#6b2e1c",
    "gray": "#9b9893",
    "white": "#e2dfd9",
}

EYE_COLORS = {
    "dark_brown": "#3a2416",
    "brown": "#5c3b20",
    "hazel": "#7b6532",
    "green": "#5d7b4a",
    "blue": "#4e7aa6",
    "gray": "#7a8893",
}

# Team colors used when a roster gives none. Picked by hashing the team key.
TEAM_PALETTE = [
    ("#13274f", "#ce1141"),
    ("#0c2340", "#bd3039"),
    ("#002d72", "#ff5910"),
    ("#005a9c", "#ef3e42"),
    ("#27251f", "#fd5a1e"),
    ("#134a8e", "#e8291c"),
    ("#0e3386", "#cc3433"),
    ("#003831", "#efb21e"),
    ("#2f241d", "#ffc425"),
    ("#33006f", "#c4ced4"),
    ("#ba0021", "#003263"),
    ("#00a3e0", "#ef3340"),
    ("#0c2c56", "#005c5c"),
    ("#000000", "#ff6600"),
    ("#002b5c", "#d31145"),
    ("#4f2683", "#ffc62f"),
    ("#006847", "#ffffff"),
    ("#7a0019", "#ffcc33"),
]
