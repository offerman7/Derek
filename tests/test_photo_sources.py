import io

import pytest
from PIL import Image

from simface.genome import Genome
from simface.portrait import RenderContext, build_portrait
from simface.roster import PlayerRecord
from simface.sources import ESPN_HEADSHOT, EspnDirectory, Fetcher, direct_url, name_key


def test_prepare_photo_cuts_out_head(drawn_face_png):
    pytest.importorskip("cv2")
    from simface.photo import EYE_DIST, prepare_photo

    head = prepare_photo(drawn_face_png)
    img = Image.open(io.BytesIO(head.png))
    assert img.mode == "RGBA" and img.size == (head.width, head.height)
    # Opaque at the face, transparent in the corners and below the neck.
    assert img.getpixel((int(head.eye_x), int(head.eye_y + 0.6 * EYE_DIST)))[3] > 200
    assert img.getpixel((2, 2))[3] == 0
    assert img.getpixel((int(head.eye_x), head.height - 2))[3] == 0
    assert head.eye_y < head.chin_y < head.height


def test_photo_portrait_with_cap(drawn_face_png):
    pytest.importorskip("cv2")
    from simface.backends import render_png, render_svg
    from simface.photo import prepare_photo

    head = prepare_photo(drawn_face_png)
    ctx = RenderContext(uniform="baseball", headwear="cap", logo="LA", cap="#005a9c")
    items = build_portrait(Genome(), ctx, photo=head)
    assert Image.open(io.BytesIO(render_png(items, (300, 450)))).size == (300, 450)
    assert "data:image/png;base64," in render_svg(items)


def test_no_face_raises():
    pytest.importorskip("cv2")
    from simface.photo import NoFaceFound, prepare_photo

    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (90, 90, 90)).save(buf, format="PNG")
    with pytest.raises(NoFaceFound):
        prepare_photo(buf.getvalue())


def test_direct_url_priority():
    assert direct_url(PlayerRecord(id="1", photo_url="x.png", espn_id="9"), "nba") == "x.png"
    assert direct_url(PlayerRecord(id="1", espn_id="9"), "nba") == ESPN_HEADSHOT.format(league="nba", espn_id="9")
    assert "people/660271/headshot" in direct_url(PlayerRecord(id="1", mlbam_id="660271"), "mlb")
    assert direct_url(PlayerRecord(id="1", nba_id="2544"), "nba").endswith("/2544.png")
    assert direct_url(PlayerRecord(id="1"), "nfl") is None


def test_name_key():
    assert name_key("José Ramírez Jr.") == name_key("jose ramirez") == "joseramirez"


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get_json(self, url, max_age=None):
        for key, page in self.pages.items():
            if url.endswith(key):
                return page
        return None


def test_espn_directory_flat_and_grouped_rosters():
    pages = {
        "/teams": {"sports": [{"leagues": [{"teams": [
            {"team": {"id": "1", "abbreviation": "AAA", "displayName": "Alpha Ants"}},
            {"team": {"id": "2", "abbreviation": "BBB", "displayName": "Beta Bees"}},
        ]}]}]},
        # Flat list (NBA style) and grouped by position (NFL/MLB style).
        "/teams/1/roster": {"athletes": [
            {"id": "11", "fullName": "Sam Smith", "headshot": {"href": "https://img/11.png"}},
            {"id": "12", "fullName": "Chris Jones", "headshot": {"href": "https://img/12.png"}},
        ]},
        "/teams/2/roster": {"athletes": [{"position": "offense", "items": [
            {"id": "21", "fullName": "Chris Jones"},
            {"id": "22", "fullName": "Luis Peña"},
        ]}]},
    }
    espn = EspnDirectory(FakeFetcher(pages), "nfl")
    assert espn.find("Sam Smith")["headshot"] == "https://img/11.png"
    assert espn.find("Luis Pena")["headshot"] == ESPN_HEADSHOT.format(league="nfl", espn_id="22")
    assert espn.find("Chris Jones") is None  # ambiguous without a team
    assert espn.find("Chris Jones", "BBB")["espn_id"] == "21"
    assert espn.find("Chris Jones", "Alpha Ants")["espn_id"] == "12"
    assert espn.find("Nobody Here") is None


def test_fetcher_reads_local_files_and_cached_misses(tmp_path):
    f = Fetcher(tmp_path / "cache")
    p = tmp_path / "a.bin"
    p.write_bytes(b"abc")
    assert f.get(str(p)) == b"abc"
    assert f.get(str(tmp_path / "missing.png")) is None
    url = "https://example.invalid/x.png"
    f._path(url).write_bytes(b"")  # a recorded 404
    assert f.get(url) is None
