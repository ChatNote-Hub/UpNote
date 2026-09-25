"""
Tests for session.py WITHOUT network access (this sandbox has no internet
access, and pytest isn't installable here either). We patch
requests.Session.get/post by hand to check that:

- parsing the initial HTML (Start({...})) works
- request bodies (no, session, id, dataSec) are built correctly
- the compression+encryption pipeline is internally consistent

This does NOT replace testing against the real demo server - just a check
of the internal logic, with zero external dependencies (pytest included).
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from pronote_wrapper import crypto
from pronote_wrapper.session import PronoteSession, Workspace


def _fake_workspace():
    return Workspace(delegated=False, url="/eleve.html", name="Students", type=6)


@contextmanager
def _patched(method_name: str, replacement):
    original = getattr(requests.Session, method_name)
    setattr(requests.Session, method_name, replacement)
    try:
        yield
    finally:
        setattr(requests.Session, method_name, original)


def test_session_create_parses_onload_attrs():
    html = (
        "<html><body onload=\"try { Start ({h:'2052117',sCrA:true,sCoA:true,a:6,d:true}) } "
        "catch (e) { messageErreur (e) } \"></body></html>"
    )
    fake_response = MagicMock()
    fake_response.text = html
    fake_response.raise_for_status = MagicMock()

    with _patched("get", lambda self, url, **kw: fake_response):
        session = PronoteSession.create("https://demo.index-education.net/pronote", _fake_workspace())

    assert session.session_id == "2052117"
    assert session.use_encryption is True
    assert session.use_compression is True
    assert session.use_https is True


def test_session_create_joins_url_without_double_slash_bug():
    """
    Regression test: InfoMobileApp.json returns workspace URLs WITHOUT a
    leading slash (e.g. "mobile.eleve.html", not "/mobile.eleve.html").
    Combined with an Instance.source that has its trailing slash stripped
    in PronoteSession.__init__, naive string concatenation produced
    "https://host/pronotemobile.eleve.html" (missing slash) - a real bug
    hit against the live demo server. This test locks in the fix
    regardless of whether either side does or doesn't have its slash.
    """
    html = "<html><body onload=\"try { Start ({h:'1',sCrA:false,sCoA:false,a:6}) } catch (e) {}\"></body></html>"
    fake_response = MagicMock()
    fake_response.text = html
    fake_response.raise_for_status = MagicMock()

    captured_urls = []

    def fake_get(self, url, **kw):
        captured_urls.append(url)
        return fake_response

    workspace_no_leading_slash = Workspace(delegated=False, url="mobile.eleve.html", name="Students", type=6)

    with _patched("get", fake_get):
        PronoteSession.create("https://demo.index-education.net/pronote/", workspace_no_leading_slash)

    assert captured_urls[0].startswith(
        "https://demo.index-education.net/pronote/mobile.eleve.html?"
    )
    assert "pronotemobile" not in captured_urls[0]


def test_post_builds_correct_body_no_encryption():
    captured = {}

    def fake_post(self, url, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        # Real PRONOTE responses wrap the useful fields one level deeper,
        # under "data" (mirroring the {Signature, data} shape of requests).
        resp.json = MagicMock(return_value={"dataSec": {"data": {"donnees": {"ok": True}}, "_Signature_": {}}})
        return resp

    session = PronoteSession("https://demo.index-education.net/pronote", _fake_workspace())
    session.session_id = "2052117"
    session.use_encryption = False
    session.use_compression = False

    with _patched("post", fake_post):
        result = session.post("ParametresUtilisateur", {})

    # first call -> requestNumber=0 before the call, so "no" encrypts "1"
    assert captured["json"]["no"] == crypto.AESSession().encrypt_hex("1")
    assert captured["json"]["session"] == 2052117
    assert captured["json"]["id"] == "ParametresUtilisateur"
    assert session.request_number == 2  # incremented by 2 after the call
    assert result == {"donnees": {"ok": True}}


def test_process_response_unwraps_data_envelope():
    """
    Regression test for a real bug hit against the live demo server:
    _process_response used to return the raw decoded dict directly, but
    PRONOTE always wraps the useful fields one level deeper, under "data"
    (e.g. {"data": {"challenge": "...", "alea": "..."}, "_Signature_": {}}).
    Forgetting to unwrap it meant data["challenge"] raised KeyError even
    though the request/response cycle otherwise worked fine.
    """
    session = PronoteSession("https://demo.index-education.net/pronote", _fake_workspace())
    session.session_id = "1"
    session.use_encryption = False
    session.use_compression = False

    raw = {"dataSec": {"data": {"challenge": "deadbeef", "alea": "someSeed"}, "_Signature_": {}}}
    result = session._process_response(raw)

    assert result == {"challenge": "deadbeef", "alea": "someSeed"}


def test_process_response_missing_data_key_returns_empty_dict():
    session = PronoteSession("https://demo.index-education.net/pronote", _fake_workspace())
    session.use_encryption = False
    session.use_compression = False

    assert session._process_response({"dataSec": {"_Signature_": {}}}) == {}
    assert session._process_response({}) == {}


def test_request_payload_compression_uses_hex_detour():
    """
    Checks the EXACT expected format for an outgoing request (compression +
    encryption): JSON -> hex(utf8) -> raw deflate -> AES -> hex upper. We
    decode it "by hand" in reverse to confirm the format, instead of going
    through _process_response (which follows a different format on the
    response side, see the next test).
    """
    import zlib as _zlib
    import json as _json

    session = PronoteSession("https://demo.index-education.net/pronote", _fake_workspace())
    session.session_id = "12345"
    session.use_encryption = True
    session.use_compression = True

    original = {"Signature": {"onglet": 7}, "data": {"hello": "world", "n": 42}}
    encoded = session._process_payload(original)
    assert isinstance(encoded, str)

    decrypted = session.aes.decrypt(bytes.fromhex(encoded))
    decompressor = _zlib.decompressobj(-15)
    inflated = decompressor.decompress(decrypted) + decompressor.flush()
    # still need one more hex-decode step here - that's the protocol's "bump"
    recovered = bytes.fromhex(inflated.decode()).decode()
    assert _json.loads(recovered) == original


def test_response_decompression_no_hex_detour():
    """
    Checks the expected format for an INCOMING response (compression +
    encryption): unlike the request, there's no hex detour after
    decompression - we land directly on the UTF-8 bytes of the JSON
    (which is itself the {"data": {...}, "_Signature_": ...} envelope, see
    test_process_response_unwraps_data_envelope). We build a fake
    "server-style" response here to confirm that _process_response decodes
    and unwraps it correctly.
    """
    import json as _json
    import zlib as _zlib

    session = PronoteSession("https://demo.index-education.net/pronote", _fake_workspace())
    session.session_id = "12345"
    session.use_encryption = True
    session.use_compression = True

    envelope = {"data": {"donnees": {"hello": "world", "n": 42}}, "_Signature_": {}}

    compressor = _zlib.compressobj(6, _zlib.DEFLATED, -15)
    compressed = compressor.compress(_json.dumps(envelope).encode()) + compressor.flush()
    encrypted_hex = session.aes.encrypt(compressed).hex()  # as sent by the server

    decoded = session._process_response({"dataSec": encrypted_hex})
    assert decoded == {"donnees": {"hello": "world", "n": 42}}


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
