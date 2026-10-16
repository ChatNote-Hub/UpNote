"""
Generic form-based CAS (Apereo CAS and compatible) login.

Works for ENTs whose login page is a plain CAS form: username + password
posted to `<cas>/login?service=...`. It does NOT cover ENTs that delegate to
EduConnect / SAML, or that require a captcha or a second factor - for those,
write a dedicated provider, or log in with a browser and pass the cookies to
`upnote.login_ent(cookies=...)`.

Only the standard library is used for HTML parsing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests

from .. import constants
from .base import EntLoginError, EntProvider

_REDIRECTS = (301, 302, 303, 307, 308)
_NON_VALUE_INPUTS = ("submit", "button", "image", "reset", "file", "checkbox", "radio")


@dataclass
class _Form:
    action: str = ""
    method: str = "get"
    inputs: list[tuple[str, str, str]] = field(default_factory=list)  # (name, type, value)


class _FormParser(HTMLParser):
    """Collects every <form> and its <input> elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_Form] = []
        self._current: Optional[_Form] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "form":
            self._current = _Form(action=a.get("action", ""), method=a.get("method", "get").lower())
            self.forms.append(self._current)
        elif tag == "input" and self._current is not None:
            name = a.get("name")
            if name:
                self._current.inputs.append((name, a.get("type", "text").lower(), a.get("value", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current = None


def _login_form(html: str) -> Optional[_Form]:
    """The first form that has a password field, or None."""
    parser = _FormParser()
    parser.feed(html)
    for form in parser.forms:
        if any(kind == "password" for _, kind, _ in form.inputs):
            return form
    return None


def _build_submission(form: _Form, username: str, password: str) -> dict[str, str]:
    data: dict[str, str] = {}
    user_field_set = False

    for name, kind, value in form.inputs:
        if kind == "password":
            data[name] = password
        elif kind in ("text", "email") and not user_field_set:
            data[name] = username
            user_field_set = True
        elif kind not in _NON_VALUE_INPUTS:
            data[name] = value  # hidden fields: lt, execution, ...

    if not user_field_set:
        raise EntLoginError("Could not find a username field in the CAS login form.")

    # CAS web flows need the event id; most forms carry it as a hidden field.
    if "execution" in data and "_eventId" not in data:
        data["_eventId"] = "submit"
    return data


def cas_login(
    cas_url: str,
    username: str,
    password: str,
    *,
    service: str,
    timeout: float = 30.0,
) -> requests.cookies.RequestsCookieJar:
    """
    Log in to a CAS server and return the resulting cookies (notably the
    single sign-on ticket-granting cookie).

    The redirect that carries the service ticket is deliberately NOT
    followed: PRONOTE will ask CAS for a fresh ticket itself when its page is
    requested with these cookies, so the unused one just expires.
    """
    login_url = cas_url.rstrip("/")
    if not urlparse(login_url).path.endswith("/login"):
        login_url += "/login"

    http = requests.Session()
    http.headers.update({"User-Agent": constants.DESKTOP_USER_AGENT})

    page = http.get(login_url, params={"service": service}, timeout=timeout)
    page.raise_for_status()

    form = _login_form(page.text)
    if form is None:
        raise EntLoginError(
            "No login form found on the CAS page. This ENT probably uses another sign-in "
            "mechanism (EduConnect / SAML / captcha): use a dedicated provider, or pass "
            "browser cookies with login_ent(cookies=...)."
        )

    submit_url = urljoin(page.url, form.action)
    response = http.post(
        submit_url,
        data=_build_submission(form, username, password),
        allow_redirects=False,
        timeout=timeout,
    )

    if response.status_code in _REDIRECTS and response.headers.get("Location"):
        return http.cookies
    if response.status_code == 200 and _login_form(response.text) is None:
        return http.cookies  # logged in, but CAS stayed on a confirmation page

    raise EntLoginError("The CAS server rejected the login (wrong credentials, or an unsupported login step).")


def cas_provider(cas_url: str, *, service: Optional[str] = None) -> EntProvider:
    """
    Build an `EntProvider` for a CAS server. `service` defaults to the
    PRONOTE root URL (`https://host/pronote/`), which is what existing ENT
    helpers target; override it if your CAS only accepts another service URL.
    """

    def provider(username: str, password: str, *, pronote_url: str):
        target = service or pronote_url.rsplit("/", 1)[0] + "/"
        return cas_login(cas_url, username, password, service=target)

    return provider
