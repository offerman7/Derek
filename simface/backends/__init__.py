from .svg import render_svg

__all__ = ["render_svg", "render_png"]


def render_png(*args, **kwargs):
    """PNG output needs Pillow; import lazily so SVG-only use has no dependencies."""
    from .raster import render_png as _render_png

    return _render_png(*args, **kwargs)
