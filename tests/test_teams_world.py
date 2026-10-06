import random

from simface.teams import TeamDB, fallback_kit
from simface.world import World


def test_team_counts():
    db = TeamDB.load_default()
    assert len(db.by_league("mlb")) == 30
    assert len(db.by_league("nba")) == 30
    assert len(db.by_league("nfl")) == 32


def test_find_by_abbr_name_alias_and_league():
    db = TeamDB.load_default()
    assert db.find("NYY", "mlb").name == "Yankees"
    assert db.find("New York Yankees").abbr == "NYY"
    assert db.find("lakers").abbr == "LAL"
    assert db.find("SF", "mlb").name == "Giants"
    assert db.find("SF", "nfl").name == "49ers"
    assert db.find("CHW", "mlb").abbr == "CWS"
    assert db.find("Oakland Athletics", "mlb").abbr == "ATH"
    assert db.find("nobody") is None


def test_kits():
    db = TeamDB.load_default()
    yankees = db.find("NYY", "mlb").kit("home")
    assert yankees["pinstripes"] == "#0c2340" and yankees["logo"] == "NY" and yankees["cap"] == "#0c2340"
    assert db.find("NYY", "mlb").kit("away")["pinstripes"] is None
    assert db.find("DAL", "nfl").kit("home")["jersey"] == "#ffffff"
    assert db.find("LAL", "nba").kit("home")["jersey"] == "#fdb927"
    assert db.find("BOS", "nba").kit("home")["jersey"] == "#ffffff"
    assert db.find("BOS", "nba").kit("away")["jersey"] == "#007a33"


def test_custom_teams_file(tmp_path):
    f = tmp_path / "teams.csv"
    f.write_text("team_id,name,city,primary,secondary,logo\n7,Comets,Springfield,112233,ffcc00,SC\n")
    db = TeamDB.load_default()
    assert db.add_file(f) == 1
    t = db.find("7")
    assert t.name == "Comets" and t.kit()["logo"] == "SC" and t.primary == "#112233"


def test_fallback_kit_is_stable():
    assert fallback_kit("Team X", "nba") == fallback_kit("Team X", "nba")
    assert fallback_kit(None, "mlb")["logo"] == ""


def test_nation_resolution():
    w = World.load()
    assert w.resolve_nation("JPN") == "Japan"
    assert w.resolve_nation("Austin, TX") == "USA"
    assert w.resolve_nation("Toronto, ON") == "Canada"
    assert w.resolve_nation("Santo Domingo, Dominican Republic") == "Dominican Republic"
    assert w.resolve_nation("Curaçao") == "Curacao"
    assert w.resolve_nation("Atlantis") is None


def test_facial_mix_follows_nation_and_league():
    w = World.load()
    assert set(k for k, v in w.facial_mix("Japan").items() if v) == {"asian"}
    nba, mlb = w.facial_mix("USA", league="nba"), w.facial_mix("USA", league="mlb")
    assert nba["african"] > mlb["african"]
    assert w.facial_mix(ethnicity="South Asian")["east_indian"] == 1000


def test_user_world_file_in_ootp_list_format(tmp_path):
    f = tmp_path / "world.json"
    f.write_text('{"ethnicities": {"Martian": [0, 0, 0, 1000, 0]}, "nations": {"Mars": {"ethnicities": {"Martian": 1}}},'
                 ' "facial_types": {"pacific": {"base": "hispanic", "skin_tone": [0.5, 0.05]}}}')
    w = World.load(f)
    assert w.facial_mix("Mars") == {"african": 0, "asian": 0, "caucasian": 0, "east_indian": 1000, "hispanic": 0}
    assert w.priors["pacific"]["skin_tone"] == (0.5, 0.05)
    assert w.resolve_nation("Japan") == "Japan"  # defaults still there


def test_pick_types_respects_mix():
    w = World.load()
    rng = random.Random(1)
    for _ in range(50):
        primary, other, blend = w.pick_types(rng, {"asian": 1000})
        assert primary == "asian" and other is None and blend == 0
