import json

import pytest

from simface.batch import BatchOptions, run_batch
from simface.presets import get_preset
from simface.roster import read_roster

ROSTER = (
    "player_id,first_name,last_name,team,nation,age,height,weight\n"
    "1,Marcus,Delgado,NYY,Dominican Republic,27,6-1,205\n"
    "2,Kenji,Watanabe,LAD,Japan,24,5-11,180\n"
    "3,Tyler,Brandt,Comets,USA,31,6-3,225\n"
)


@pytest.fixture
def roster(tmp_path):
    f = tmp_path / "roster.csv"
    f.write_text(ROSTER)
    return read_roster(f)


def _opts(tmp_path, **kw):
    kw.setdefault("preset", get_preset("ootp"))
    return BatchOptions(out_dir=tmp_path / "out", cache_dir=tmp_path / "cache", workers=1, **kw)


def test_writes_ootp_files_and_bank(tmp_path, roster):
    report = run_batch(roster, _opts(tmp_path), log=lambda *a: None)
    out = tmp_path / "out"
    assert sorted(p.name for p in out.glob("player_*.png")) == ["player_1.png", "player_2.png", "player_3.png"]
    assert report.generated == 3 and report.new_genomes == 3 and not report.failed
    bank = json.loads((out / "simface_bank.json").read_text())
    assert set(bank["players"]) == {"1", "2", "3"}
    assert bank["players"]["2"]["genome"]["facial_type"] == "asian"
    assert (out / "index.html").exists()


def test_rerun_is_identical_and_keeps_genomes(tmp_path, roster):
    run_batch(roster, _opts(tmp_path), log=lambda *a: None)
    first = (tmp_path / "out" / "player_1.png").read_bytes()
    report = run_batch(roster, _opts(tmp_path), log=lambda *a: None)
    assert report.new_genomes == 0
    assert (tmp_path / "out" / "player_1.png").read_bytes() == first


def test_same_seed_same_faces_across_leagues(tmp_path, roster):
    run_batch(roster, _opts(tmp_path / "a"), log=lambda *a: None)
    run_batch(roster, _opts(tmp_path / "b"), log=lambda *a: None)
    a = json.loads((tmp_path / "a" / "out" / "simface_bank.json").read_text())["players"]
    b = json.loads((tmp_path / "b" / "out" / "simface_bank.json").read_text())["players"]
    assert a["3"]["genome"] == b["3"]["genome"]


def test_aging_changes_picture_not_genome(tmp_path, roster):
    run_batch(roster, _opts(tmp_path), log=lambda *a: None)
    young = (tmp_path / "out" / "player_3.png").read_bytes()
    genome = json.loads((tmp_path / "out" / "simface_bank.json").read_text())["players"]["3"]["genome"]
    for r in roster:
        r.age = 44
    run_batch(roster, _opts(tmp_path), log=lambda *a: None)
    assert (tmp_path / "out" / "player_3.png").read_bytes() != young
    assert json.loads((tmp_path / "out" / "simface_bank.json").read_text())["players"]["3"]["genome"] == genome


def test_never_overwrites_files_it_did_not_make(tmp_path, roster):
    out = tmp_path / "out"
    out.mkdir()
    (out / "player_2.png").write_bytes(b"my photo pack picture")
    report = run_batch(roster, _opts(tmp_path), log=lambda *a: None)
    assert report.protected == ["player_2.png"]
    assert (out / "player_2.png").read_bytes() == b"my photo pack picture"
    run_batch(roster, _opts(tmp_path, force=True), log=lambda *a: None)
    assert (out / "player_2.png").read_bytes() != b"my photo pack picture"


def test_only_missing(tmp_path, roster):
    run_batch(roster, _opts(tmp_path), log=lambda *a: None)
    report = run_batch(roster, _opts(tmp_path, only_missing=True), log=lambda *a: None)
    assert report.skipped_existing == 3 and report.generated == 0


def test_svg_output_and_other_presets(tmp_path, roster):
    preset = get_preset("basketball").with_overrides(fmt="svg", size=(200, 300))
    run_batch(roster, _opts(tmp_path, preset=preset), log=lambda *a: None)
    assert sorted(p.name for p in (tmp_path / "out").glob("*.svg")) == ["1.svg", "2.svg", "3.svg"]


def test_photo_from_local_path(tmp_path, drawn_face_png):
    pytest.importorskip("cv2")
    photo = tmp_path / "face.png"
    photo.write_bytes(drawn_face_png)
    f = tmp_path / "roster.csv"
    f.write_text(f"id,name,team,photo_url\n9,Real Guy,LAD,{photo}\n10,Fake Guy,LAD,\n")
    report = run_batch(read_roster(f), _opts(tmp_path, preset=get_preset("baseball")), log=lambda *a: None)
    assert report.photo == 1 and report.generated == 1
    bank = json.loads((tmp_path / "out" / "simface_bank.json").read_text())["players"]
    assert bank["9"]["source"] == "photo" and bank["10"]["source"] == "generated"
    # Processed heads are cached for the next run.
    assert list((tmp_path / "cache" / "heads").glob("*.png"))


def test_photo_without_a_face_falls_back(tmp_path):
    pytest.importorskip("cv2")
    from PIL import Image

    blank = tmp_path / "blank.png"
    Image.new("RGB", (300, 400), (40, 120, 200)).save(blank)
    f = tmp_path / "roster.csv"
    f.write_text(f"id,name,photo_url\n1,Nobody,{blank}\n")
    report = run_batch(read_roster(f), _opts(tmp_path), log=lambda *a: None)
    assert report.generated == 1 and report.no_face == 1
