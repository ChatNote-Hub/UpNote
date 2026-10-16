"""The contract between UpNote and ENT (school portal) login helpers."""
from __future__ import annotations

from typing import Any, Protocol

from ..session import PronoteError


class EntLoginError(PronoteError):
    """The ENT / CAS server did not accept the login."""


class EntProvider(Protocol):
    """
    A callable that logs in to an ENT and returns the cookies that PRONOTE
    needs to recognise the user (a `requests` cookie jar, or a plain
    `{name: value}` dict).

    It receives the direct PRONOTE page URL (query string removed) so it can
    target the right service. This mirrors pronotepy's ENT functions, so
    providers are easy to port. To support a new ENT, write one function with
    this signature in its own module under `upnote/ent/`.
    """

    def __call__(self, username: str, password: str, *, pronote_url: str) -> Any: ...
