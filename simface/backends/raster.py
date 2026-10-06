"""Rasterizes a portrait with Pillow. Draws at a multiple of the output size, then downsamples to anti-alias."""

from __future__ import annotations

import functools
import io

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from ..colors import to_rgb
from ..geometry import DESIGN_H, DESIGN_W, Picture, Shape, Text


def render_png(
    items,
    size: tuple[int, int] = (200, 300),
    background: str | None = None,
    supersample: int | None = None,
) -> bytes:
    img = render_image(items, size, background, supersample)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_image(items, size=(200, 300), background=None, supersample=None) -> Image.Image:
    w, h = size
    if supersample is None:
        # Aim for a ~600px working canvas so small outputs still get smooth curves.
        supersample = max(2, min(6, round(600 / max(w, 1))))
    W, H = w * supersample, h * supersample
    # Same fit as the SVG's preserveAspectRatio="xMidYMid slice".
    scale = max(W / DESIGN_W, H / DESIGN_H)
    ox = W / 2 - DESIGN_W / 2 * scale
    oy = H / 2 - DESIGN_H / 2 * scale

    def tr(pts):
        return [(ox + x * scale, oy + y * scale) for x, y in pts]

    canvas = Image.new("RGBA", (W, H), to_rgb(background) + (255,) if background else (0, 0, 0, 0))
    for item in items:
        if isinstance(item, Picture):
            _draw_picture(canvas, item, tr, scale)
        elif isinstance(item, Text):
            _draw_text(canvas, item, tr, scale)
        else:
            _draw_shape(canvas, item, tr, scale)

    # Downsample in premultiplied alpha so transparent edges don't pick up dark fringes.
    return canvas.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")


def _draw_shape(canvas: Image.Image, shape: Shape, tr, scale: float) -> None:
    # ~3 working pixels per segment is smooth once downsampled.
    polys = [(tr(pts), closed) for pts, closed in shape.path.flatten(step=3.0 / scale)]
    if not polys:
        return
    stroke_px = max(1.0, shape.width * scale) if shape.stroke else 0.0
    margin = shape.blur * scale * 3 + stroke_px + 2
    xs = [x for pts, _ in polys for x, _ in pts]
    ys = [y for pts, _ in polys for _, y in pts]
    x0 = max(0, int(min(xs) - margin))
    y0 = max(0, int(min(ys) - margin))
    x1 = min(canvas.width, int(max(xs) + margin) + 1)
    y1 = min(canvas.height, int(max(ys) + margin) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    bw, bh = x1 - x0, y1 - y0

    def local(pts):
        return [(x - x0, y - y0) for x, y in pts]

    clip_mask = None
    if shape.clip is not None:
        clip_mask = Image.new("L", (bw, bh), 0)
        cd = ImageDraw.Draw(clip_mask)
        for pts, _ in shape.clip.flatten(step=3.0 / scale):
            if len(pts) >= 3:
                cd.polygon(local(tr(pts)), fill=255)

    for color, mode in ((shape.fill, "fill"), (shape.stroke, "stroke")):
        if not color:
            continue
        mask = Image.new("L", (bw, bh), 0)
        d = ImageDraw.Draw(mask)
        for pts, closed in polys:
            lp = local(pts)
            if mode == "fill":
                if len(lp) >= 3:
                    d.polygon(lp, fill=255)
            else:
                if closed:
                    lp = lp + [lp[0]]
                wpx = int(round(stroke_px))
                d.line(lp, fill=255, width=wpx, joint="curve")
                r = stroke_px / 2
                for px, py in (lp[0], lp[-1]):
                    d.ellipse((px - r, py - r, px + r, py + r), fill=255)
        if shape.blur > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(shape.blur * scale))
        if clip_mask is not None:
            mask = ImageChops.multiply(mask, clip_mask)
        if shape.opacity < 1:
            mask = mask.point(_opacity_lut(round(shape.opacity, 3)))
        layer = Image.new("RGBA", (bw, bh), to_rgb(color) + (255,))
        layer.putalpha(mask)
        canvas.alpha_composite(layer, (x0, y0))


def _draw_picture(canvas: Image.Image, pic: Picture, tr, scale: float) -> None:
    (x, y), = tr([(pic.x, pic.y)])
    w, h = max(1, int(round(pic.w * scale))), max(1, int(round(pic.h * scale)))
    img = Image.open(io.BytesIO(pic.png)).convert("RGBA").convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(img, (int(round(x)), int(round(y))))
    if pic.clip is not None:
        mask = Image.new("L", canvas.size, 0)
        d = ImageDraw.Draw(mask)
        for pts, _ in pic.clip.flatten(step=3.0 / scale):
            if len(pts) >= 3:
                d.polygon(tr(pts), fill=255)
        layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    canvas.alpha_composite(layer)


def _draw_text(canvas: Image.Image, t: Text, tr, scale: float) -> None:
    (x, y), = tr([(t.x, t.y)])
    font = _font(max(6, int(round(t.size * scale))))
    sw = int(round(t.stroke_width * scale)) if t.stroke else 0
    for color, width in ((t.stroke, sw), (t.fill, 0)):
        if not color or (color is t.stroke and not sw):
            continue
        mask = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(mask).text((x, y), t.text, font=font, fill=255, anchor="mm", stroke_width=width)
        if t.opacity < 1:
            mask = mask.point(_opacity_lut(round(t.opacity, 3)))
        layer = Image.new("RGBA", canvas.size, to_rgb(color) + (255,))
        layer.putalpha(mask)
        canvas.alpha_composite(layer)


@functools.lru_cache(maxsize=64)
def _opacity_lut(opacity: float) -> list[int]:
    return [int(v * opacity + 0.5) for v in range(256)]


_FONT_CANDIDATES = (
    "Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


@functools.lru_cache(maxsize=32)
def _font(px: int):
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)
