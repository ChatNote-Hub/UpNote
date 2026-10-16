"""
High-level entry point, mirroring Instance.ts + Authenticator.ts from
Blocksnote: discovering the workspaces available on an instance, then a
full login (FonctionParametres -> Identification -> Authentification).
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from . import constants, crypto
from .ent import EntProvider, cas_provider
from .session import PronoteError, PronoteSession, Workspace


@dataclass
class CAS:
    url: str
    token: str


@dataclass
class Instance:
    source: str
    workspaces: list[Workspace]
    version: list[int]
    cas: Optional[CAS] = None

    @staticmethod
    def clean_url(source: str) -> str:
        """Mirrors Instance.cleanUrl: keeps only the /pronote/ root."""
        if not source.startswith("http"):
            source = "https://" + source
        parsed = urlparse(source.strip())
        segments = [s for s in parsed.path.split("/") if s]
        while segments and segments[-1].lower().endswith(".html"):
            segments.pop()
        base_path = "/".join(segments)
        root = f"{parsed.scheme}://{parsed.netloc}/{base_path + '/' if base_path else ''}"
        return root.lower()

    @classmethod
    def create_from_url(cls, source: str) -> "Instance":
        source = cls.clean_url(source)
        url = f"{source}InfoMobileApp.json?id={constants.INFO_MOBILE_ID}"

        response = requests.get(url, headers={"User-Agent": constants.USER_AGENT})
        response.raise_for_status()
        data = response.json()

        workspaces = [
            Workspace(
                delegated=raw.get("avecDelegation", False),
                url=raw["URL"],
                name=raw["nom"],
                type=raw["genreEspace"],
            )
            for raw in data.get("espaces", [])
            if raw.get("genreEspace") is not None
        ]

        cas = None
        cas_info = data.get("CAS", {})
        if cas_info.get("actif"):
            cas = CAS(url=cas_info["casURL"], token=cas_info["jetonCAS"])

        return cls(source=source, workspaces=workspaces, version=data.get("version", []), cas=cas)

    def workspace(self, type_: int) -> Workspace:
        for w in self.workspaces:
            if int(w.type) == int(type_):
                return w
        raise PronoteError(f"No workspace of type {type_} available on this instance.")


def login(source: str, username: str, password: str, workspace_type: int = constants.NOTSpace.STUDENT) -> PronoteSession:
    """
    Full username/password login. Mirrors Authenticator.credentials() from
    Blocksnote.
    """
    instance = Instance.create_from_url(source)
    workspace = instance.workspace(workspace_type)
    session = PronoteSession.create(instance.source, workspace)

    session.settings = _load_settings(session)
    challenge_hex, seed = _request_identification(session, username)
    _authenticate(session, challenge_hex, crypto.generate_temp_key(username, password, seed))

    return session


def _load_settings(session: PronoteSession) -> dict:
    """
    Mirrors Settings.load: sends FonctionParametres with a new iv, BUILT
    AND ENCRYPTED with the OLD iv, then updates the session iv BEFORE
    reading/decrypting the response (this exact ordering matters).
    """
    raw_iv = os.urandom(16)
    uuid = (
        base64.b64encode(raw_iv).decode()
        if session.use_https
        else base64.b64encode(crypto.rsa_encrypt(raw_iv)).decode()
    )

    no_hex = session._next_no_hex()  # built WITH the old iv
    payload = session._process_payload({"Signature": None, "data": {"Uuid": uuid, "identifiantNav": None}})
    body = {
        "session": int(session.session_id),
        "no": no_hex,
        "id": "FonctionParametres",
        "dataSec": payload,
    }
    url = f"{session.source}/appelfonction/{int(session.workspace.type)}/{session.session_id}/{no_hex}"

    session.aes.set_iv(raw_iv)  # from here on, the NEW iv is active

    response = session.http.post(url, json=body)
    response.raise_for_status()
    session.request_number += 2

    raw = response.json()
    if "Erreur" in raw:
        err = raw["Erreur"]
        raise PronoteError(err.get("Titre", "Unknown PRONOTE error"), code=err.get("G"))

    return session._process_response(raw)


def _request_identification(
    session: PronoteSession, username: str, *, for_ent: bool = False
) -> tuple[str, str]:
    data = session.post(
        "Identification",
        {
            "demandeConnexionAppliMobile": False,
            "demandeConnexionAppliMobileJeton": False,
            "demandeConnexionAuto": False,
            "enConnexionAppliMobile": False,
            "enConnexionAuto": False,
            "genreConnexion": 0,
            "genreEspace": int(session.workspace.type),
            "identifiant": username,
            "informationsAppareil": None,
            "loginTokenSAV": "",
            "pourENT": for_ent,
            "uuidAppliMobile": "",
        },
    )
    return data["challenge"], data.get("alea", "") or ""


def _authenticate(session: PronoteSession, challenge_hex: str, temp_key: str) -> None:
    """
    Answer the challenge and install the final session key. `temp_key` is the
    key material derived from the credentials (`crypto.generate_temp_key` for
    password logins, `crypto.generate_ent_key` for ENT logins).
    """
    solution = crypto.solve_challenge_with_key(session.aes, challenge_hex, temp_key)

    data = session.post(
        "Authentification",
        {"challenge": solution, "connexion": 0, "espace": int(session.workspace.type)},
    )

    if "cle" not in data:
        raise PronoteError(
            "Unable to retrieve the final AES key. Credentials are probably incorrect."
        )

    # Re-applies the temporary key to decrypt 'cle', like Authenticator.authenticate
    session.aes.set_key(temp_key.encode())
    decrypted = session.aes.decrypt_hex(data["cle"]).decode()

    final_key_bytes = bytes(int(x) for x in decrypted.split(","))
    session.aes.set_key(final_key_bytes)


# --- ENT / CAS login -----------------------------------------------------------

def _split_page_url(url: str) -> tuple[str, str, str]:
    """
    "https://host/pronote/eleve.html?login=true" ->
    ("https://host/pronote", "eleve.html", "https://host/pronote/eleve.html").
    """
    parsed = urlparse(url.strip())
    segments = [seg for seg in parsed.path.split("/") if seg]
    if not parsed.netloc or not segments or not segments[-1].lower().endswith(".html"):
        raise ValueError(
            "Expected the direct URL of a workspace page, "
            "e.g. https://host/pronote/eleve.html (not the PRONOTE root)."
        )
    page = segments[-1]
    root = f"{parsed.scheme}://{parsed.netloc}" + "".join(f"/{seg}" for seg in segments[:-1])
    return root, page, f"{root}/{page}"


def _workspace_type_from_page(page: str) -> Optional[int]:
    name = page.lower().removesuffix(".html").removeprefix("mobile.")
    space = constants.WORKSPACE_PAGES.get(name)
    return int(space) if space is not None else None


def login_ent(
    url: str,
    username: str = "",
    password: str = "",
    *,
    ent: Optional[EntProvider] = None,
    cookies: Optional[Any] = None,
    workspace_type: Optional[int] = None,
) -> PronoteSession:
    """
    Log in through an ENT (school portal / CAS single sign-on).

    `url` is the direct URL of the workspace page, e.g.
    `https://0000000a.index-education.net/pronote/eleve.html` (a trailing
    `?login=true` is ignored). The ENT session can come from three places:

    - `cookies=`: cookies you obtained yourself (works for any ENT, including
      EduConnect/SAML ones - log in with a browser and export them);
    - `ent=`: an `EntProvider` that logs in with `username`/`password` (see
      `upnote.ent`);
    - neither: if the instance advertises a CAS server in InfoMobileApp.json,
      a generic form-based CAS login is attempted.

    Once PRONOTE accepts the ENT session it hands out two one-time values,
    `e` and `f`, which act as the identifier and password for the usual
    challenge exchange (`pourENT` set to true).
    """
    if cookies is not None and ent is not None:
        raise ValueError("Pass either cookies= or ent=, not both.")

    root, page, page_url = _split_page_url(url)

    resolved_type = workspace_type if workspace_type is not None else _workspace_type_from_page(page)
    if resolved_type is None:
        raise ValueError(f"Cannot tell the workspace type from {page!r}: pass workspace_type=.")

    if cookies is None:
        if not (username and password):
            raise ValueError("username and password are required unless cookies= is given.")
        if ent is None:
            instance = Instance.create_from_url(root)
            if instance.cas is None:
                raise PronoteError(
                    "This instance does not advertise a CAS server. Pass ent= (an EntProvider) "
                    "or cookies= obtained from your ENT."
                )
            ent = cas_provider(instance.cas.url)
        cookies = ent(username, password, pronote_url=page_url)

    workspace = Workspace(delegated=False, url=page, name=page, type=resolved_type)
    session = PronoteSession.create(root, workspace, mobile=False, cookies=cookies)

    e, f = session.attributes.get("e"), session.attributes.get("f")
    if not e or not f:
        raise PronoteError(
            "PRONOTE did not return the ENT identifiers ('e' and 'f') - the ENT session was not "
            "accepted, or this instance does not use that ENT."
        )

    session.settings = _load_settings(session)
    challenge_hex, _ = _request_identification(session, e, for_ent=True)
    _authenticate(session, challenge_hex, crypto.generate_ent_key(f))

    return session
