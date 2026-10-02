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
