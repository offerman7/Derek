"""Writes a portrait as a standalone SVG document. Standard library only."""

from __future__ import annotations

import base64
from xml.sax.saxutils import escape

from ..geometry import DESIGN_H, DESIGN_W, Picture, Shape, Text, _num


def render_svg(items, size: tuple[int, int] = (200, 300), background: str | None = None) -> str:
    w, h = size
    defs: list[str] = []
    body: list[str] = []
    blur_ids: dict[float, str] = {}
    clip_ids: dict[int, str] = {}

    def blur_ref(b: float) -> str:
        key = round(b, 2)
        if key not in blur_ids:
            blur_ids[key] = f"b{len(blur_ids)}"
            defs.append(
                f'<filter id="{blur_ids[key]}" filterUnits="userSpaceOnUse" x="-50" y="-50" width="300" height="400">'
                f'<feGaussianBlur stdDeviation="{_num(key)}"/></filter>'
            )
        return blur_ids[key]

    def clip_ref(path) -> str:
        key = id(path)
        if key not in clip_ids:
            clip_ids[key] = f"c{len(clip_ids)}"
            defs.append(f'<clipPath id="{clip_ids[key]}"><path d="{path.svg()}"/></clipPath>')
        return clip_ids[key]

    if background:
        body.append(f'<rect x="-50" y="-50" width="300" height="400" fill="{background}"/>')

    for item in items:
        if isinstance(item, Picture):
            data = base64.b64encode(item.png).decode("ascii")
            clip = f' clip-path="url(#{clip_ref(item.clip)})"' if item.clip is not None else ""
            body.append(
                f'<image x="{_num(item.x)}" y="{_num(item.y)}" width="{_num(item.w)}" height="{_num(item.h)}" '
                f'preserveAspectRatio="none" href="data:image/png;base64,{data}"{clip}/>'
            )
            continue
        if isinstance(item, Text):
            stroke = ""
            if item.stroke and item.stroke_width:
                stroke = (
                    f' stroke="{item.stroke}" stroke-width="{_num(item.stroke_width)}" '
                    f'paint-order="stroke" stroke-linejoin="round"'
                )
            body.append(
                f'<text x="{_num(item.x)}" y="{_num(item.y)}" font-size="{_num(item.size)}" '
                f'font-family="Arial Black, Arial, Helvetica, sans-serif" font-weight="900" '
                f'text-anchor="middle" dominant-baseline="central" fill="{item.fill}"'
                f'{stroke}{_opacity(item.opacity)}>{escape(item.text)}</text>'
            )
            continue
        assert isinstance(item, Shape)
        group_attrs = _opacity(item.opacity)
        if item.blur > 0:
            group_attrs += f' filter="url(#{blur_ref(item.blur)})"'
        if item.clip is not None:
            # Clip on an outer group so the blur happens before clipping, as in the PNG backend.
            body.append(f'<g clip-path="url(#{clip_ref(item.clip)})">')
        paint = []
        if item.fill:
            paint.append(f'fill="{item.fill}"')
        else:
            paint.append('fill="none"')
        if item.stroke:
            paint.append(
                f'stroke="{item.stroke}" stroke-width="{_num(item.width)}" '
                f'stroke-linecap="round" stroke-linejoin="round"'
            )
        paint_attr = " ".join(paint)
        subpaths = item.path.subpath_strings()
        if len(subpaths) == 1:
            body.append(f'<path d="{subpaths[0]}" {paint_attr}{group_attrs}/>')
        else:
            # Separate elements in one group: overlapping subpaths union regardless of winding,
            # and group opacity applies once to the union.
            body.append(f"<g{group_attrs}>")
            body.extend(f'<path d="{d}" {paint_attr}/>' for d in subpaths)
            body.append("</g>")
        if item.clip is not None:
            body.append("</g>")

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {_num(DESIGN_W)} {_num(DESIGN_H)}" preserveAspectRatio="xMidYMid slice">'
        f'<defs>{"".join(defs)}</defs>{"".join(body)}</svg>'
    )


def _opacity(o: float) -> str:
    return "" if o >= 1 else f' opacity="{_num(max(0.0, o))}"'
