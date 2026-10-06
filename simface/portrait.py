"""Turns a Genome plus per-season context (age, build, team colors, uniform) into a list of shapes.

Everything is laid out in the 200 x 300 design space. Light comes from the upper left, so the viewer's right
side of every feature gets the shadows.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .colors import (
    EYE_COLORS, HAIR_COLORS, clamp, darken, lerp, lighten, luminance, mix, skin_color,
)
from .genome import Genome
from .geometry import Path, Picture, Shape, Text, ellipse, resample, spline, x_at

CX = 100.0
UNIFORMS = ("baseball", "crew", "pads", "tank", "none")
HEADWEAR = ("cap", "none")


@dataclass
class RenderContext:
    """Things that change over a career or between teams. The genome stays fixed."""

    age: float = 27.0
    bmi: float = 25.0
    uniform: str = "crew"  # baseball | crew | pads | tank | none
    headwear: str = "none"  # cap | none
    # Kit colors (see teams.py for real teams).
    jersey: str = "#13274f"
    trim: str = "#ce1141"
    trim2: str | None = None
    pinstripes: str | None = None
    cap: str = "#13274f"
    cap_brim: str | None = None
    logo: str = ""
    logo_color: str = "#ffffff"
    logo_outline: str | None = None
    background: str | None = None
    # Photo mode: skin color sampled from the player's photo, used for the drawn neck.
    skin: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "RenderContext":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class _Layout:
    """Key measurements of the face, derived from the genome, age and build."""

    def __init__(self, g: Genome, ctx: RenderContext):
        self.g = g
        self.ctx = ctx
        self.age = ctx.age
        # 0 for an athletic build (BMI ~25); heavier players get fuller faces.
        self.fat = clamp((ctx.bmi - 25.5) / 8.0, -0.4, 1.0)
        fat = self.fat
        L = g.head_length
        male = g.sex == "male"
        self.male = male
        self.crown_y = lerp(58, 51, L)
        self.eye_y = 138 + (L - 0.5) * 3
        self.cheek_hw = lerp(45.5, 55.5, g.head_width) + fat * 6 - (0 if male else 2)
        self.temple_hw = self.cheek_hw * lerp(0.91, 0.84, g.cheekbones)
        jaw = lerp(38, 48, g.jaw_width) if male else lerp(33, 41, g.jaw_width)
        self.jaw_hw = min(jaw + fat * 8, self.cheek_hw - 1.0)
        self.chin_hw = (lerp(12, 20, g.chin_width) if male else lerp(8, 14, g.chin_width)) + fat * 5 + g.jaw_square * 2
        self.nose_y = self.eye_y + lerp(25, 32, g.nose_length)
        self.mouth_y = self.nose_y + lerp(14, 17.5, g.chin_length * 0.4 + 0.3)
        self.chin_y = lerp(self.mouth_y + 27, self.mouth_y + 35, g.chin_length) + fat * 2.5
        self.jaw_y = lerp(self.mouth_y - 4, self.mouth_y + 9, g.jaw_square) if male else lerp(self.mouth_y - 8, self.mouth_y + 3, g.jaw_square)
        self.eye_sep = lerp(18.5, 22.5, g.eye_spacing)
        self.ew = lerp(18.5, 22.5, g.eye_size)
        self.eh = (lerp(3.9, 5.1, g.eye_size) if male else lerp(4.3, 5.6, g.eye_size)) * (1 - 0.2 * g.eye_lid)
        self.brow_y = self.eye_y - (lerp(8.5, 12.5, g.brow_height) if male else lerp(10, 14.5, g.brow_height))
        self.nw = lerp(8.5, 13.5, g.nose_width) + (0.8 if male else -0.5)
        self.mw = lerp(15.5, 20.5, g.mouth_width)
        self.lip_up = lerp(1.8, 4.4, g.lip_upper) if male else lerp(2.4, 5.0, g.lip_upper)
        self.lip_lo = lerp(2.9, 6.2, g.lip_lower) if male else lerp(3.4, 6.8, g.lip_lower)
        neck = lerp(28, 33, g.jaw_width) if male else lerp(21, 25, g.jaw_width)
        self.neck_hw = neck + fat * 7 + (3 if ctx.uniform == "pads" else 0)

        # Receding hairline (men only), from genetics and age.
        self.recession = 0.0
        if g.sex == "male":
            self.recession = clamp(g.baldness * (self.age - 21) / 22, 0, 1)
        self.hairline_y = self.crown_y + lerp(34, 42, g.forehead) + self.recession * 14

        self.face = self._face_path()
        self.face_poly = self.face.flatten(step=1.0)[0][0]

        # Colors.
        self.skin = ctx.skin or skin_color(g.skin_tone, g.undertone)
        self.shadow = darken(mix(self.skin, "#7a3b2a", 0.18), 0.22)
        self.deep = darken(mix(self.skin, "#4a2418", 0.25), 0.45)
        self.highlight = lighten(self.skin, 0.28)
        self.line = darken(mix(self.skin, "#3a1f17", 0.3), 0.5)
        lip_red = lerp(0.24, 0.06, g.skin_tone) if g.sex == "male" else lerp(0.42, 0.14, g.skin_tone)
        self.lip = mix(darken(self.skin, 0.12 + 0.12 * g.skin_tone), "#9c4d47", lip_red)

        base_hair = HAIR_COLORS.get(g.hair_color, HAIR_COLORS["brown"])
        gray = clamp((self.age - g.graying_age) / 20, 0, 1)
        self.hair = mix(mix(base_hair, HAIR_COLORS["gray"], gray * 0.85), HAIR_COLORS["white"], clamp(gray - 0.7, 0, 0.3))
        beard_base = base_hair
        if g.hair_color in ("blond", "dark_blond", "light_brown"):
            beard_base = mix(base_hair, "#7f4524", 0.25)
        beard_gray = clamp((self.age - g.graying_age + 4) / 18, 0, 1)
        self.beard = mix(beard_base, HAIR_COLORS["gray"], beard_gray * 0.85)
        brow_base = darken(base_hair, 0.12) if luminance(base_hair) > 0.25 else base_hair
        self.brow = mix(brow_base, HAIR_COLORS["gray"], gray * 0.4)

    def _face_path(self) -> Path:
        sq = self.g.jaw_square
        right = [
            (CX + self.temple_hw * 0.6, self.crown_y + 8),
            (CX + self.temple_hw * 0.92, self.crown_y + 25),
            (CX + self.temple_hw, self.eye_y - 30),
            (CX + self.cheek_hw, self.eye_y + 8),
            (CX + self.jaw_hw, self.jaw_y),
            (CX + self.chin_hw, self.chin_y - lerp(3, 7, sq)),
            (CX + self.chin_hw * 0.45, self.chin_y - 0.6),
        ]
        rt = [0, 0, 0, 0, lerp(0.1, 0.5, sq), lerp(0, 0.4, sq), 0]
        pts = [(CX, self.crown_y)] + right + [(CX, self.chin_y)] + [(2 * CX - x, y) for x, y in reversed(right)]
        tens = [0.0] + rt + [0.0] + list(reversed(rt))
        return spline(pts, closed=True, tension=tens)

    def edge(self, y: float) -> float:
        """Half-width of the face outline at height y."""
        x = x_at(self.face_poly, y, +1)
        return (x - CX) if x is not None else self.cheek_hw * 0.5


class PortraitBuilder:
    def __init__(self, genome: Genome, ctx: RenderContext):
        self.g = genome
        self.ctx = ctx
        self.f = _Layout(genome, ctx)
        self.items: list = []
        self.rng = random.Random(genome.detail_seed)
        self.style = genome.hair_style
        if genome.sex == "male" and self.f.recession > 0.62 and self.style not in ("long", "dreads", "afro", "bald"):
            self.style = "horseshoe"

    def add(self, path: Path, **kw) -> Shape:
        s = Shape(path, **kw)
        self.items.append(s)
        return s

    def build_photo(self, photo) -> list:
        """Photo mode: drawn uniform and neck, the player's cut-out head on top, then the team cap."""
        f = self.f
        k = 2 * f.eye_sep / _photo_eye_dist()
        x, y = CX - photo.eye_x * k, f.eye_y - photo.eye_y * k
        # Size the cap to the real head instead of the genome's.
        f.temple_hw = clamp(photo.head_half_width * k - 2.0, 36, 58)
        f.crown_y = clamp(y + photo.head_top * k + 7, f.eye_y - 95, f.eye_y - 72)
        f.neck_hw = clamp(photo.neck_half_width * k, 20, 38) + (3 if self.ctx.uniform == "pads" else 0)
        f.chin_y = y + photo.chin_y * k - 4
        f.jaw_y = f.chin_y - 14
        f.jaw_hw = f.neck_hw * 1.35
        self.body()
        clip = None
        if self.ctx.headwear == "cap":
            # Hide hair that would poke out above the cap.
            brim_y = f.brow_y - 4.5
            thw = f.temple_hw
            clip = (Path().M(-20, brim_y - 3).L(CX - thw - 4.5, brim_y - 3)
                    .add(self._cap_crown_curve(brim_y, open_path=True))
                    .L(220, brim_y - 3).L(220, 320).L(-20, 320).Z())
        self.items.append(Picture(photo.png, x, y, photo.width * k, photo.height * k, clip=clip))
        if self.ctx.headwear == "cap":
            self.cap()
        return self.items

    def build(self) -> list:
        self.hair_back()
        self.body()
        self.ears()
        self.head()
        self.age_marks()
        self.facial_hair(layer="base")
        self.eyes()
        self.brows()
        self.nose()
        self.mouth()
        self.facial_hair(layer="mustache")
        self.hair_front()
        if self.ctx.headwear == "cap":
            self.cap()
        return self.items

    # ------------------------------------------------------------------ body

    def _neckline(self, sy: float):
        """Quadratic (left, control, right) the collar follows; the neck is hidden just below it."""
        f, u = self.f, self.ctx.uniform
        nhw = f.neck_hw
        if u == "baseball":
            return (CX - nhw - 1, sy + 1), (CX, sy + 15), (CX + nhw + 1, sy + 1)
        return (CX - nhw - 4, sy - 1), (CX, sy + 21), (CX + nhw + 4, sy - 1)

    def _shoulder_lines(self, u: str, nhw: float, sy: float) -> Path:
        out = Path()
        for s in (-1, 1):
            if u == "pads":
                out.M(CX + s * (nhw + 12), sy - 4).C(CX + s * 88, sy - 14, CX + s * 112, sy - 10, CX + s * 112, sy + 14)
            else:
                out.M(CX + s * (nhw + 14), sy).C(CX + s * 84, sy + 5, CX + s * 112, sy + 14, CX + s * 112, sy + 28)
        return out

    def body(self) -> None:
        f, ctx = self.f, self.ctx
        u = ctx.uniform if ctx.uniform in UNIFORMS else "crew"
        jersey, trim = ctx.jersey, ctx.trim
        if u == "none":
            jersey = trim = "#3b4048"
        nhw = f.neck_hw
        sy = 237.0  # where the neck meets the shoulders

        # Shoulders. Football pads sit higher and wider.
        if u == "pads":
            torso = (Path().M(-12, 310).L(-12, sy + 14).C(-12, sy - 10, 12, sy - 14, CX - nhw - 12, sy - 4)
                     .L(CX + nhw + 12, sy - 4).C(188, sy - 14, 212, sy - 10, 212, sy + 14).L(212, 310).Z())
        else:
            torso = (Path().M(-12, 310).L(-12, sy + 28).C(-12, sy + 14, 16, sy + 5, CX - nhw - 14, sy)
                     .L(CX + nhw + 14, sy).C(184, sy + 5, 212, sy + 14, 212, sy + 28).L(212, 310).Z())
        self.add(torso, fill=f.skin if u == "tank" else jersey)
        if u == "tank":
            for s in (-1, 1):
                self.add(ellipse(CX + s * 84, sy + 30, 20, 26), fill=f.shadow, opacity=0.35, blur=7, clip=torso)
                self.add(ellipse(CX + s * 70, sy + 13, 14, 6), fill=f.highlight, opacity=0.25, blur=4, clip=torso)
            self.add(self._shoulder_lines(u, nhw, sy), stroke=f.deep, width=1.0, opacity=0.35)
        elif ctx.pinstripes:
            stripes = Path()
            for k in range(-12, 13):
                x = CX + k * 7.5
                stripes.M(x, sy - 20).L(x, 312)
            self.add(stripes, stroke=ctx.pinstripes, width=0.7, opacity=0.75, clip=torso)
        undershirt = ctx.trim2 or (darken(trim, 0.2) if luminance(jersey) > 0.6 else darken(jersey, 0.45))
        if u == "baseball":
            vee = Path().M(CX - nhw - 7, sy).L(CX, sy + 28).L(CX + nhw + 7, sy).Z()
            self.add(vee, fill=undershirt)

        # Neck, cut off just under the collar.
        (lx, ly), (qx, qy), (rx, ry) = self._neckline(sy)
        top = f.jaw_y - 8
        neck = Path().M(CX - nhw, top).L(CX - nhw, sy - 14).Q(CX - nhw - 1, sy - 3, CX - nhw - 10, sy + 3)
        if u == "tank":
            neck.L(CX - nhw - 12, 300).L(CX + nhw + 12, 300)
        else:
            neck.L(lx, ly + 3).Q(qx, qy + 3, rx, ry + 3)
        neck.L(CX + nhw + 10, sy + 3).Q(CX + nhw + 1, sy - 3, CX + nhw, sy - 14).L(CX + nhw, top).Z()
        self.add(neck, fill=f.skin)
        self.add(neck, fill=darken(f.skin, 0.06), opacity=0.6)
        self.add(ellipse(CX, f.chin_y + 3, f.jaw_hw * 0.95, 14), fill=f.deep, opacity=0.45, blur=4.5, clip=neck)
        self.add(ellipse(CX + nhw, sy - 8, 6, 30), fill=f.shadow, opacity=0.35, blur=4, clip=neck)
        if f.male:
            self.add(ellipse(CX + 1, f.chin_y + 19, 3.2, 4.5), fill=f.shadow, opacity=0.18, blur=1.8, clip=neck)
            self.add(ellipse(CX - 1, f.chin_y + 17, 2.2, 3), fill=f.highlight, opacity=0.18, blur=1.5, clip=neck)
        for s in (-1, 1):
            self.add(Path().M(CX + s * nhw, top + 10).L(CX + s * nhw, sy - 14).Q(CX + s * (nhw + 1), sy - 3, CX + s * (nhw + 10), sy + 3),
                     stroke=f.deep, width=0.9, opacity=0.35)

        if u == "tank":
            arm_l = [(CX - nhw - 7, sy), (CX - nhw - 21, sy)]
            tank = (Path().M(*arm_l[0]).L(*arm_l[1])
                    .C(CX - nhw - 25, sy + 22, CX - 60, sy + 36, CX - 70, 310).L(CX + 70, 310)
                    .C(CX + 60, sy + 36, CX + nhw + 25, sy + 22, CX + nhw + 21, sy).L(CX + nhw + 7, sy)
                    .C(CX + nhw + 4, sy + 20, CX + 12, sy + 33, CX, sy + 34)
                    .C(CX - 12, sy + 33, CX - nhw - 4, sy + 20, CX - nhw - 7, sy).Z())
            self.add(tank, fill=jersey)
            if ctx.pinstripes:
                stripes = Path()
                for k in range(-10, 11):
                    stripes.M(CX + k * 7.5, sy - 5).L(CX + k * 7.5, 312)
                self.add(stripes, stroke=ctx.pinstripes, width=0.7, opacity=0.75, clip=tank)
            trim_path = Path()
            for s in (-1, 1):
                trim_path.M(CX + s * (nhw + 21), sy).C(CX + s * (nhw + 25), sy + 22, CX + s * 60, sy + 36, CX + s * 70, 310)
            trim_path.M(CX + nhw + 7, sy).C(CX + nhw + 4, sy + 20, CX + 12, sy + 33, CX, sy + 34).C(CX - 12, sy + 33, CX - nhw - 4, sy + 20, CX - nhw - 7, sy)
            if ctx.trim2:
                self.add(trim_path, stroke=ctx.trim2, width=4.4)
            self.add(trim_path, stroke=trim, width=2.6)
            self.add(ellipse(CX, sy + 6, nhw + 8, 7), fill="#000000", opacity=0.2, blur=4, clip=tank)
            self.add(ellipse(CX + 70, 290, 16, 40), fill="#000000", opacity=0.15, blur=9, clip=tank)
            return

        collar = Path().M(lx, ly).Q(qx, qy, rx, ry)
        if u == "baseball":
            self.add(collar, stroke=darken(undershirt, 0.15), width=4.2)
            for s in (-1, 1):
                piping = Path().M(CX + s * (nhw + 7), sy).L(CX, sy + 28)
                if ctx.trim2:
                    self.add(piping, stroke=ctx.trim2, width=3.4)
                self.add(piping, stroke=trim, width=1.9)
            self.add(Path().M(CX, sy + 28).L(CX, 310), stroke=darken(jersey, 0.25), width=0.9)
            button = lighten(jersey, 0.5) if luminance(jersey) < 0.5 else darken(jersey, 0.3)
            for by in (sy + 40, sy + 54):
                self.add(ellipse(CX + 2.4, by, 1.3, 1.3), fill=button)
        else:
            if ctx.trim2:
                self.add(collar, stroke=ctx.trim2, width=7.4)
            self.add(collar, stroke=trim, width=5.2)
            if u == "pads":
                for s in (-1, 1):
                    for k, color in ((0, trim), (6, ctx.trim2 or trim)):
                        stripe = Path().M(CX + s * (62 + k), sy + k * 0.2).Q(CX + s * (79 + k), sy - 9, CX + s * (98 + k), sy + 5 + k * 0.6)
                        self.add(stripe, stroke=color, width=2.6)
        # Shadow cast by the head on the chest, and fabric shading on the far shoulder.
        self.add(ellipse(CX, sy + 10, nhw + 10, 8), fill="#000000", opacity=0.18, blur=4, clip=torso)
        self.add(ellipse(CX + 86, sy + 40, 22, 40), fill="#000000", opacity=0.18, blur=10, clip=torso)
        self.add(self._shoulder_lines(u, nhw, sy), stroke="#000000", width=0.9, opacity=0.25)

    # ------------------------------------------------------------------ head

    def ears(self) -> None:
        f, g = self.f, self.g
        top = f.eye_y - lerp(5, 9, g.ear_size)
        bot = f.nose_y + lerp(-2, 3, g.ear_size)
        length = bot - top
        w = lerp(7.5, 11.5, g.ear_protrusion)
        for s in (-1, 1):
            ax = CX + s * (f.edge((top + bot) / 2) - 3.5)
            ear = (Path().M(ax, top + 2)
                   .C(ax + s * w * 0.8, top - 4, ax + s * (w + 2.5), top + length * 0.3, ax + s * w * 0.8, top + length * 0.6)
                   .C(ax + s * w * 0.55, bot - 4, ax + s * w * 0.65, bot + 1.5, ax + s * 1.5, bot)
                   .L(ax - s * 4, bot).L(ax - s * 4, top + 2).Z())
            self.add(ear, fill=mix(f.skin, f.shadow, 0.25))
            inner = (Path().M(ax + s * w * 0.25, top + 5)
                     .C(ax + s * w * 0.8, top + 2, ax + s * w * 0.95, top + length * 0.35, ax + s * w * 0.45, top + length * 0.68))
            self.add(inner, stroke=f.deep, width=1.6, opacity=0.45, blur=0.5)
            self.add(ellipse(ax + s * w * 0.3, top + length * 0.45, w * 0.22, length * 0.15), fill=f.deep, opacity=0.35, blur=1.2, clip=ear)
            if s == 1:
                self.add(ear, fill=f.shadow, opacity=0.25)

    def head(self) -> None:
        f, g = self.f, self.g
        face = f.face
        self.add(face, fill=f.skin)
        # Light ink outline for the illustrated look.
        self.add(face, stroke=f.deep, width=1.0, opacity=0.4)
        # Form shading, clipped to the face so it never spills.
        self.add(ellipse(CX + f.cheek_hw + 8, f.eye_y + 12, 20, 95), fill=f.shadow, opacity=0.5, blur=10, clip=face)
        self.add(ellipse(CX - f.cheek_hw - 10, f.eye_y + 12, 16, 95), fill=f.shadow, opacity=0.22, blur=9, clip=face)
        self.add(ellipse(CX, f.chin_y + 10, f.jaw_hw, 12), fill=f.shadow, opacity=0.35, blur=6, clip=face)
        self.add(ellipse(CX - 8, f.eye_y - 36, 24, 13), fill=f.highlight, opacity=0.35, blur=8, clip=face)
        self.add(ellipse(CX - 24, f.eye_y + 16, 9, 6), fill=f.highlight, opacity=0.2, blur=5, clip=face)
        self.add(ellipse(CX + 24, f.eye_y + 16, 8, 5), fill=f.highlight, opacity=0.1, blur=5, clip=face)
        self.add(ellipse(CX, f.chin_y - 8, 7, 4), fill=f.highlight, opacity=0.22, blur=3, clip=face)
        hollow = clamp(0.06 + 0.16 * g.cheekbones - 0.18 * max(f.fat, 0), 0, 0.25)
        for s in (-1, 1):
            self.add(ellipse(CX + s * (f.cheek_hw - 13), f.mouth_y - 9, 7, 12), fill=f.shadow, opacity=hollow * (1.4 if s == 1 else 0.8), blur=5, clip=face)
        # Temple shading near the hairline.
        for s in (-1, 1):
            self.add(ellipse(CX + s * (f.temple_hw - 2), f.eye_y - 26, 7, 14), fill=f.shadow, opacity=0.25, blur=5, clip=face)
        if f.fat > 0.3:
            dc = Path().M(CX - f.chin_hw - 6, f.chin_y - 1).Q(CX, f.chin_y + 10 * f.fat, CX + f.chin_hw + 6, f.chin_y - 1)
            self.add(dc, stroke=f.shadow, width=1.6, opacity=0.5 * f.fat, blur=1.2)
            for s in (-1, 1):
                self.add(ellipse(CX + s * (f.cheek_hw - 12), f.mouth_y - 2, 10, 12), fill=f.highlight, opacity=0.18 * f.fat, blur=5, clip=face)
        if g.freckles > 0.45:
            n = int((g.freckles - 0.45) * 70)
            dots = Path()
            for _ in range(n):
                fx = CX + self.rng.choice((-1, 1)) * self.rng.uniform(3, 32)
                fy = f.nose_y - self.rng.uniform(2, 20)
                ellipse(fx, fy, self.rng.uniform(0.45, 0.85), self.rng.uniform(0.45, 0.8), path=dots)
            self.add(dots, fill=darken(f.skin, 0.28), opacity=0.4, clip=face)

    def age_marks(self) -> None:
        f, g = self.f, self.g
        k = clamp((f.age - 26) / 26, 0, 1)
        if k > 0:
            for i in range(3 if f.age > 40 else 2):
                y = f.brow_y - 11 - i * 5.5
                if y < f.hairline_y + 3:
                    break
                line = Path().M(CX - 17 + i, y + 1.2).Q(CX, y - 1.8, CX + 17 - i, y + 1.2)
                self.add(line, stroke=f.line, width=0.8, opacity=0.28 * k, blur=0.4)
        if f.age > 31:
            k2 = clamp((f.age - 31) / 20, 0, 1)
            for s in (-1, 1):
                ox = CX + s * (f.eye_sep + f.ew / 2 + 1.5)
                for dy in (-2.5, 0.5, 3.5):
                    self.add(Path().M(ox, f.eye_y + dy * 0.5).L(ox + s * 4.5, f.eye_y + dy), stroke=f.line, width=0.6, opacity=0.35 * k2, blur=0.3)
                bag = Path().M(CX + s * (f.eye_sep - f.ew * 0.4), f.eye_y + f.eh + 3).Q(CX + s * f.eye_sep, f.eye_y + f.eh + 5.5, CX + s * (f.eye_sep + f.ew * 0.45), f.eye_y + f.eh + 2)
                self.add(bag, stroke=f.shadow, width=1.0, opacity=0.35 * k2, blur=0.6)
        # Nose-to-mouth folds deepen with age and weight.
        depth = clamp(0.12 + 0.3 * k + 0.12 * max(f.fat, 0) + 0.08 * g.cheekbones, 0, 0.55)
        for s in (-1, 1):
            fold = (Path().M(CX + s * (f.nw + 1.5), f.nose_y - 5)
                    .C(CX + s * (f.nw + 6), f.nose_y + 3, CX + s * (f.mw + 4.5), f.mouth_y - 5, CX + s * (f.mw + 3.5), f.mouth_y + 5))
            self.add(fold, stroke=f.shadow, width=1.6, opacity=depth * (1.2 if s == 1 else 0.8), blur=1.0)
            if f.age > 46:
                mar = Path().M(CX + s * (f.mw + 2), f.mouth_y + 3).Q(CX + s * (f.mw + 3), f.mouth_y + 10, CX + s * (f.mw + 1), f.chin_y - 8)
                self.add(mar, stroke=f.shadow, width=1.1, opacity=0.3 * k, blur=0.8)

    # ------------------------------------------------------------------ features

    def eyes(self) -> None:
        f, g = self.f, self.g
        iris_base = EYE_COLORS.get(g.eye_color, EYE_COLORS["brown"])
        tilt = lerp(-1.6, 2.6, g.eye_tilt)
        ew, eh, ey = f.ew, f.eh, f.eye_y
        for s in (-1, 1):
            ex = CX + s * f.eye_sep
            inner = (ex - s * ew / 2, ey + tilt / 2)
            outer = (ex + s * ew / 2, ey - tilt / 2)
            c1 = (inner[0] + s * ew * 0.2, ey - eh * 1.3)
            c2 = (outer[0] - s * ew * 0.3, ey - eh * 1.15 - tilt * 0.3)
            c3 = (outer[0] - s * ew * 0.28, ey + eh * 0.85)
            c4 = (inner[0] + s * ew * 0.32, ey + eh * 0.8)
            opening = Path().M(*inner).C(*c1, *c2, *outer).C(*c3, *c4, *inner).Z()
            upper = Path().M(*inner).C(*c1, *c2, *outer)
            lower = Path().M(*outer).C(*c3, *c4, *inner)

            # Socket shading above and around the eye.
            self.add(ellipse(ex - s * 2, ey - eh - 1.5, ew * 0.62, 5.5), fill=f.shadow, opacity=0.32, blur=3)
            self.add(ellipse(ex - s * (ew * 0.55), ey - 1, 3.5, 5), fill=f.shadow, opacity=0.2, blur=2.5)
            gap = lerp(3.4, 1.4, g.eye_lid)
            crease = Path().M(inner[0] + s * 1.5, inner[1] - gap * 0.6).C(c1[0], c1[1] - gap, c2[0], c2[1] - gap, outer[0] - s * 0.5, outer[1] - gap * 0.6)
            self.add(crease, stroke=f.line, width=0.9, opacity=lerp(0.5, 0.12, g.eye_lid), blur=0.35)

            self.add(opening, fill="#efe8e1")
            self.add(ellipse(inner[0] + s * 1.4, inner[1], 1.8, 1.4), fill="#d79a90", opacity=0.7, clip=opening)
            ir = ew * 0.235
            ix, iy = ex + s * 0.2, ey - eh * 0.1
            self.add(ellipse(ix, iy, ir, ir), fill=iris_base, clip=opening)
            self.add(ellipse(ix + 0.3, iy + 0.8, ir * 0.7, ir * 0.7), fill=lighten(iris_base, 0.18), opacity=0.55, blur=0.6, clip=opening)
            self.add(ellipse(ix, iy, ir, ir), stroke=darken(iris_base, 0.5), width=0.7, opacity=0.8, clip=opening)
            self.add(ellipse(ix, iy, ir * 0.42, ir * 0.42), fill="#0d0a09", clip=opening)
            # Lid shadow on the eyeball, then a catch light.
            self.add(upper, stroke="#2a1a14", width=eh * 1.2, opacity=0.4, blur=1.1, clip=opening)
            self.add(ellipse(ix - 1.4, iy - 1.5, 1.05, 1.05), fill="#ffffff", opacity=0.9)
            # Lash line; women get a small flick at the outer corner.
            lash = Path().M(*inner).C(*c1, *c2, *outer)
            if f.male:
                self.add(lash, stroke="#21150f", width=lerp(1.05, 1.3, g.eye_size), opacity=0.85)
            else:
                lash.L(outer[0] + s * 1.4, outer[1] - 0.9)
                self.add(lash, stroke="#1b120e", width=lerp(1.35, 1.7, g.eye_size), opacity=0.92)
            self.add(lower, stroke=f.line, width=0.75, opacity=0.4)

    def brows(self) -> None:
        f, g = self.f, self.g
        if f.male:
            thick, arch = lerp(2.6, 5.0, g.brow_thickness), lerp(0.2, 2.6, g.brow_arch)
        else:
            thick, arch = lerp(1.6, 3.4, g.brow_thickness), lerp(1.2, 4.2, g.brow_arch)
        for s in (-1, 1):
            ex = CX + s * f.eye_sep
            x_in, x_out = ex - s * f.ew * 0.6, ex + s * f.ew * 0.68
            y_in = f.brow_y + 1.5
            y_peak = f.brow_y - arch
            x_peak = ex + s * f.ew * 0.22
            y_out = f.brow_y + 2.2
            top = [(x_in, y_in - thick), (x_peak, y_peak - thick * 0.75), (x_out, y_out - 0.4)]
            bot = [(x_out + s * 0.6, y_out + 0.5), (x_peak, y_peak + thick * 0.2), (x_in + s * 0.5, y_in + 0.6)]
            brow = spline(top + bot, closed=True, tension=[0.6, 0, 0.8, 0.8, 0, 0.6])
            self.add(brow, fill=self.f.brow, opacity=0.92, blur=0.35)
            # Hair strokes at the thick inner end.
            hairs = Path()
            for i in range(4):
                hx = x_in + s * (0.6 + i * 1.3)
                hairs.M(hx, y_in + 0.5).L(hx + s * 1.2, y_in - thick - 0.4)
            self.add(hairs, stroke=f.brow, width=0.55, opacity=0.6)

    def nose(self) -> None:
        f, g = self.f, self.g
        ny, nw = f.nose_y, f.nw
        bridge = g.nose_bridge
        for s, strength in ((1, 1.0), (-1, 0.45)):
            side = (Path().M(CX + s * 4.5, f.eye_y - 3)
                    .C(CX + s * lerp(7, 5, bridge), f.eye_y + 10, CX + s * nw * 0.55, ny - 15, CX + s * nw * 0.75, ny - 6))
            self.add(side, stroke=f.shadow, width=lerp(5, 3, bridge), opacity=lerp(0.18, 0.38, bridge) * strength, blur=2.0)
        self.add(Path().M(CX - 1.2, f.eye_y + 4).L(CX - 1.6, ny - 10), stroke=f.highlight, width=2.2, opacity=lerp(0.1, 0.3, bridge), blur=1.4)
        tip_r = lerp(3, 4.8, g.nose_tip)
        self.add(ellipse(CX - 1.2, ny - 6.5, tip_r, tip_r * 0.8), fill=f.highlight, opacity=0.38, blur=1.6)
        self.add(ellipse(CX + 1, ny + 1.8, nw * 0.85, 3.2), fill=f.deep, opacity=0.3, blur=2)
        for s in (-1, 1):
            wing = (Path().M(CX + s * nw * 0.5, ny - 9.5)
                    .C(CX + s * (nw + 2.2), ny - 9, CX + s * (nw + 1.6), ny - 0.5, CX + s * nw * 0.55, ny - 0.2))
            self.add(wing, stroke=f.line, width=1.05, opacity=0.4 if s == -1 else 0.55, blur=0.35)
            self.add(ellipse(CX + s * nw * 0.42, ny - 1.4, lerp(1.8, 3.0, g.nose_width), 1.25, s * 18), fill=darken(f.deep, 0.35), opacity=0.8)
        self.add(Path().M(CX - nw * 0.3, ny - 0.6).Q(CX, ny + 1.5, CX + nw * 0.3, ny - 0.6), stroke=f.line, width=0.8, opacity=0.35, blur=0.3)

    def mouth(self) -> None:
        f, g = self.f, self.g
        my, mw, up, lo = f.mouth_y, f.mw, f.lip_up, f.lip_lo
        cdy = 0.6 - g.smile * 1.8
        L, R = (CX - mw, my + cdy), (CX + mw, my + cdy)
        upper = (Path().M(*L)
                 .C(CX - mw * 0.7, my - up * 0.55, CX - mw * 0.35, my - up * 1.05, CX - 3.4, my - up)
                 .Q(CX, my - up + 1.5, CX + 3.4, my - up)
                 .C(CX + mw * 0.35, my - up * 1.05, CX + mw * 0.7, my - up * 0.55, *R)
                 .C(CX + mw * 0.4, my + 1, CX - mw * 0.4, my + 1, *L).Z())
        lower = (Path().M(*L).C(CX - mw * 0.4, my + 1, CX + mw * 0.4, my + 1, *R)
                 .C(CX + mw * 0.75, my + lo * 0.9, CX + mw * 0.3, my + lo * 1.28, CX, my + lo * 1.28)
                 .C(CX - mw * 0.3, my + lo * 1.28, CX - mw * 0.75, my + lo * 0.9, *L).Z())
        # Philtrum and the shadow under the lower lip.
        self.add(ellipse(CX + 0.5, f.nose_y + (my - up - f.nose_y) / 2 + 1, 2.4, (my - up - f.nose_y) / 2), fill=f.shadow, opacity=0.18, blur=1.2)
        self.add(ellipse(CX + 1, my + lo * 1.3 + 3.5, mw * 0.45, 2.6), fill=f.shadow, opacity=0.4, blur=1.8)
        self.add(lower, fill=f.lip)
        self.add(upper, fill=darken(f.lip, 0.12))
        self.add(ellipse(CX - 2, my + lo * 0.65, mw * 0.32, lo * 0.3), fill=lighten(f.lip, 0.25), opacity=0.45, blur=1.2)
        self.add(lower, fill=f.shadow, opacity=0.15, blur=0.6)
        line = Path().M(L[0] - 0.5, L[1] - 0.2).C(CX - mw * 0.4, my + 1, CX + mw * 0.4, my + 1, R[0] + 0.5, R[1] - 0.2)
        self.add(line, stroke=darken(f.lip, 0.55), width=1.05, opacity=0.9)
        for s in (-1, 1):
            self.add(ellipse(CX + s * (mw + 0.8), my + cdy, 1.4, 1.2), fill=f.deep, opacity=0.3, blur=0.8)

    # ------------------------------------------------------------------ facial hair

    def _beard_region(self, ext: float, cheek_drop: float) -> Path:
        f = self.f
        y_sb = f.eye_y + 3
        e_sb = f.edge(y_sb)
        right_inner = [
            (CX + f.nw + 1.5, f.nose_y + 4),
            (CX + f.mw + 7, f.mouth_y - 9 + cheek_drop * 0.3),
            (CX + f.cheek_hw - 15, f.nose_y - 3 + cheek_drop),
            (CX + e_sb - 6, y_sb + 4 + cheek_drop * 0.4),
        ]
        right_outer = [
            (CX + e_sb + 0.6, y_sb),
            (CX + f.edge(f.eye_y + 22) + ext * 0.25, f.eye_y + 22),
            (CX + f.jaw_hw + ext * 0.45, f.jaw_y + ext * 0.3),
            (CX + f.chin_hw + ext * 0.6, f.chin_y - 4 + ext * 0.6),
        ]
        pts = [(CX, f.nose_y + 5)] + right_inner + right_outer + [(CX, f.chin_y + ext)]
        pts += [(2 * CX - x, y) for x, y in reversed(right_outer)] + [(2 * CX - x, y) for x, y in reversed(right_inner)]
        tens = [0.0, 0.3, 0.2, 0.0, 0.6, 0.9, 0, 0, 0, 0, 0, 0, 0, 0.9, 0.6, 0.0, 0.2, 0.3]
        return spline(pts, closed=True, tension=tens)

    def _mustache(self) -> Path:
        f = self.f
        r = [(CX + f.nw + 1.5, f.nose_y + 4), (CX + f.mw + 1.8, f.mouth_y + 2.2), (CX + f.mw - 1.5, f.mouth_y - 0.6), (CX + 5, f.mouth_y - f.lip_up + 0.2)]
        pts = [(CX, f.nose_y + 4.5)] + r + [(CX, f.mouth_y - f.lip_up + 1.2)] + [(2 * CX - x, y) for x, y in reversed(r)]
        return spline(pts, closed=True, tension=[0, 0.2, 0.8, 0.8, 0.2, 0.2, 0.2, 0.8, 0.8, 0.2])

    def facial_hair(self, layer: str) -> None:
        f, g = self.f, self.g
        style = g.facial_hair if g.sex == "male" else "none"
        if style == "none" or f.age < 17:
            return
        d = g.beard_density
        color = f.beard
        face = f.face
        if layer == "base":
            if style == "stubble":
                region = self._beard_region(0, 0)
                self.add(region, fill=color, opacity=lerp(0.14, 0.3, d), blur=1.3, clip=face)
            elif style in ("short_beard", "full_beard"):
                ext = 2.5 if style == "short_beard" else 7.5
                alpha = lerp(0.55, 0.88, d) if style == "short_beard" else lerp(0.78, 0.97, d)
                region = self._beard_region(ext, 0 if style == "full_beard" else 3)
                self.add(region, fill=color, opacity=alpha, blur=0.7)
                self.add(region, fill=lighten(color, 0.15), opacity=0.25, blur=2.5, clip=region)
                self._strands(region, color, alpha)
            elif style == "goatee":
                r = [(CX + f.nw + 1, f.nose_y + 4.5), (CX + f.mw + 2.5, f.mouth_y - 1), (CX + f.mw + 1.5, f.mouth_y + 6),
                     (CX + f.chin_hw * 0.95, f.chin_y - 6), (CX + f.chin_hw * 0.65, f.chin_y + 2)]
                pts = [(CX, f.nose_y + 5)] + r + [(CX, f.chin_y + 3)] + [(2 * CX - x, y) for x, y in reversed(r)]
                goatee = spline(pts, closed=True, tension=[0, 0.2, 0.6, 0.2, 0, 0, 0, 0, 0, 0.2, 0.6, 0.2])
                self.add(goatee, fill=color, opacity=lerp(0.6, 0.9, d), blur=0.7)
                self.add(self._beard_region(0, 0), fill=color, opacity=0.08, blur=1.3, clip=face)
            elif style == "chin_strap":
                # A band along the jaw: down the right side, around the chin, up the left, then back inside.
                right_out = [(CX + f.edge(y) + 0.5, y) for y in (f.eye_y + 3, f.eye_y + 20, f.jaw_y)]
                right_out.append((CX + f.chin_hw + 1.5, f.chin_y - 3))
                right_in = [(x - 5, y + (0 if i < 3 else -4.5)) for i, (x, y) in enumerate(right_out)]
                mirror = lambda pts: [(2 * CX - x, y) for x, y in pts]  # noqa: E731
                ring = (right_out + [(CX, f.chin_y + 1.5)] + mirror(right_out)[::-1]
                        + mirror(right_in) + [(CX, f.chin_y - 3.5)] + right_in[::-1])
                n = len(right_out)
                tens = [0.9] + [0.0] * (2 * n - 1) + [0.9, 0.9] + [0.0] * (2 * n - 1) + [0.9]
                strap = spline(ring, closed=True, tension=tens)
                self.add(strap, fill=color, opacity=lerp(0.6, 0.9, d), blur=0.6)
        elif layer == "mustache" and style in ("mustache", "goatee", "short_beard", "full_beard"):
            alpha = {"mustache": lerp(0.7, 0.95, d), "goatee": lerp(0.6, 0.9, d)}.get(style, lerp(0.6, 0.95, d))
            m = self._mustache()
            self.add(m, fill=color, opacity=alpha, blur=0.5)
            self._strands(m, color, alpha, n=10, length=2.5)

    def _strands(self, region: Path, color: str, alpha: float, n: int = 40, length: float = 3.5) -> None:
        """Short hair strokes so beards read as hair instead of a flat patch."""
        poly = region.flatten(step=1.0)[0][0]
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        strokes_dark, strokes_light = Path(), Path()
        for i in range(n):
            x = self.rng.uniform(min(xs), max(xs))
            y = self.rng.uniform(min(ys), max(ys))
            lean = (x - CX) * 0.04
            target = strokes_dark if i % 2 else strokes_light
            target.M(x, y).L(x + lean + self.rng.uniform(-0.6, 0.6), y + length)
        self.add(strokes_dark, stroke=darken(color, 0.3), width=0.55, opacity=alpha * 0.6, clip=region)
        self.add(strokes_light, stroke=lighten(color, 0.3), width=0.5, opacity=alpha * 0.4, clip=region)

    # ------------------------------------------------------------------ hair

    def _hair_params(self) -> dict:
        tex = self.g.hair_texture
        tight = tex == "coily"
        p = {
            "bald": dict(top=0.6, side=0.4, sb=1, alpha=0.1, soft=1.0),
            "horseshoe": dict(top=0, side=1.5, sb=2, alpha=0.95, sides_only=True),
            "buzz": dict(top=1.2, side=0.8, sb=2, alpha=0.62, soft=0.7, bumps=1.4 if tight else 0),
            "crew": dict(top=4.5, side=1.4, sb=3, alpha=0.97, side_alpha=0.6, strands=10, tufts=1.0),
            "side_part": dict(top=6.5, side=1.8, sb=3, alpha=0.98, side_alpha=0.7, part=True, strands=12, tufts=0.9),
            "crop": dict(top=5.5, side=1.4, sb=2, alpha=0.97, side_alpha=0.6, fringe=5, strands=10, tufts=1.1),
            "curly": dict(top=8, side=2.0, sb=2, alpha=0.97, side_alpha=0.7, bumps=2.5 if tight else 3.4, hairline_bumps=True),
            "afro": dict(top=17, side=10, sb=4, alpha=0.98, bumps=4.6, hairline_bumps=True),
            "waves": dict(top=2.3, side=1.0, sb=3, alpha=0.92, side_alpha=0.7, soft=0.4, waves=True),
            "fade": dict(top=5.5, side=0.6, sb=1, alpha=0.97, side_alpha=0.4, fade=True, bumps=2.0 if tex in ("curly", "coily") else 0, strands=6),
            "long": dict(top=6, side=3.2, sb=4, alpha=0.98, back="long", strands=12, tufts=0.9),
            "dreads": dict(top=6, side=3.5, sb=3, alpha=0.98, bumps=3.0, back="dreads"),
            "ponytail": dict(top=3.2, side=1.4, sb=-10, alpha=0.98, back="ponytail", strands=12, pulled=True),
            "bun": dict(top=3.2, side=1.4, sb=-10, alpha=0.98, bun=True, strands=12, pulled=True),
            "curly_long": dict(top=10, side=6, sb=-6, alpha=0.98, bumps=3.4, back="long_f", curtains=True, hairline_bumps=True),
            "bob": dict(top=5, side=3, sb=-6, alpha=0.98, back="bob", curtains=True, strands=10),
            "braids": dict(top=2.6, side=1.3, sb=-8, alpha=0.98, back="braids", rows=True),
        }
        if self.g.sex == "female" and self.style == "long":
            return dict(top=5, side=3, sb=-6, alpha=0.98, back="long_f", curtains=True, strands=12)
        params = dict(p.get(self.style, p["crew"]))
        if self.ctx.headwear == "cap":
            params["side"] = min(params["side"], 4.0)
        return params

    def _hair_shape(self, top: float, side: float, sb: float, fringe: float = 0.0) -> tuple[Path, Path, Path]:
        """Returns (cap shape, outer edge, hairline) for a hair mass of the given volume."""
        f = self.f
        rec = f.recession
        sb_y = f.eye_y + sb
        e_sb = f.edge(sb_y)
        e_mid = f.edge(f.eye_y - 14)
        hl = f.hairline_y
        thw = f.temple_hw
        outer_r = [
            (CX + e_sb + 0.8, sb_y),
            (CX + e_mid + side * 0.5 + 0.8, f.eye_y - 14),
            (CX + thw + side * 0.8 + 0.6, f.eye_y - 32),
            (CX + thw * 0.92 + side * 0.5 + top * 0.4, f.crown_y + 25 - top * 0.5),
            (CX + thw * 0.6 + top * 0.45, f.crown_y + 8 - top * 0.9),
        ]
        inner_r = [
            (CX + e_sb - 3.8, sb_y),
            (CX + e_mid - 3.8, min(f.eye_y - 12, sb_y - 1)),
            (CX + thw - 6.5 - rec * 6, hl + 6 - rec * 13),
        ]
        if fringe:
            mid = [(CX + dx, hl + fringe * (1 - (dx / 22) ** 2) + (2.2 if i % 2 else -0.6))
                   for i, dx in enumerate((18, 13, 8.5, 4, 0, -4, -8.5, -13, -18))]
        else:
            mid = [(CX + 13, hl + 1 - rec * 4), (CX, hl + 0.5), (CX - 13, hl + 1 - rec * 4)]
        outer = [(2 * CX - x, y) for x, y in outer_r] + [(CX, f.crown_y - top)] + list(reversed(outer_r))
        inner = inner_r + mid + [(2 * CX - x, y) for x, y in reversed(inner_r)]
        pts = outer + inner
        n_out = len(outer)
        tens = [0.9] + [0.0] * (n_out - 2) + [0.9] + [0.9, 0.0, 0.3] + [0.5 if fringe else 0.0] * len(mid) + [0.3, 0.0, 0.9]
        shape = spline(pts, closed=True, tension=tens)
        return shape, spline(outer, tension=0.0), spline(inner, tension=0.0)

    def _bumps(self, edge: Path, r: float, push: float, jitter: float = 0.25) -> Path:
        out = Path()
        pts = edge.flatten(step=1.0)[0][0]
        for (x, y), (nx, ny) in resample(pts, r * 1.25):
            rr = r * (1 + self.rng.uniform(-jitter, jitter))
            ellipse(x + nx * push * rr, y + ny * push * rr, rr, rr, path=out)
        return out

    def hair_back(self) -> None:
        if self.style in ("bald", "horseshoe"):
            return
        p = self._hair_params()
        back = p.get("back")
        if not back:
            return
        f = self.f
        hair = f.hair
        top_y = f.eye_y - 34
        if back in ("long", "long_f", "bob"):
            end = {"long": 236, "long_f": 266, "bob": f.jaw_y + 8}[back]
            spread = {"long": 9, "long_f": 12, "bob": 8}[back] + p["side"]
            r = [(CX + f.temple_hw + p["side"], top_y), (CX + f.cheek_hw + spread * 0.7, f.eye_y + 20),
                 (CX + f.cheek_hw + spread * 0.6, end - 10), (CX + f.cheek_hw - 2, end)]
            # Up the left side, over the crown, down the right side; the bottom closes the shape.
            edge = [(2 * CX - x, y) for x, y in reversed(r)] + [(CX, f.crown_y)] + r
            shape = spline(edge + [(CX + 10, end - 4), (CX - 10, end - 4)], closed=True, tension=0.0)
            self.add(shape, fill=darken(hair, 0.12))
            if p.get("bumps"):
                self.add(self._bumps(spline(edge, tension=0), p["bumps"], 0.2), fill=darken(hair, 0.12))
            self.add(ellipse(CX, (top_y + end) / 2, f.cheek_hw, (end - top_y) / 2), fill="#000000", opacity=0.25, blur=6, clip=shape)
        elif back == "ponytail":
            tail = Path().M(CX + 14, f.crown_y + 20).C(CX + 60, f.crown_y + 30, CX + 52, 200, CX + 42, 238).C(CX + 36, 236, CX + 34, 200, CX + 10, f.crown_y + 30).Z()
            self.add(tail, fill=darken(hair, 0.1))
        elif back in ("dreads", "braids"):
            n = 16 if back == "dreads" else 26
            width = 5.0 if back == "dreads" else 3.2
            end_base = 236 if back == "dreads" else 262
            ropes = Path()
            for i in range(n):
                t = i / (n - 1)
                ang = math.pi * (0.04 + 0.92 * t)
                sx = CX - math.cos(ang) * (f.temple_hw + p["side"]) * 1.02
                sy = top_y + 6 - math.sin(ang) * 18
                ex = CX - math.cos(ang) * (f.cheek_hw + 10 + self.rng.uniform(-3, 5))
                ey = end_base + self.rng.uniform(-14, 10)
                ropes.M(sx, sy).C(sx, sy + 40, ex, ey - 40, ex, ey)
            self.add(ropes, stroke=darken(hair, 0.15), width=width + 1.2)
            self.add(ropes, stroke=hair, width=width)
            self.add(ropes, stroke=lighten(hair, 0.2), width=width * 0.25, opacity=0.5)

    def hair_front(self) -> None:
        f, g = self.f, self.g
        p = self._hair_params()
        hair = f.hair
        face = f.face

        if p.get("sides_only"):
            for s in (-1, 1):
                sb_y = f.eye_y + p["sb"]
                pts = [(CX + s * (f.edge(sb_y) + 0.8), sb_y), (CX + s * (f.edge(f.eye_y - 14) + 1.5), f.eye_y - 14),
                       (CX + s * (f.temple_hw + 1.2), f.eye_y - 36), (CX + s * (f.temple_hw - 3), f.eye_y - 30),
                       (CX + s * (f.edge(f.eye_y - 14) - 6), f.eye_y - 16), (CX + s * (f.edge(sb_y) - 5), sb_y)]
                side = spline(pts, closed=True, tension=[0.9, 0, 0.6, 0.6, 0, 0.9])
                self.add(side, fill=hair, opacity=0.9, blur=0.6)
            self._scalp_shine()
            return

        shape, outer, hairline = self._hair_shape(p["top"], p["side"], p["sb"], p.get("fringe", 0))
        if self.style == "bald":
            self.add(shape, fill=hair, opacity=p["alpha"], blur=p["soft"], clip=face)
            self._scalp_shine()
            return

        # Soft shadow the hair casts on the forehead.
        self.add(hairline, stroke=f.deep, width=4, opacity=0.18, blur=2.2, clip=face)

        # Sides are cut shorter than the top on most styles (fully faded on "fade"), so scalp shows
        # through above the ears. The top is layered on in bands to fake a soft gradient.
        side_alpha = p.get("side_alpha", p["alpha"])
        mass = shape
        if p.get("fade"):
            mass, _, _ = self._hair_shape(0.8, 0.4, p["sb"])
        self.add(mass, fill=hair, opacity=side_alpha * 0.55, blur=1.6)
        self.add(mass, fill=hair, opacity=side_alpha, blur=p.get("soft", 0.3))
        if side_alpha < p["alpha"]:
            taper_y = f.eye_y - 26 - p["top"] * 0.3
            steps = 4
            band_alpha = 1 - ((1 - p["alpha"]) / (1 - side_alpha)) ** (1 / steps)
            for k in range(steps):
                y = taper_y + (k - steps / 2) * 3
                band = Path().M(-20, -20).L(220, -20).L(220, y).Q(CX, y - 8, -20, y).Z()
                self.add(shape, fill=hair, opacity=band_alpha, clip=band)
        if p.get("tufts"):
            self.add(self._tufts(outer, p["tufts"]), fill=hair, opacity=p["alpha"] * 0.8)
        if p.get("bumps"):
            self.add(self._bumps(outer, p["bumps"], 0.25), fill=hair, opacity=p["alpha"])
            if p.get("hairline_bumps"):
                self.add(self._bumps(hairline, p["bumps"] * 0.6, -0.1, 0.35), fill=hair, opacity=p["alpha"])
        clip = shape

        # Shading and texture inside the hair.
        light, dark = lighten(hair, 0.35 if luminance(hair) < 0.2 else 0.25), darken(hair, 0.35)
        self.add(ellipse(CX - 14, f.crown_y + 6, 24, 10), fill=light, opacity=0.25, blur=5, clip=clip)
        self.add(ellipse(CX + f.temple_hw + 2, f.eye_y - 30, 14, 34), fill=dark, opacity=0.4, blur=6, clip=clip)
        if p.get("strands"):
            self._hair_strands(p, clip, light, dark)
        if p.get("part"):
            ps = g.part_side
            part = Path().M(CX + ps * 12, f.hairline_y - 0.5).Q(CX + ps * 13, f.crown_y + 18, CX + ps * 9, f.crown_y - p["top"] + 3)
            self.add(part, stroke=dark, width=1.1, opacity=0.6, clip=clip)
        if p.get("waves"):
            rings = Path()
            for k in range(1, 6):
                rad = 8 + k * 6.5
                pts = []
                for i in range(41):
                    a = math.pi * (1.05 + 0.9 * i / 40)
                    rr = rad + 0.8 * math.sin(i * 1.7)
                    pts.append((CX + math.cos(a) * rr * 1.35, f.crown_y + 30 + math.sin(a) * rr))
                spline(pts, path=rings)
            self.add(rings, stroke=light, width=1.1, opacity=0.3, clip=clip)
        if p.get("rows"):
            rows = Path()
            for dx in (-24, -15, -6, 3, 12, 21):
                rows.M(CX + dx, f.hairline_y + 1).Q(CX + dx * 0.8, f.crown_y + 14, CX + dx * 0.4, f.crown_y - 1)
            self.add(rows, stroke=f.skin, width=0.8, opacity=0.35, clip=clip)
        if p.get("bun"):
            bun = ellipse(CX, f.crown_y - 9, 12, 10)
            self.add(bun, fill=hair)
            self.add(ellipse(CX - 3, f.crown_y - 13, 6, 4), fill=light, opacity=0.3, blur=2.5, clip=bun)
            self.add(Path().M(CX - 9, f.crown_y - 4).Q(CX, f.crown_y - 1, CX + 9, f.crown_y - 4), stroke=dark, width=1.2, opacity=0.5)
        if p.get("curtains"):
            self._curtains(p)

    def _hair_strands(self, p: dict, clip: Path, light: str, dark: str) -> None:
        """Curved strands flowing from the hairline back toward the crown."""
        f = self.f
        lights, darks = Path(), Path()
        sweep = -self.g.part_side if p.get("part") else 0
        n = p["strands"] * 2
        for i in range(n):
            t = self.rng.random()
            x0 = CX + (t - 0.5) * 2 * (f.temple_hw - 4)
            y0 = f.hairline_y + 2 + abs(t - 0.5) * 14 + self.rng.uniform(-1, 2)
            if p.get("pulled"):
                x1, y1 = CX + (x0 - CX) * 0.3, f.crown_y - p["top"] + 3
            else:
                reach = self.rng.uniform(0.2, 0.55)
                x1 = x0 + (CX - x0) * 0.25 + sweep * 10 * reach
                y1 = y0 - (y0 - (f.crown_y - p["top"] * 0.5)) * reach
            bend = (x0 - CX) * 0.12 + sweep * 5
            path = lights if i % 3 else darks
            path.M(x0, y0).Q((x0 + x1) / 2 + bend, (y0 + y1) / 2, x1, y1)
        self.add(lights, stroke=light, width=0.55, opacity=0.25, clip=clip)
        self.add(darks, stroke=dark, width=0.65, opacity=0.3, clip=clip)

    def _tufts(self, edge: Path, size: float) -> Path:
        """Small pointed tufts along the outer edge so short hair doesn't read as a solid helmet."""
        out = Path()
        pts = edge.flatten(step=1.0)[0][0]
        for (x, y), (nx, ny) in resample(pts, size * 1.6)[1:-1]:
            h = size * self.rng.uniform(0.6, 1.3)
            tx, ty = -ny, nx  # along the edge
            lean = self.rng.uniform(-0.6, 0.6)
            out.M(x - tx * size * 0.9 - nx * 0.8, y - ty * size * 0.9 - ny * 0.8)
            out.L(x + nx * h + tx * lean * h, y + ny * h + ty * lean * h)
            out.L(x + tx * size * 0.9 - nx * 0.8, y + ty * size * 0.9 - ny * 0.8).Z()
        return out

    def _curtains(self, p: dict) -> None:
        f = self.f
        end = {"bob": f.jaw_y + 8, "long_f": 266}.get(p.get("back"), 266)
        hair = f.hair
        for s in (-1, 1):
            pts = [
                (CX + s * (f.temple_hw - 10), f.hairline_y + 6),
                (CX + s * (f.edge(f.eye_y - 6) - 2.5), f.eye_y - 6),
                (CX + s * (f.edge(f.mouth_y) - 1), f.mouth_y),
                (CX + s * (f.cheek_hw + 6), end),
                (CX + s * (f.cheek_hw + 12 + p["side"]), end - 6),
                (CX + s * (f.cheek_hw + 10 + p["side"]), f.eye_y + 10),
                (CX + s * (f.temple_hw + p["side"] + 1), f.eye_y - 32),
            ]
            curtain = spline(pts, closed=True, tension=[0.5, 0, 0, 0.6, 0.6, 0, 0])
            self.add(curtain, fill=hair)
            self.add(ellipse(CX + s * (f.cheek_hw + 4), (f.eye_y + end) / 2, 6, (end - f.eye_y) / 2), fill=darken(hair, 0.35), opacity=0.4, blur=3, clip=curtain)
            if p.get("bumps"):
                self.add(self._bumps(spline(pts[3:], tension=0), p["bumps"], 0.2), fill=hair)

    def _scalp_shine(self) -> None:
        f = self.f
        self.add(ellipse(CX - 10, f.crown_y + 14, 16, 8), fill=f.highlight, opacity=0.35, blur=5, clip=f.face)

    # ------------------------------------------------------------------ cap

    def _cap_crown_curve(self, brim_y: float, open_path: bool = False) -> Path:
        """The cap's outline from the left brim corner over the top to the right brim corner."""
        f, thw = self.f, self.f.temple_hw
        pts = [(CX - thw - 4.5, brim_y - 3), (CX - thw - 3.2, f.eye_y - 40), (CX - thw * 0.72, f.crown_y + 1),
               (CX, f.crown_y - 8), (CX + thw * 0.72, f.crown_y + 1), (CX + thw + 3.2, f.eye_y - 40), (CX + thw + 4.5, brim_y - 3)]
        curve = spline(pts, tension=[0.9, 0, 0, 0, 0, 0, 0.9])
        if open_path:
            curve.cmds = [("L",) + curve.cmds[0][1:]] + curve.cmds[1:]
        return curve

    def cap(self) -> None:
        f, ctx = self.f, self.ctx
        color = ctx.cap
        brim_y = f.brow_y - 4.5
        thw = f.temple_hw
        # Shadow from the brim across the forehead and eyes.
        self.add(ellipse(CX, brim_y + 6, thw + 4, 10), fill=f.deep, opacity=0.35, blur=4.5, clip=f.face)
        crown = self._cap_crown_curve(brim_y)
        crown.Q(CX, brim_y + 0.5, CX - thw - 4.5, brim_y - 3).Z()
        self.add(crown, fill=color)
        self.add(ellipse(CX - 16, f.crown_y + 10, 22, 14), fill=lighten(color, 0.3), opacity=0.25, blur=7, clip=crown)
        self.add(ellipse(CX + thw + 4, f.eye_y - 40, 16, 34), fill="#000000", opacity=0.3, blur=8, clip=crown)
        seams = Path()
        for s in (-1, 1):
            seams.M(CX + s * 1.5, f.crown_y - 6).Q(CX + s * thw * 0.55, f.crown_y + 6, CX + s * thw * 0.62, brim_y - 7)
        self.add(seams, stroke=darken(color, 0.3), width=0.8, opacity=0.55)
        for s in (-1, 1):
            self.add(ellipse(CX + s * thw * 0.55, f.crown_y + 14, 1.1, 1.1), fill=darken(color, 0.45), opacity=0.8)
        self.add(ellipse(CX, f.crown_y - 7.5, 3.6, 1.9), fill=darken(color, 0.15))
        if ctx.logo:
            logo = ctx.logo[:3]
            size = {1: 25, 2: 19, 3: 14.5}[len(logo)]
            fill, outline = ctx.logo_color, ctx.logo_outline
            if not outline and abs(luminance(fill) - luminance(color)) < 0.18:
                outline = "#ffffff" if luminance(color) < 0.5 else "#111111"
            self.items.append(Text(CX, (f.crown_y - 8 + brim_y - 8) / 2 + 3, logo, size, fill,
                                   stroke=outline, stroke_width=1.1 if outline else 0))
        bw = thw + 9.5
        brim = (Path().M(CX - bw, brim_y - 6.5).Q(CX, brim_y - 12.5, CX + bw, brim_y - 6.5)
                .C(CX + bw + 1, brim_y - 3.5, CX + bw * 0.55, brim_y + 3.5, CX, brim_y + 3.5)
                .C(CX - bw * 0.55, brim_y + 3.5, CX - bw - 1, brim_y - 3.5, CX - bw, brim_y - 6.5).Z())
        brim_color = ctx.cap_brim or darken(color, 0.08)
        self.add(brim, fill=brim_color)
        self.add(Path().M(CX - bw + 1, brim_y - 3.4).C(CX - bw * 0.55, brim_y + 3, CX + bw * 0.55, brim_y + 3, CX + bw - 1, brim_y - 3.4),
                 stroke=darken(brim_color, 0.5), width=1.8, opacity=0.7, clip=brim)
        self.add(Path().M(CX - bw + 2, brim_y - 6.8).Q(CX, brim_y - 12.3, CX + bw - 2, brim_y - 6.8),
                 stroke=lighten(brim_color, 0.35), width=0.9, opacity=0.5)
        self.add(crown, stroke="#000000", width=0.8, opacity=0.3)
        self.add(brim, stroke="#000000", width=0.8, opacity=0.3)


def _photo_eye_dist() -> float:
    from .photo import EYE_DIST

    return EYE_DIST


def build_portrait(genome: Genome, ctx: RenderContext | None = None, photo=None) -> list:
    """Shapes for one portrait. With a PhotoHead, the player's real (cel-shaded) face is used instead of the
    drawn one; the genome then only shapes the neck and build."""
    ctx = ctx or RenderContext()
    if photo is not None:
        ctx = RenderContext.from_dict({**ctx.to_dict(), "skin": photo.skin})
        neutral = Genome.from_dict({**genome.to_dict(), "head_length": 0.5, "eye_spacing": 0.5, "brow_height": 0.5})
        return PortraitBuilder(neutral, ctx).build_photo(photo)
    return PortraitBuilder(genome, ctx).build()
