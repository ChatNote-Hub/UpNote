"""
PRONOTE session: mirrors Request.ts + RequestManager.ts + Session.ts from
Blocksnote.

Important detail taken from Settings.ts (FonctionParametres): the request
is BUILT AND ENCRYPTED with the OLD iv, then the session iv is updated, and
it's the NEW iv that's used to decrypt the response. That's the only place
where building the request and decrypting the response don't use the same
iv.
"""
from __future__ import annotations

import re
import json as jsonlib
import zlib
from dataclasses import dataclass
from typing import Any, Optional

import requests

from . import constants, crypto, parsing


@dataclass
class Workspace:
    delegated: bool
    url: str
    name: str
    type: int  # see constants.NOTSpace


class PronoteError(Exception):
    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


class PronoteSession:
    """
    A session opened on a PRONOTE instance (after the initial GET request).
    """

    def __init__(self, source: str, workspace: Workspace):
        self.source = source.rstrip("/")
        self.workspace = workspace

        self.http = requests.Session()
        self.http.headers.update({"User-Agent": constants.USER_AGENT})

        self.aes = crypto.AESSession()

        self.session_id: Optional[str] = None
        self.use_compression = False
        self.use_encryption = False
        self.use_https = True

        self.request_number = 0  # like RequestManager.requestNumber

    # --- Step 1: opening a session ---------------------------------------

    @classmethod
    def create(cls, source: str, workspace: Workspace) -> "PronoteSession":
        session = cls(source, workspace)

        endpoint = f"{session.source.rstrip('/')}/{workspace.url.lstrip('/')}?fd=1&bydlg={constants.BYPASS_ID}"
        response = session.http.get(endpoint)
        response.raise_for_status()
        text = response.text

        # The body contains <... onload="Start({h:'...',sCrA:true,sCoA:true,a:6,...})">
        match = re.search(r"Start\s*\(\{([^}]*)\}\)", text)
        if not match:
            raise PronoteError(
                "Unable to parse the HTML page. Make sure the URL points "
                "directly to a workspace (eleve.html, parent.html, ...)."
            )

        attrs: dict[str, str] = {}
        for part in match.group(1).split(","):
            key, _, value = part.partition(":")
            attrs[key.strip().strip("'\"")] = value.strip().strip("'\"")

        if "h" not in attrs:
            raise PronoteError("Session id ('h') missing from the HTML response.")

        session.session_id = attrs["h"]
        session.use_encryption = attrs.get("sCrA", "false") == "true"
        session.use_compression = attrs.get("sCoA", "false") == "true"
        session.use_https = "http" not in attrs or attrs.get("http") != "true"

        return session

    # --- Building / sending appelfonction requests -------------------------

    def _next_no_hex(self) -> str:
        next_request_number = self.request_number + 1
        return self.aes.encrypt_hex(str(next_request_number))

    def post(self, function_name: str, data: Any, signature: Any = None) -> dict:
        """
        Sends an appelfonction request. Does NOT itself handle an iv/key
        change mid-request (see client.py, which calls aes.set_iv /
        aes.set_key between building the request and reading the response,
        exactly like Settings.load on the JS side).
        """
        no_hex = self._next_no_hex()

        payload: Any = {"Signature": signature, "data": data}
        payload = self._process_payload(payload)

        body = {
            "session": int(self.session_id),  # type: ignore[arg-type]
            "no": no_hex,
            "id": function_name,
            "dataSec": payload,
        }

        url = f"{self.source}/appelfonction/{int(self.workspace.type)}/{self.session_id}/{no_hex}"
        response = self.http.post(url, json=body)
        response.raise_for_status()
        self.request_number += 2

        raw = response.json()
        if "Erreur" in raw:
            err = raw["Erreur"]
            raise PronoteError(err.get("Titre", "Unknown PRONOTE error"), code=err.get("G"))

        return self._process_response(raw)

    def _process_payload(self, data: Any) -> Any:
        """
        WARNING - asymmetry confirmed in both pronotepy AND Blocksnote:
        compressing an OUTGOING request does NOT compress the UTF-8 bytes
        of the JSON directly, but the HEXADECIMAL representation of those
        bytes (so the text is "inflated" x2 into hex before being
        deflated). See _process_response below: decompressing an INCOMING
        response does NOT go through this hex detour.
        """
        if not self.use_compression and not self.use_encryption:
            return data

        text = jsonlib.dumps(data)

        if self.use_compression:
            hex_str = text.encode().hex()
            compressor = zlib.compressobj(6, zlib.DEFLATED, -15)  # raw deflate, level 6
            out: bytes = compressor.compress(hex_str.encode()) + compressor.flush()
        else:
            out = text.encode()

        if self.use_encryption:
            out = self.aes.encrypt(out).hex().upper()
        else:
            # compression only (no encryption) - still need to hex-encode
            # the compressed binary bytes to keep this JSON-transportable
            out = out.hex().upper()

        return out

    def _process_response(self, raw: dict) -> dict:
        """
        No hex detour here (unlike _process_payload): after decrypting +
        decompressing, we land directly on the UTF-8 bytes of the JSON.

        IMPORTANT - this was the source of a real bug: the decoded JSON is
        an envelope shaped like `{"data": {...}, "_Signature_": ...}`
        (mirroring the `{Signature, data}` shape we send in requests), not
        the useful fields directly. Blocksnote's Request._processResponse
        confirms this: it runs the whole thing through Parser.parse() and
        returns `parsed.data`. Forgetting this unwrap step meant
        `data["challenge"]` raised KeyError even though the request/response
        cycle otherwise worked correctly - the challenge was there, just one
        level deeper, at `data["data"]["challenge"]`.
        """
        data_sec = raw.get("dataSec")
        if data_sec is None:
            return {}

        processed: Any = data_sec

        if self.use_encryption:
            processed = self.aes.decrypt(bytes.fromhex(processed))

        if self.use_compression:
            raw_bytes = processed if isinstance(processed, (bytes, bytearray)) else bytes.fromhex(processed)
            decompressor = zlib.decompressobj(-15)
            decompressed = decompressor.decompress(raw_bytes) + decompressor.flush()
            processed = jsonlib.loads(decompressed.decode())
        elif isinstance(processed, (bytes, bytearray)):
            processed = jsonlib.loads(processed.decode())

        parsed = parsing.parse(processed)

        if not isinstance(parsed, dict) or parsed.get("data") is None:
            return {}

        return parsed["data"]
