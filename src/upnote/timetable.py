"""
Timetable (`PageEmploiDuTemps`), mirroring `routes/PageEmploiDuTemps/*`
from Blocksnote.

    from upnote import login, get_user, get_timetable

    session = login(url, username, password)
    user = get_user(session)
    lessons = get_timetable(session, user.resource, week_number=12)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional, Union

from . import parsing
from .constants import NOTSpace
from .session import PronoteError, PronoteSession
from .user import Resource

FUNCTION_NAME = "PageEmploiDuTemps"

# Kind codes of the entries in a course's "ListeContenus".
_KIND_GROUPS = 2
_KIND_TEACHERS = 3
_KIND_SUBJECT = 16
_KIND_ROOMS = 17
_KIND_STAFF = 34

# Tab ("onglet") number sent in the request signature. Students, parents
# and teachers share the default; administrators and school life differ.
_DEFAULT_TAB = 16
_TABS = {NOTSpace.ADMINISTRATOR: 60, NOTSpace.SCHOOL_LIFE: 171}

# Spaces whose requests must also name the member whose timetable is read.
_MEMBER_SPACES = (NOTSpace.PARENT, NOTSpace.ACCOMPANYING, NOTSpace.ENTERPRISE)


@dataclass
class TimeSlot:
    """Fields shared by lessons and detentions."""

    start: datetime
    end: datetime
    subject: Optional[str]
    teachers: list[str]
    staff: list[str]
    rooms: list[str]
    groups: list[str]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


@dataclass
class Lesson(TimeSlot):
    canceled: bool = False
    status: Optional[str] = None
    background_color: Optional[str] = None
    has_evaluation: bool = False
    videoconferences: list[dict[str, Optional[str]]] = field(default_factory=list)


@dataclass
class Detention(TimeSlot):
    state: Optional[str] = None


@dataclass
class TimetableDay:
    date: date
    slots: list[TimeSlot]


def build_payload(
    resource: Resource,
    *,
    week_number: Union[int, str, None] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    with_absences: bool = False,
    with_class_council: bool = True,
    with_field_trips: bool = True,
    with_availabilities: bool = True,
    with_grid_preferences: bool = True,
    with_free_resources_footer: bool = False,
    with_student_detentions: bool = True,
    is_permanence_timetable: bool = False,
) -> dict[str, Any]:
    """Build the `data` part of a PageEmploiDuTemps request."""
    payload: dict[str, Any] = {
        "avecAbsencesEleve": with_absences,
        "avecAbsencesRessource": True,
        "avecConseilDeClasse": with_class_council,
        "avecCoursSortiePeda": with_field_trips,
        "avecDisponibilites": with_availabilities,
        "avecInfosPrefsGrille": with_grid_preferences,
        "avecRessourcesLibrePiedHoraire": with_free_resources_footer,
        "avecRetenuesEleve": with_student_detentions,
        "estEDTPermanence": is_permanence_timetable,
    }

    if start is not None and end is not None:
        payload.update(parsing.encode_type("dateDebut", 7, parsing.encode_date(start)))
        payload.update(parsing.encode_type("dateFin", 7, parsing.encode_date(end)))
    elif week_number is not None:
        payload.update(parsing.encode_value("numeroSemaine", week_number))

    payload.update(parsing.encode_kind("ressource", resource.kind, resource.id))
    return payload


def build_signature(workspace_type: int, resource: Resource) -> dict[str, Any]:
    """Build the request signature: the tab number, plus the member for non-student spaces."""
    signature: dict[str, Any] = {"onglet": _TABS.get(workspace_type, _DEFAULT_TAB)}  # type: ignore[call-overload]

    if workspace_type in _MEMBER_SPACES:
        signature["membre"] = {"G": resource.kind, "N": resource.id}

    return signature


def _content(raw_course: dict[str, Any], kind: int) -> list[str]:
    return [
        item["label"]
        for item in raw_course.get("ListeContenus", [])
        if item.get("G") == kind and "label" in item
    ]


def _parse_slot(raw_course: dict[str, Any], seats_per_hour: float) -> TimeSlot:
    start = raw_course["DateDuCours"]
    if not isinstance(start, datetime):
        raise PronoteError(f"Unexpected course date format: {start!r}")

    # "duree" is a number of time slots; seats_per_hour converts it to hours.
    end = start + timedelta(hours=raw_course["duree"] / seats_per_hour)

    subjects = _content(raw_course, _KIND_SUBJECT)
    common: dict[str, Any] = dict(
        start=start,
        end=end,
        subject=subjects[0] if subjects else None,
        teachers=_content(raw_course, _KIND_TEACHERS),
        staff=_content(raw_course, _KIND_STAFF),
        rooms=_content(raw_course, _KIND_ROOMS),
        groups=_content(raw_course, _KIND_GROUPS),
        raw=raw_course,
    )

    if raw_course.get("estRetenue"):
        return Detention(**common, state=raw_course.get("hintRealise"))

    return Lesson(
        **common,
        canceled=bool(raw_course.get("estAnnule", False)),
        status=raw_course.get("Statut"),
        background_color=raw_course.get("CouleurFond"),
        has_evaluation=bool((raw_course.get("cahierDeTextes") or {}).get("estEval", False)),
        videoconferences=[
            {"comment": v.get("commentaire"), "label": v.get("libelleLien"), "url": v.get("url")}
            for v in raw_course.get("listeVisios") or []
        ],
    )


def parse_timetable(data: dict[str, Any], seats_per_hour: float) -> list[TimeSlot]:
    """Turn a (parsed, unwrapped) PageEmploiDuTemps response into sorted slots."""
    slots = [_parse_slot(course, seats_per_hour) for course in data.get("ListeCours", [])]
    slots.sort(key=lambda slot: slot.start)
    return slots


def group_by_day(slots: list[TimeSlot]) -> list[TimetableDay]:
    """Group already-sorted slots by calendar day."""
    days: dict[date, list[TimeSlot]] = {}
    for slot in slots:
        days.setdefault(slot.start.date(), []).append(slot)
    return [TimetableDay(date=day, slots=items) for day, items in sorted(days.items())]


def get_timetable(
    session: PronoteSession,
    resource: Resource,
    *,
    week_number: Union[int, str, None] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    **options: bool,
) -> list[TimeSlot]:
    """
    Fetch a timetable for `resource`, either for a school-week number or for
    an explicit `start`/`end` range. Returns slots sorted by start time;
    use `group_by_day` to bucket them per day.
    """
    if week_number is None and (start is None or end is None):
        raise ValueError("Provide either week_number, or both start and end.")

    try:
        seats_per_hour = session.settings["General"]["PlacesParHeure"]
    except KeyError as exc:
        raise PronoteError(
            "Missing 'PlacesParHeure' in the instance settings - was the session created by login()?"
        ) from exc

    data = session.post(
        FUNCTION_NAME,
        build_payload(resource, week_number=week_number, start=start, end=end, **options),
        signature=build_signature(session.workspace.type, resource),
    )
    return parse_timetable(data, seats_per_hour)
