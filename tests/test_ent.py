"""Offline tests for ENT / CAS login (no network, no pytest needed)."""
import hashlib
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests

from upnote import client, crypto
from upnote.ent import EntLoginError, cas
from upnote.session import PronoteError, PronoteSession, Workspace

CAS5_PAGE = """
<html><body>
<form id="fm1" method="post" action="/cas/login?service=x">
  <input type="text" name="username" id="username"/>
  <input type="password" name="password"/>
  <input type="hidden" name="execution" value="e1s1"/>
  <input type="hidden" name="_eventId" value="submit"/>
  <input type="submit" name="submit" value="LOGIN"/>
</form>
</body></html>
"""

CAS3_PAGE = """
<form action="/forgot" method="post"><input type="email" name="mail"/></form>
<form action="login" method="post">
  <input name="username"/><input type="password" name="password"/>
  <input type="hidden" name="lt" value="LT-123"/>
  <input type="hidden" name="execution" value="e2s1"/>
</form>
"""


@contextmanager
def _patched(**methods):
    originals = {name: getattr(requests.Session, name) for name in methods}
    for name, fn in methods.items():
        setattr(requests.Session, name, fn)
    try:
        yield
    finally:
        for name, fn in originals.items():
            setattr(requests.Session, name, fn)


def _response(text="", status=200, headers=None, url="https://cas.example.fr/cas/login"):
    r = MagicMock()
    r.text, r.status_code, r.headers, r.url = text, status, headers or {}, url
    r.raise_for_status = MagicMock()
    return r


# --- form parsing ------------------------------------------------------------

def test_login_form_is_found_and_submission_built():
    form = cas._login_form(CAS5_PAGE)
    data = cas._build_submission(form, "jdupont", "s3cret")

    assert data == {"username": "jdupont", "password": "s3cret", "execution": "e1s1", "_eventId": "submit"}


def test_login_form_skips_forms_without_password_and_keeps_lt():
    form = cas._login_form(CAS3_PAGE)
    data = cas._build_submission(form, "u", "p")

    assert form.action == "login"
    assert data["lt"] == "LT-123" and data["execution"] == "e2s1"
    assert data["_eventId"] == "submit"  # added: execution present, event id missing
    assert "mail" not in data


def test_no_login_form_returns_none():
    assert cas._login_form("<html><form><input name='q'/></form></html>") is None


# --- cas_login ---------------------------------------------------------------

def test_cas_login_success_posts_form_without_following_redirect():
    seen = {}

    def fake_get(self, url, params=None, **kw):
        seen["get"] = (url, params)
        return _response(CAS5_PAGE)

    def fake_post(self, url, data=None, allow_redirects=True, **kw):
        seen["post"] = (url, data, allow_redirects)
        self.cookies.set("TGC", "ticket-granting")
        return _response(status=302, headers={"Location": "https://h/pronote/?ticket=ST-1"})

    with _patched(get=fake_get, post=fake_post):
        jar = cas.cas_login("https://cas.example.fr", "jdupont", "pw", service="https://h/pronote/")

    assert seen["get"] == ("https://cas.example.fr/login", {"service": "https://h/pronote/"})
    assert seen["post"][0] == "https://cas.example.fr/cas/login?service=x"
    assert seen["post"][1]["username"] == "jdupont" and seen["post"][1]["password"] == "pw"
    assert seen["post"][2] is False
    assert jar.get("TGC") == "ticket-granting"


def test_cas_login_keeps_existing_login_path():
    urls = []

    def fake_get(self, url, params=None, **kw):
        urls.append(url)
        return _response("<html></html>")

    with _patched(get=fake_get):
        for base in ("https://ent.example.fr/cas", "https://ent.example.fr/cas/login/"):
            try:
                cas.cas_login(base, "u", "p", service="s")
            except EntLoginError:
                pass

    assert urls == ["https://ent.example.fr/cas/login", "https://ent.example.fr/cas/login"]


def test_cas_login_rejected_credentials_raise():
    with _patched(
        get=lambda self, url, params=None, **kw: _response(CAS5_PAGE),
        post=lambda self, url, data=None, **kw: _response(CAS5_PAGE, status=200),
    ):
        try:
            cas.cas_login("https://cas.example.fr", "u", "bad", service="s")
        except EntLoginError as exc:
            assert "rejected" in str(exc)
            return
    raise AssertionError("expected EntLoginError")


def test_cas_login_without_form_explains_alternatives():
    with _patched(get=lambda self, url, params=None, **kw: _response("<html>EduConnect</html>")):
        try:
            cas.cas_login("https://cas.example.fr", "u", "p", service="s")
        except EntLoginError as exc:
            assert "cookies" in str(exc)
            return
    raise AssertionError("expected EntLoginError")


def test_cas_provider_defaults_service_to_pronote_root():
    captured = {}
    original = cas.cas_login
    cas.cas_login = lambda cas_url, u, p, *, service, **kw: captured.update(cas_url=cas_url, service=service) or "jar"
    try:
        jar = cas.cas_provider("https://cas.example.fr")("u", "p", pronote_url="https://h/pronote/eleve.html")
    finally:
        cas.cas_login = original

    assert jar == "jar"
    assert captured == {"cas_url": "https://cas.example.fr", "service": "https://h/pronote/"}


# --- URL / workspace helpers ---------------------------------------------------

def test_split_page_url_drops_query_and_keeps_case():
    assert client._split_page_url("https://0000000A.index-education.net/pronote/eleve.html?login=true") == (
        "https://0000000A.index-education.net/pronote",
        "eleve.html",
        "https://0000000A.index-education.net/pronote/eleve.html",
    )
    assert client._split_page_url("https://h/my/path/parent.html")[0] == "https://h/my/path"


def test_split_page_url_rejects_root():
    for bad in ("https://h/pronote/", "https://h/pronote", "not a url"):
        try:
            client._split_page_url(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_workspace_type_from_page_name():
    assert client._workspace_type_from_page("eleve.html") == 6
    assert client._workspace_type_from_page("mobile.parent.html") == 7
    assert client._workspace_type_from_page("professeur.html") == 8
    assert client._workspace_type_from_page("unknown.html") is None


# --- crypto --------------------------------------------------------------------

def test_generate_ent_key_is_uppercase_sha256_of_f_only():
    assert crypto.generate_ent_key("tok") == hashlib.sha256(b"tok").hexdigest().upper()


def test_solve_challenge_with_ent_key_both_formats():
    key = crypto.generate_ent_key("tok")

    def server(iv=b"iv-material"):
        aes = crypto.AESSession()
        aes.set_iv(iv)
        aes.set_key(key.encode())
        return aes

    # current format: one raw block, re-encrypted directly
    block_hex = bytes(range(16)).hex()
    out = crypto.solve_challenge_with_key(_with_iv(b"iv-material"), block_hex, key)
    assert out == server().encrypt_hex(block_hex.upper())

    # legacy format: real ciphertext, decrypt then drop every other char
    legacy_hex = server().encrypt_hex("aXbXcXdXeXfXgXhXiXjX")
    out = crypto.solve_challenge_with_key(_with_iv(b"iv-material"), legacy_hex, key)
    assert server().decrypt_hex(out).decode() == "abcdefghij"


def _with_iv(material):
    aes = crypto.AESSession()
    aes.set_iv(material)
    return aes


# --- PronoteSession.create for ENT ---------------------------------------------

def test_session_create_desktop_page_with_cookies():
    seen = {}

    def fake_get(self, url, **kw):
        seen["url"] = url
        seen["ua"] = self.headers["User-Agent"]
        seen["cookie"] = self.cookies.get("TGC")
        return _response("<body onload=\"Start ({h:'7',sCrA:false,sCoA:false,a:6,e:'E1',f:'F1'})\">")

    ws = Workspace(delegated=False, url="eleve.html", name="eleve.html", type=6)
    with _patched(get=fake_get):
        session = PronoteSession.create("https://h/pronote", ws, mobile=False, cookies={"TGC": "abc"})

    assert seen["url"] == "https://h/pronote/eleve.html"  # no mobile query string
    assert "Firefox" in seen["ua"] and seen["cookie"] == "abc"
    assert session.attributes["e"] == "E1" and session.attributes["f"] == "F1"


def test_session_create_hints_at_expired_ent_cookies():
    ws = Workspace(delegated=False, url="eleve.html", name="eleve.html", type=6)
    with _patched(get=lambda self, url, **kw: _response("<html>CAS login</html>")):
        try:
            PronoteSession.create("https://h/pronote", ws, mobile=False, cookies={"TGC": "old"})
        except PronoteError as exc:
            assert "ENT" in str(exc)
            return
    raise AssertionError("expected PronoteError")


# --- login_ent end to end ------------------------------------------------------

FIXED_IV = bytes(range(100, 116))
ENT_PAGE = "<body onload=\"Start ({h:'42',sCrA:false,sCoA:false,a:6,e:'ENTUSER',f:'ENTTOKEN'})\">"


def _fake_pronote_server(record, page=ENT_PAGE):
    """A PRONOTE stand-in: serves the ENT page, then FonctionParametres / Identification / Authentification."""
    challenge_hex = bytes(range(16)).hex()
    final_key = list(range(1, 17))

    def server_aes():
        aes = crypto.AESSession()
        aes.set_iv(FIXED_IV)
        # Computed independently of the code under test, so a wrong derivation is caught.
        aes.set_key(hashlib.sha256(b"ENTTOKEN").hexdigest().upper().encode())
        return aes

    def fake_get(self, url, **kw):
        record["page"] = (url, self.headers["User-Agent"], self.cookies.get("TGC"))
        return _response(page)

    def fake_post(self, url, json=None, **kw):
        name, data = json["id"], json["dataSec"]["data"]
        record.setdefault("calls", []).append((name, data))
        if name == "FonctionParametres":
            body = {"General": {"PlacesParHeure": 2}}
        elif name == "Identification":
            body = {"challenge": challenge_hex}
        elif name == "Authentification":
            record["challenge_ok"] = data["challenge"] == server_aes().encrypt_hex(challenge_hex.upper())
            body = {"cle": server_aes().encrypt_hex(",".join(map(str, final_key)))}
        else:
            raise AssertionError(f"unexpected call {name}")
        return _response_json({"dataSec": {"data": body, "_Signature_": {}}})

    return fake_get, fake_post, final_key


def _response_json(body):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=body)
    return r


def test_login_ent_full_flow_with_cookies():
    record = {}
    fake_get, fake_post, final_key = _fake_pronote_server(record)
    client.os = types.SimpleNamespace(urandom=lambda n: FIXED_IV)
    try:
        with _patched(get=fake_get, post=fake_post):
            session = client.login_ent("https://h/pronote/eleve.html?login=true", cookies={"TGC": "abc"})
    finally:
        import os

        client.os = os

    assert record["page"] == ("https://h/pronote/eleve.html", constants_desktop_ua(), "abc")
    names = [name for name, _ in record["calls"]]
    assert names == ["FonctionParametres", "Identification", "Authentification"]

    identification = dict(record["calls"])["Identification"]
    assert identification["identifiant"] == "ENTUSER" and identification["pourENT"] is True
    assert identification["genreEspace"] == 6

    assert record["challenge_ok"] is True
    assert session.aes.key == crypto.md5(bytes(final_key))
    assert session.settings["General"]["PlacesParHeure"] == 2
    assert session.mobile is False


def constants_desktop_ua():
    from upnote import constants

    return constants.DESKTOP_USER_AGENT


def test_login_ent_with_provider_receives_clean_page_url():
    record, calls = {}, {}
    fake_get, fake_post, _ = _fake_pronote_server(record)

    def provider(username, password, *, pronote_url):
        calls.update(username=username, password=password, pronote_url=pronote_url)
        return {"TGC": "from-provider"}

    client.os = types.SimpleNamespace(urandom=lambda n: FIXED_IV)
    try:
        with _patched(get=fake_get, post=fake_post):
            client.login_ent("https://h/pronote/eleve.html?login=true", "jdupont", "pw", ent=provider)
    finally:
        import os

        client.os = os

    assert calls == {"username": "jdupont", "password": "pw", "pronote_url": "https://h/pronote/eleve.html"}
    assert record["page"][2] == "from-provider"


def test_login_ent_without_e_and_f_explains():
    record = {}
    fake_get, fake_post, _ = _fake_pronote_server(
        record, page="<body onload=\"Start ({h:'42',sCrA:false,sCoA:false,a:6})\">"
    )
    with _patched(get=fake_get, post=fake_post):
        try:
            client.login_ent("https://h/pronote/eleve.html", cookies={"TGC": "x"})
        except PronoteError as exc:
            assert "'e' and 'f'" in str(exc)
            return
    raise AssertionError("expected PronoteError")


def test_login_ent_argument_validation():
    cases = [
        dict(url="https://h/pronote/eleve.html", cookies={"a": "b"}, ent=lambda *a, **k: {}),  # both
        dict(url="https://h/pronote/eleve.html"),  # no credentials, no cookies
        dict(url="https://h/pronote/unknown.html", cookies={"a": "b"}),  # unknown workspace
        dict(url="https://h/pronote/", cookies={"a": "b"}),  # not a page
    ]
    for kwargs in cases:
        try:
            client.login_ent(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")


def test_login_ent_without_cas_or_provider_raises():
    original = requests.get
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"espaces": [], "version": [2026, 2, 7], "CAS": {"actif": False}})
    requests.get = lambda *a, **k: resp
    try:
        client.login_ent("https://h/pronote/eleve.html", "u", "p")
    except PronoteError as exc:
        assert "CAS" in str(exc)
        return
    finally:
        requests.get = original
    raise AssertionError("expected PronoteError")


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
