import io
import random
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from simface.backends import render_png, render_svg
from simface.genome import FACIAL_HAIR_STYLES, HAIR_STYLES_FEMALE, HAIR_STYLES_MALE, generate_genome
from simface.portrait import HEADWEAR, UNIFORMS, RenderContext, build_portrait


def _png(items, size=(90, 135)):
    img = Image.open(io.BytesIO(render_png(items, size)))
    assert img.size == size and img.mode == "RGBA"
    return img


@pytest.mark.parametrize("style", HAIR_STYLES_MALE)
def test_male_hair_styles_render(style):
    g = generate_genome(random.Random(1), "african")
    g.hair_style = style
    _png(build_portrait(g, RenderContext(age=30)))


@pytest.mark.parametrize("style", HAIR_STYLES_FEMALE)
def test_female_hair_styles_render(style):
    g = generate_genome(random.Random(1), "caucasian", sex="female")
    g.hair_style = style
    _png(build_portrait(g, RenderContext()))


@pytest.mark.parametrize("beard", FACIAL_HAIR_STYLES)
def test_facial_hair_renders(beard):
    g = generate_genome(random.Random(2), "hispanic")
    g.facial_hair = beard
    _png(build_portrait(g, RenderContext(age=33)))


@pytest.mark.parametrize("uniform", UNIFORMS)
@pytest.mark.parametrize("headwear", HEADWEAR)
def test_uniforms_and_headwear(uniform, headwear):
    g = generate_genome(random.Random(3), "asian")
    ctx = RenderContext(uniform=uniform, headwear=headwear, logo="NY", pinstripes="#0c2340", trim2="#ffffff")
    _png(build_portrait(g, ctx))


def test_age_and_weight_extremes():
    g = generate_genome(random.Random(4), "caucasian")
    for age, bmi in ((18, 19), (45, 40), (60, 30)):
        _png(build_portrait(g, RenderContext(age=age, bmi=bmi)))


def test_svg_is_valid_xml_and_sized():
    g = generate_genome(random.Random(5), "east_indian")
    svg = render_svg(build_portrait(g, RenderContext(headwear="cap", uniform="baseball", logo="SD")), (300, 450))
    root = ET.fromstring(svg)
    assert root.get("width") == "300" and root.get("height") == "450"
    assert "SD" in svg


def test_transparent_background_by_default_and_solid_on_request():
    g = generate_genome(random.Random(6), "african")
    items = build_portrait(g, RenderContext())
    assert _png(items).getpixel((0, 0))[3] == 0
    solid = Image.open(io.BytesIO(render_png(items, (90, 135), background="#ff0000")))
    assert solid.getpixel((0, 0)) == (255, 0, 0, 255)


def test_non_portrait_aspect_ratio():
    g = generate_genome(random.Random(7), "hispanic")
    _png(build_portrait(g, RenderContext()), size=(128, 128))
