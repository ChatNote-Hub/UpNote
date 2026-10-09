import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from upnote import parsing


def test_parse_leaves_plain_values_untouched():
    assert parsing.parse("hello") == "hello"
    assert parsing.parse(42) == 42
    assert parsing.parse(None) is None


def test_parse_renames_label_and_id_keys():
    result = parsing.parse({"L": "Maths", "N": "123", "other": "x"})
    assert result == {"label": "Maths", "id": "123", "other": "x"}


def test_parse_unwraps_typed_number():
    result = parsing.parse({"_T": 10, "V": "15,5"})
    assert result == 15.5


def test_parse_number_set():
    assert parsing.parse_number_set("[1..3,5]") == [1, 2, 3, 5]
    assert parsing.parse_number_set("[]") == []
    assert parsing.parse_number_set("not a set") == []


def test_parse_full_date():
    result = parsing.parse_date("14/03/2026 08:30:00")
    assert result == datetime(2026, 3, 14, 8, 30, 0)


def test_parse_recurses_into_nested_structures():
    result = parsing.parse({"data": [{"L": "A", "N": "1"}, {"L": "B", "N": "2"}]})
    assert result == {"data": [{"label": "A", "id": "1"}, {"label": "B", "id": "2"}]}


def test_parse_unknown_type_code_is_lenient():
    # Should not raise, unlike Blocksnote's Parser.handleType which throws.
    assert parsing.parse({"_T": 999, "V": "whatever"}) == "whatever"


def test_js_weekday_uses_sunday_zero_indexing():
    # 2026-10-04 is a Sunday, 2026-10-05 a Monday, 2026-10-10 a Saturday.
    assert parsing._js_weekday(datetime(2026, 10, 4)) == 0
    assert parsing._js_weekday(datetime(2026, 10, 5)) == 1
    assert parsing._js_weekday(datetime(2026, 10, 10)) == 6
    assert parsing._FRENCH_DAYS["dimanche"] == 0
    assert parsing._FRENCH_DAYS["lundi"] == 1


def test_short_date_resolves_to_most_recent_matching_weekday():
    now = datetime.now()
    names = {v: k for k, v in parsing._FRENCH_DAYS.items()}
    today_name = names[parsing._js_weekday(now)]

    result = parsing.parse_date(f"{today_name} 08h30")

    assert result.date() == now.date()
    assert (result.hour, result.minute) == (8, 30)


def test_encode_date_has_no_zero_padding():
    assert parsing.encode_date(datetime(2026, 3, 5, 8, 5, 0)) == "5/3/2026 8:5:0"
    assert parsing.encode_date(datetime(2026, 12, 25, 23, 59, 58)) == "25/12/2026 23:59:58"


def test_encode_helpers_emit_dual_case_keys():
    assert parsing.encode_value("numeroSemaine", 3) == {"numeroSemaine": 3, "NumeroSemaine": 3}
    assert parsing.encode_type("dateDebut", 7, "1/1/2026 0:0:0") == {
        "dateDebut": {"_T": 7, "V": "1/1/2026 0:0:0"},
        "DateDebut": {"_T": 7, "V": "1/1/2026 0:0:0"},
    }
    assert parsing.encode_kind("ressource", 4, "x") == {
        "ressource": {"G": 4, "N": "x"},
        "Ressource": {"G": 4, "N": "x"},
    }


def test_encoded_date_round_trips_through_parse():
    original = datetime(2026, 3, 5, 8, 5, 7)
    assert parsing.parse(parsing.encode_type("d", 7, parsing.encode_date(original))["d"]) == original


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)
