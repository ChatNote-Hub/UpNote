"""
Generic parser/encoder for PRONOTE's typed value wrappers, mirroring
`structures/parsing/{Parser,DateParser,NumberSet}.ts` from Blocksnote.

PRONOTE wraps many response fields as `{"_T": <type_code>, "V": <value>}`
(numbers, dates, "number sets" like grade scales, nested typed objects...),
and uses `"L"`/`"N"` as short keys for "label"/"id" on a lot of objects.
`parse` undoes both. The `encode_*` helpers do the reverse for outgoing
request payloads.

Unknown type codes are left as-is rather than raising, since being lenient
is safer than crashing on a field this project doesn't need yet.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

# JS-style day-of-week indexing (Sunday = 0), exactly like DateParser.ts.
_FRENCH_DAYS = {
    "lundi": 1,
    "mardi": 2,
    "mercredi": 3,
    "jeudi": 4,
    "vendredi": 5,
    "samedi": 6,
    "dimanche": 0,
}

_SHORT_DATE_RE = re.compile(r"^\w+\s\d{2}h\d{2}")
_SHORT_PRECISE_DATE_RE = re.compile(r"^\w+\s\d{2}/\d{2}")


def _js_weekday(dt: datetime) -> int:
    """Python weekday() is Monday=0..Sunday=6; JS getDay() is Sunday=0..Saturday=6."""
    return (dt.weekday() + 1) % 7


# --- Decoding ----------------------------------------------------------------

def parse_number_set(value: str) -> list[int]:
    """"[1..3,5]" -> [1, 2, 3, 5] (used for grade scales, etc.)."""
    if not value or not value.startswith("[") or not value.endswith("]"):
        return []

    inside = value[1:-1].strip()
    if not inside:
        return []

    result: list[int] = []
    for part in inside.split(","):
        bounds = [b.strip() for b in part.split("..")]
        try:
            start = int(bounds[0])
        except ValueError:
            continue
        if len(bounds) == 1:
            result.append(start)
            continue
        try:
            end = int(bounds[1])
        except ValueError:
            result.append(start)
            continue
        result.extend(range(start, end + 1))

    return result


def parse_date(value: str) -> datetime:
    """Port of DateParser.parse - full date, "day HHhMM", or "day DD/MM"."""
    if _SHORT_DATE_RE.match(value):
        return _parse_short_date(value)
    if _SHORT_PRECISE_DATE_RE.match(value):
        return _parse_short_precise_date(value)
    return _parse_full_date(value)


def _parse_short_precise_date(value: str) -> datetime:
    """
    "lundi 14/09" -> a date with no year. Ported as-is from DateParser.ts:
    months January-September (1-9) resolve to NEXT calendar year, October-
    December to the current one (school-year logic).
    """
    now = datetime.now()
    _, rest = value.split(" ", 1)
    day_str, month_str = rest.split("/")[:2]
    day, month = int(day_str), int(month_str)
    year = now.year + 1 if month <= 9 else now.year
    return datetime(year, month, day)


def _parse_short_date(value: str) -> datetime:
    """"lundi 14h30" -> the most recent such weekday (today included), at that time."""
    now = datetime.now()
    day_name, hour_part = value.split(" ", 1)
    hour_str, minute_str = hour_part.split("h")
    target_weekday = _FRENCH_DAYS.get(day_name, 0)
    delta = (_js_weekday(now) - target_weekday + 7) % 7
    target = now.replace(hour=int(hour_str), minute=int(minute_str), second=0, microsecond=0)
    return target - timedelta(days=delta)


def _parse_full_date(value: str) -> datetime:
    day_part, _, hour_part = value.partition(" ")
    day, month, year = (int(x) for x in day_part.split("/"))
    if hour_part:
        pieces = hour_part.split(":")
        hour, minute = int(pieces[0]), int(pieces[1])
        second = int(pieces[2]) if len(pieces) > 2 else 0
    else:
        hour = minute = second = 0
    return datetime(year, month, day, hour, minute, second)


def _handle_type(type_code: int, value: Any) -> Any:
    if type_code == 10:  # locale-formatted number ("12,5" -> 12.5)
        if isinstance(value, str):
            try:
                return float(value.replace(",", "."))
            except ValueError:
                return value
        return value
    if type_code in (8, 11, 26):  # number set (grade scale, etc.)
        return parse_number_set(value) if isinstance(value, str) else value
    if type_code == 7:  # date
        try:
            return parse_date(value)
        except Exception:
            return value
    if type_code in (21, 23, 24, 25, 27):  # nested typed object - just recurse
        return parse(value)
    # Unknown type code: be lenient, return the raw value rather than raising.
    return value


def parse(obj: Any) -> Any:
    if obj is None or not isinstance(obj, (dict, list)):
        return obj

    if isinstance(obj, list):
        return [parse(item) for item in obj]

    o = dict(obj)

    if "L" in o:
        o["label"] = o.pop("L")
    if "N" in o:
        o["id"] = o.pop("N")

    if "_T" in o and "V" in o:
        return _handle_type(o["_T"], o["V"])

    return {key: parse(value) for key, value in o.items()}


# --- Encoding (outgoing request payloads) ----------------------------------

def encode_date(value: datetime) -> str:
    """
    Port of DateParser.encode: "D/M/YYYY H:M:S" with NO zero-padding
    (e.g. 2026-03-05 08:05:00 -> "5/3/2026 8:5:0"), exactly the wire format.
    """
    return f"{value.day}/{value.month}/{value.year} {value.hour}:{value.minute}:{value.second}"


def _dual_case_key(key: str, value: Any) -> dict[str, Any]:
    """PRONOTE expects some fields under both `key` and `Key` - send both."""
    capitalized = key[:1].upper() + key[1:]
    return {key: value, capitalized: value}


def encode_value(key: str, value: Any) -> dict[str, Any]:
    return _dual_case_key(key, value)


def encode_type(key: str, type_code: int, value: Any) -> dict[str, Any]:
    return _dual_case_key(key, {"_T": type_code, "V": value})


def encode_kind(key: str, kind: int, id_: str) -> dict[str, Any]:
    return _dual_case_key(key, {"G": kind, "N": id_})
