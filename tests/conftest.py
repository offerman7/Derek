import random

import pytest

from simface.backends import render_png
from simface.genome import generate_genome
from simface.portrait import RenderContext, build_portrait


@pytest.fixture(scope="session")
def drawn_face_png() -> bytes:
    """A rendered illustrated face, used as a stand-in 'photo' so tests need no real people's pictures."""
    g = generate_genome(random.Random(2), "caucasian")
    g.hair_style, g.facial_hair = "crew", "none"
    ctx = RenderContext(uniform="crew", background="#d0d4da")
    return render_png(build_portrait(g, ctx), (400, 600), background="#d0d4da")
