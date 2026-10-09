"""Offline tests for timetable.py and user.py (no network, no pytest needed)."""
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests

from upnote import parsing, timetable
from upnote.session import PronoteSession, Workspace
from upnote.user import Resource, get_user

RESOURCE = Resource(kind=4, id="abc123")


def _session(workspace_type=6):
    session = PronoteSession(
        "https://demo.index-education.net/pronote",
        Workspace(delegated=False, url="mobile.eleve.html", name="Students", type=workspace_type),
    )
    session.session_id = "1"
    session.settings = {"General": {"PlacesParHeure": 2}}
    return session


@contextmanager
def _patched_post(response_body, captured):
    original = requests.Session.post

    def fake_post(self, url, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value=response_body)
        return resp

    requests.Session.post = fake_post
    try:
        yield
    finally:
        requests.Session.post = original


def _course(**overrides):
    base = {
        "DateDuCours": datetime(2026, 3, 9, 8, 0),
        "duree": 4,
        "place": 0,
        "CouleurFond": "#ff0000",
        "ListeContenus": [
            {"G": 16, "label": "MATHEMATIQUES"},
            {"G": 3, "label": "M. DUPONT"},
            {"G": 17, "label": "B12"},
            {"G": 2, "label": "2NDE 3"},
        ],
    }
    base.update(overrides)
    return base


def test_build_payload_week_number_uses_dual_case_keys():
    payload = timetable.build_payload(RESOURCE, week_number=12)

    assert payload["numeroSemaine"] == 12
    assert payload["NumeroSemaine"] == 12
    assert payload["ressource"] == {"G": 4, "N": "abc123"}
    assert payload["Ressource"] == {"G": 4, "N": "abc123"}
    assert payload["avecAbsencesEleve"] is False
    assert payload["avecRetenuesEleve"] is True
    assert "dateDebut" not in payload


def test_build_payload_date_range_wins_over_week_number():
    payload = timetable.build_payload(
        RESOURCE,
        week_number=12,
        start=datetime(2026, 3, 5, 8, 5, 0),
        end=datetime(2026, 3, 12),
    )

    assert payload["dateDebut"] == {"_T": 7, "V": "5/3/2026 8:5:0"}
    assert payload["DateFin"] == {"_T": 7, "V": "12/3/2026 0:0:0"}
    assert "numeroSemaine" not in payload


def test_build_signature_by_workspace():
    assert timetable.build_signature(6, RESOURCE) == {"onglet": 16}
    assert timetable.build_signature(17, RESOURCE) == {"onglet": 60}
    assert timetable.build_signature(14, RESOURCE) == {"onglet": 171}
    assert timetable.build_signature(7, RESOURCE) == {"onglet": 16, "membre": {"G": 4, "N": "abc123"}}


def test_parse_timetable_lesson_fields_and_duration():
    slots = timetable.parse_timetable({"ListeCours": [_course()]}, seats_per_hour=2)

    lesson = slots[0]
    assert isinstance(lesson, timetable.Lesson)
    assert lesson.subject == "MATHEMATIQUES"
    assert lesson.teachers == ["M. DUPONT"]
    assert lesson.rooms == ["B12"]
    assert lesson.groups == ["2NDE 3"]
    assert lesson.canceled is False
    # 4 slots at 2 slots per hour = 2 hours
    assert lesson.end == datetime(2026, 3, 9, 10, 0)


def test_parse_timetable_detention_and_cancellation():
    data = {
        "ListeCours": [
            _course(estAnnule=True, Statut="Cours annule"),
            _course(estRetenue="oui", hintRealise="A faire", DateDuCours=datetime(2026, 3, 9, 17, 0)),
        ]
    }
    first, second = timetable.parse_timetable(data, seats_per_hour=2)

    assert isinstance(first, timetable.Lesson) and first.canceled and first.status == "Cours annule"
    assert isinstance(second, timetable.Detention) and second.state == "A faire"


def test_parse_timetable_sorts_and_groups_by_day():
    data = {
        "ListeCours": [
            _course(DateDuCours=datetime(2026, 3, 10, 9, 0)),
            _course(DateDuCours=datetime(2026, 3, 9, 14, 0)),
            _course(DateDuCours=datetime(2026, 3, 9, 8, 0)),
        ]
    }
    slots = timetable.parse_timetable(data, seats_per_hour=2)
    days = timetable.group_by_day(slots)

    assert [s.start.hour for s in slots] == [8, 14, 9]
    assert [d.date.day for d in days] == [9, 10]
    assert len(days[0].slots) == 2


def test_get_timetable_requires_week_or_range():
    try:
        timetable.get_timetable(_session(), RESOURCE)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_get_timetable_end_to_end_with_mocked_http():
    captured = {}
    body = {
        "dataSec": {
            "data": {"ListeCours": [{"DateDuCours": {"_T": 7, "V": "9/3/2026 8:0:0"}, "duree": 2, "place": 0,
                                      "ListeContenus": [{"G": 16, "L": "HISTOIRE"}]}]},
            "_Signature_": {},
        }
    }
    session = _session()
    session.use_encryption = False
    session.use_compression = False

    with _patched_post(body, captured):
        slots = timetable.get_timetable(session, RESOURCE, week_number=12)

    sent = captured["json"]
    assert sent["id"] == "PageEmploiDuTemps"
    assert sent["dataSec"]["Signature"] == {"onglet": 16}
    assert sent["dataSec"]["data"]["numeroSemaine"] == 12
    assert slots[0].subject == "HISTOIRE"
    assert slots[0].end == datetime(2026, 3, 9, 9, 0)


def test_get_user_extracts_resource():
    captured = {}
    body = {
        "dataSec": {
            "data": {"ressource": {"G": 4, "N": "xyz", "L": "DUPONT Jean"}},
            "_Signature_": {},
        }
    }
    session = _session()
    session.use_encryption = False
    session.use_compression = False

    with _patched_post(body, captured):
        user = get_user(session)

    assert user.full_name == "DUPONT Jean"
    assert user.resource == Resource(kind=4, id="xyz")


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
