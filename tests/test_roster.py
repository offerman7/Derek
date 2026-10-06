import json

from simface.roster import parse_age, parse_height_cm, parse_weight_kg, read_nation_names, read_roster


def test_parsers():
    assert round(parse_height_cm("6-2")) == 188
    assert round(parse_height_cm("6'2\"")) == 188
    assert round(parse_height_cm("74")) == 188
    assert parse_height_cm("188") == 188
    assert parse_height_cm("") is None
    assert round(parse_weight_kg("220")) == 100
    assert parse_weight_kg("100", "kg") == 100
    assert parse_age("1995-07-01", 2026) == 31.0
    assert parse_age("07/01/1995", 2026) == 31.0
    assert parse_age(2000, 2026) == 26.0


def test_csv_autodetects_columns(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text(
        "PlayerID,First Name,Last Name,Team,Country,DOB,Height,Weight,Facial_Type,Hair_Color,Photo\n"
        "11,Ana,Silva,LAL,Brazil,1999-01-15,6-0,180,4,red,https://example.com/a.png\n"
        "12,Bo,Lee,BOS,Korea,,74,200,,,yes\n"
    )
    a, b = read_roster(f, season=2026)
    assert (a.id, a.first, a.last, a.team, a.nation) == ("11", "Ana", "Silva", "LAL", "Brazil")
    assert a.age == 27.5 and round(a.height_cm) == 183 and a.facial_type == "hispanic"
    assert a.overrides == {"hair_color": "red"} and a.photo_url == "https://example.com/a.png"
    assert b.age is None and b.photo_url is None  # "yes" is not a URL
    assert a.bmi and 20 < a.bmi < 30


def test_explicit_mapping_and_semicolon_csv(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("Num;Who;Club\n5;Sam Hill;KC\n")
    (rec,) = read_roster(f, mapping={"id": "Num", "name": "Who"})
    assert rec.id == "5" and rec.name == "Sam Hill" and rec.team == "KC"


def test_zengm_league_export(tmp_path):
    league = {
        "gameAttributes": [{"key": "season", "value": 2030}],
        "teams": [{"tid": 0, "region": "Boston", "name": "Celtics", "abbrev": "BOS"}],
        "players": [
            {"pid": 7, "firstName": "Max", "lastName": "Cole", "tid": 0, "hgt": 79, "weight": 215,
             "born": {"year": 2008, "loc": "Austin, TX"}, "imgURL": "https://example.com/max.png"},
        ],
    }
    f = tmp_path / "league.json"
    f.write_text(json.dumps(league))
    (rec,) = read_roster(f)
    assert rec.id == "7" and rec.name == "Max Cole"
    assert rec.team == "Boston Celtics" and rec.age == 22.0 and rec.nation == "Austin, TX"
    assert round(rec.height_cm) == 201 and rec.photo_url == "https://example.com/max.png"


def test_ootp_nation_ids(tmp_path):
    nations = tmp_path / "nations.csv"
    nations.write_text("nation_id,name,abbreviation\n206,USA,USA\n120,Japan,JPN\n")
    roster = tmp_path / "players.csv"
    roster.write_text("player_id,first_name,last_name,nation_id\n1,Ken,Ito,120\n")
    (rec,) = read_roster(roster, nation_names=read_nation_names(nations))
    assert rec.nation == "Japan"
