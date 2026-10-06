"""Vector primitives shared by the SVG and PNG backends.

Portraits are drawn in a fixed 200 x 300 design space (the 2:3 shape OOTP uses for player pictures).
Every drawable is a Shape (filled and/or stroked path) or a Text; the backends only scale them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DESIGN_W = 200.0
DESIGN_H = 300.0

Point = tuple[float, float]


class Path:
    """A list of subpaths made of move/line/cubic commands. Several subpaths in one path are unioned."""

    __slots__ = ("cmds",)

    def __init__(self) -> None:
        self.cmds: list[tuple] = []

    def M(self, x: float, y: float) -> "Path":
        self.cmds.append(("M", x, y))
        return self

    def L(self, x: float, y: float) -> "Path":
        self.cmds.append(("L", x, y))
        return self

    def C(self, x1: float, y1: float, x2: float, y2: float, x: float, y: float) -> "Path":
        self.cmds.append(("C", x1, y1, x2, y2, x, y))
        return self

    def Q(self, x1: float, y1: float, x: float, y: float) -> "Path":
        # Stored as a cubic so the backends only deal with one curve type.
        x0, y0 = self._current()
        return self.C(x0 + (x1 - x0) * 2 / 3, y0 + (y1 - y0) * 2 / 3, x + (x1 - x) * 2 / 3, y + (y1 - y) * 2 / 3, x, y)

    def Z(self) -> "Path":
        self.cmds.append(("Z",))
        return self

    def add(self, other: "Path") -> "Path":
        self.cmds.extend(other.cmds)
        return self

    def _current(self) -> Point:
        for cmd in reversed(self.cmds):
            if cmd[0] != "Z":
                return cmd[-2], cmd[-1]
        return 0.0, 0.0

    def svg(self) -> str:
        out = []
        for cmd in self.cmds:
            if cmd[0] == "Z":
                out.append("Z")
            else:
                out.append(cmd[0] + " ".join(_num(v) for v in cmd[1:]))
        return "".join(out)

    def subpath_strings(self) -> list[str]:
        """One SVG path string per subpath."""
        parts, cur = [], Path()
        for cmd in self.cmds:
            if cmd[0] == "M" and cur.cmds:
                parts.append(cur.svg())
                cur = Path()
            cur.cmds.append(cmd)
        if cur.cmds:
            parts.append(cur.svg())
        return parts

    def flatten(self, step: float = 1.5) -> list[tuple[list[Point], bool]]:
        """Polylines (points, closed) approximating each subpath. step is the target segment length."""
        polys: list[tuple[list[Point], bool]] = []
        pts: list[Point] = []
        start: Point = (0.0, 0.0)
        for cmd in self.cmds:
            op = cmd[0]
            if op == "M":
                if len(pts) > 1:
                    polys.append((pts, False))
                start = (cmd[1], cmd[2])
                pts = [start]
            elif op == "L":
                pts.append((cmd[1], cmd[2]))
            elif op == "C":
                p0 = pts[-1] if pts else start
                p1, p2, p3 = (cmd[1], cmd[2]), (cmd[3], cmd[4]), (cmd[5], cmd[6])
                est = _dist(p0, p1) + _dist(p1, p2) + _dist(p2, p3)
                n = max(2, min(96, int(est / step) + 1))
                for i in range(1, n + 1):
                    pts.append(_cubic(p0, p1, p2, p3, i / n))
            elif op == "Z":
                if len(pts) > 1:
                    polys.append((pts, True))
                pts = []
        if len(pts) > 1:
            polys.append((pts, False))
        return polys


@dataclass
class Shape:
    path: Path
    fill: str | None = None
    stroke: str | None = None
    width: float = 1.0
    opacity: float = 1.0
    blur: float = 0.0
    clip: Path | None = None


@dataclass
class Picture:
    """A raster image (PNG bytes) placed at x, y with size w x h in design units. Used for photo mode."""

    png: bytes
    x: float
    y: float
    w: float
    h: float
    clip: Path | None = None


@dataclass
class Text:
    x: float
    y: float
    text: str
    size: float
    fill: str
    stroke: str | None = None
    stroke_width: float = 0.0
    opacity: float = 1.0


def _num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def spline(points: list[Point], closed: bool = False, tension: list[float] | float = 0.0, path: Path | None = None) -> Path:
    """Smooth curve through every point (cardinal spline). tension 0 is smooth, 1 makes a sharp corner."""
    n = len(points)
    if isinstance(tension, (int, float)):
        tension = [float(tension)] * n
    path = path or Path()
    path.M(*points[0])
    segments = n if closed else n - 1
    for i in range(segments):
        p0 = points[(i - 1) % n] if (closed or i > 0) else points[i]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n] if (closed or i + 2 < n) else p2
        t1 = (1 - tension[i]) / 6
        t2 = (1 - tension[(i + 1) % n]) / 6
        path.C(
            p1[0] + (p2[0] - p0[0]) * t1,
            p1[1] + (p2[1] - p0[1]) * t1,
            p2[0] - (p3[0] - p1[0]) * t2,
            p2[1] - (p3[1] - p1[1]) * t2,
            p2[0],
            p2[1],
        )
    if closed:
        path.Z()
    return path


def ellipse(cx: float, cy: float, rx: float, ry: float, rotate_deg: float = 0.0, path: Path | None = None) -> Path:
    """Closed ellipse, always wound the same way so unions behave."""
    k = 0.5522847498
    a = math.radians(rotate_deg)
    ca, sa = math.cos(a), math.sin(a)

    def tr(x: float, y: float) -> Point:
        return cx + x * ca - y * sa, cy + x * sa + y * ca

    path = path or Path()
    path.M(*tr(rx, 0))
    path.C(*tr(rx, ry * k), *tr(rx * k, ry), *tr(0, ry))
    path.C(*tr(-rx * k, ry), *tr(-rx, ry * k), *tr(-rx, 0))
    path.C(*tr(-rx, -ry * k), *tr(-rx * k, -ry), *tr(0, -ry))
    path.C(*tr(rx * k, -ry), *tr(rx, -ry * k), *tr(rx, 0))
    return path.Z()


def rect(x: float, y: float, w: float, h: float) -> Path:
    return Path().M(x, y).L(x + w, y).L(x + w, y + h).L(x, y + h).Z()


def polyline_length(pts: list[Point]) -> float:
    return sum(_dist(a, b) for a, b in zip(pts, pts[1:]))


def resample(pts: list[Point], spacing: float) -> list[tuple[Point, Point]]:
    """Evenly spaced (point, unit normal) pairs along a polyline. The normal points to the left of travel."""
    out: list[tuple[Point, Point]] = []
    if len(pts) < 2:
        return out
    carry = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = _dist(a, b)
        if seg == 0:
            continue
        dx, dy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
        pos = carry
        while pos <= seg:
            out.append(((a[0] + dx * pos, a[1] + dy * pos), (dy, -dx)))
            pos += spacing
        carry = pos - seg
    return out


def x_at(poly: list[Point], y: float, side: int) -> float | None:
    """Rightmost (side=+1) or leftmost (side=-1) x where a closed polygon crosses height y."""
    best = None
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        if (y0 <= y < y1) or (y1 <= y < y0):
            x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if best is None or (x - best) * side > 0:
                best = x
    return best
