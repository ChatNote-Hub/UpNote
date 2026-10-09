"""
UpNote - an unofficial, from-scratch Python client for the PRONOTE protocol.

Public API:

    from upnote import login, get_user, get_timetable, NOTSpace

    session = login(
        "https://demo.index-education.net/pronote/eleve.html",
        "demonstration",
        "pronotevs",
        workspace_type=NOTSpace.STUDENT,
    )
    user = get_user(session)
    lessons = get_timetable(session, user.resource, week_number=12)

See the README for a quick start and docs/PROTOCOL.md for the protocol write-up.
"""
from .client import CAS, Instance, login
from .constants import NOTSpace
from .session import PronoteError as UpNoteError
from .session import PronoteSession, Workspace
from .timetable import Detention, Lesson, TimeSlot, TimetableDay, get_timetable, group_by_day
from .user import Resource, User, get_user

__version__ = "0.2.0"

__all__ = [
    "login",
    "get_user",
    "get_timetable",
    "group_by_day",
    "Instance",
    "CAS",
    "NOTSpace",
    "PronoteSession",
    "Workspace",
    "Resource",
    "User",
    "TimeSlot",
    "Lesson",
    "Detention",
    "TimetableDay",
    "UpNoteError",
    "__version__",
]
