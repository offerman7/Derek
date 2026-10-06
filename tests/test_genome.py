import random

from simface.genome import (
    FACIAL_HAIR_STYLES, HAIR_STYLES_FEMALE, HAIR_STYLES_MALE, OOTP_FACIAL_TYPES, SHAPE_TRAITS, Genome,
    generate_genome, restyle,
)


def test_same_seed_same_face():
    a = generate_genome(random.Random(42), "hispanic")
    b = generate_genome(random.Random(42), "hispanic")
    assert a == b
    assert a != generate_genome(random.Random(43), "hispanic")


def test_every_facial_type_produces_valid_traits():
    for ft in OOTP_FACIAL_TYPES:
        for seed in range(20):
            g = generate_genome(random.Random(seed), ft)
            assert g.facial_type == ft
            for t in SHAPE_TRAITS + ("skin_tone", "freckles", "beard_density", "baldness"):
                assert 0.0 <= getattr(g, t) <= 1.0, (ft, t)
            assert g.hair_style in HAIR_STYLES_MALE
            assert g.facial_hair in FACIAL_HAIR_STYLES


def test_facial_types_differ_in_skin_tone_on_average():
    def mean_tone(ft):
        return sum(generate_genome(random.Random(i), ft).skin_tone for i in range(60)) / 60

    assert mean_tone("african") > mean_tone("east_indian") > mean_tone("hispanic") > mean_tone("caucasian")


def test_blend_records_second_type():
    g = generate_genome(random.Random(1), "caucasian", blend_type="african", blend=0.4)
    assert g.blend_type == "african" and g.blend == 0.4


def test_female_faces_have_no_facial_hair():
    for seed in range(20):
        g = generate_genome(random.Random(seed), "african", sex="female")
        assert g.sex == "female" and g.facial_hair == "none" and g.hair_style in HAIR_STYLES_FEMALE


def test_restyle_keeps_anatomy():
    g = generate_genome(random.Random(5), "asian")
    before = {t: getattr(g, t) for t in SHAPE_TRAITS + ("skin_tone", "hair_color", "eye_color")}
    restyle(g, random.Random(99))
    assert before == {t: getattr(g, t) for t in before}


def test_round_trip_and_overrides():
    g = generate_genome(random.Random(3), "east_indian")
    assert Genome.from_dict({**g.to_dict(), "unknown_future_field": 1}) == g
    o = g.with_overrides({"skin_tone": "0.25", "hair_color": "red", "nonsense": "x", "eye_color": ""})
    assert o.skin_tone == 0.25 and o.hair_color == "red" and o.eye_color == g.eye_color
    assert g.hair_color != "red" or g.skin_tone != 0.25  # original untouched
