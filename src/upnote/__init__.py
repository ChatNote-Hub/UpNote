"""
UpNote - an unofficial, from-scratch Python client for the PRONOTE protocol.

Public API:

    from upnote import login, NOTSpace, UpNoteError

    session = login(
        "https://demo.index-education.net/pronote/eleve.html",
        "demonstration",
        "pronotevs",
        workspace_type=NOTSpace.STUDENT,
    )
    data = session.post("ParametresUtilisateur", {})

See the README for a full protocol write-up and `examples/` for more.
"""
from .client import Instance, CAS, login
from .constants import NOTSpace
from .session import PronoteSession, PronoteError as UpNoteError, Workspace

__version__ = "0.1.0"

__all__ = [
    "login",
    "Instance",
    "CAS",
    "NOTSpace",
    "PronoteSession",
    "UpNoteError",
    "Workspace",
    "__version__",
]
