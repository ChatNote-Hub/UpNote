"""
High-level entry point, mirroring Instance.ts + Authenticator.ts from
Blocksnote: discovering the workspaces available on an instance, then a
full login (FonctionParametres -> Identification -> Authentification).
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests

from . import constants, crypto
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

    _load_settings(session)
    challenge_hex, seed = _request_identification(session, username)
    _authenticate(session, username, password, challenge_hex, seed)

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


def _request_identification(session: PronoteSession, username: str) -> tuple[str, str]:
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
            "pourENT": False,
            "uuidAppliMobile": "",
        },
    )
    return data["challenge"], data.get("alea", "") or ""


def _authenticate(session: PronoteSession, username: str, password: str, challenge_hex: str, seed: str) -> None:
    solution = crypto.solve_challenge_session(session.aes, challenge_hex, username, password, seed)

    data = session.post(
        "Authentification",
        {"challenge": solution, "connexion": 0, "espace": int(session.workspace.type)},
    )

    if "cle" not in data:
        raise PronoteError(
            "Unable to retrieve the final AES key. Credentials are probably incorrect."
        )

    # Re-applies the temporary key to decrypt 'cle', like Authenticator.authenticate
    temp_key = crypto.generate_temp_key(username, password, seed)
    session.aes.set_key(temp_key.encode())
    decrypted = session.aes.decrypt_hex(data["cle"]).decode()

    final_key_bytes = bytes(int(x) for x in decrypted.split(","))
    session.aes.set_key(final_key_bytes)
