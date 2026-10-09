"""
The logged-in user, as described by the `ParametresUtilisateur` function.

Mirrors the identity part of `routes/ParametresUtilisateurs/Common.ts`
from Blocksnote. Most data endpoints (timetable, grades, ...) need the
user's own "resource" - a (kind, id) pair PRONOTE uses to designate a
student, teacher, class, etc. - which comes from this call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .session import PronoteSession


@dataclass(frozen=True)
class Resource:
    """A PRONOTE resource: `kind` is the "G" code, `id` the "N" identifier."""

    kind: int
    id: str


@dataclass
class User:
    full_name: str
    resource: Resource
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def get_user(session: PronoteSession) -> User:
    """Fetch the logged-in user's identity (one `ParametresUtilisateur` call)."""
    data = session.post("ParametresUtilisateur", {})
    ressource = data["ressource"]

    return User(
        full_name=ressource.get("label", ""),
        resource=Resource(kind=ressource["G"], id=ressource["id"]),
        raw=data,
    )
