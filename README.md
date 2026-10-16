# UpNote

[![Tests](https://github.com/ChatNote-Hub/UpNote/actions/workflows/tests.yml/badge.svg)](https://github.com/ChatNote-Hub/UpNote/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

An unofficial Python client for [PRONOTE](https://www.index-education.com/fr/logiciel-gestion-vie-scolaire-college-lycee-pronote.php),
written from scratch by reverse engineering the protocol and cross-checking
two existing implementations ([`pronotepy`](https://github.com/bain3/pronotepy)
and [`Blocksnote`](https://github.com/BlocksHub/Blocksnote)).

> **Status: alpha.** Username/password login works end to end against the
> official demo instance (PRONOTE 2026.2.7), and so does the timetable
> endpoint. ENT / CAS login is implemented but could not be tested against a
> real ENT yet. See [Known limitations](#known-limitations).

## Features

| | |
|---|---|
| Instance discovery | list the workspaces (student, parent, teacher, ...) of an instance |
| Login | username/password, including the PRONOTE >= 2026.2.5 challenge change |
| ENT / CAS login | through a school portal: generic CAS form login, your own ENT helper, or browser cookies |
| Timetable | lessons and detentions, by school week or date range, grouped by day |
| Low-level access | `session.post(function, data)` for any other PRONOTE function |

## Installation

Not on PyPI yet. From source:

```bash
git clone https://github.com/ChatNote-Hub/UpNote.git
cd UpNote
pip install -e ".[dev]"      # or: pip install -e .   (runtime only)
```

## Quick start

```python
from datetime import datetime, timedelta

from upnote import NOTSpace, get_timetable, get_user, group_by_day, login

session = login(
    "https://demo.index-education.net/pronote/eleve.html",
    "demonstration",
    "pronotevs",
    workspace_type=NOTSpace.STUDENT,
)

user = get_user(session)
print(user.full_name)

start = datetime.now()
slots = get_timetable(session, user.resource, start=start, end=start + timedelta(days=7))

for day in group_by_day(slots):
    print(day.date)
    for slot in day.slots:
        print(f"  {slot.start:%H:%M}-{slot.end:%H:%M} {slot.subject}")
```

If your school logs in through an ENT (a school portal), use the direct URL of
the workspace page:

```python
from upnote import login_ent

# the instance advertises a plain CAS server: username and password are enough
session = login_ent("https://0000000a.index-education.net/pronote/eleve.html", "jdupont", "password")

# any other ENT (EduConnect, SAML, captcha...): reuse the cookies of a browser login
session = login_ent("https://0000000a.index-education.net/pronote/eleve.html",
                    cookies={"TGC": "..."})
```

Cookies are as sensitive as a password: never commit them. To support a specific
ENT, write an `EntProvider` (one function, see [`docs/PROTOCOL.md`](docs/PROTOCOL.md)).

Anything not wrapped yet is one call away:

```python
data = session.post("ParametresUtilisateur", {})
```

Every call can raise `upnote.UpNoteError`.

## Examples

| Script | Needs network | What it shows |
|---|---|---|
| [`crypto_walkthrough.py`](examples/crypto_walkthrough.py) | no | key/IV derivation and challenge solving, step by step |
| [`instance_discovery.py`](examples/instance_discovery.py) | yes | the workspaces available on an instance |
| [`basic_login.py`](examples/basic_login.py) | yes | a full login |
| [`custom_request.py`](examples/custom_request.py) | yes | login, then a raw `session.post(...)` |
| [`timetable.py`](examples/timetable.py) | yes | the current week's timetable, or a given week number |
| [`ent_login.py`](examples/ent_login.py) | yes, plus an ENT account | login through an ENT, with credentials or cookies |

## Documentation

- [`docs/PROTOCOL.md`](docs/PROTOCOL.md): how the PRONOTE protocol works,
  including the quirks that cost the most time to find.
- [`CHANGELOG.md`](CHANGELOG.md): what changed, newest first.

## Project layout

```
UpNote/
├── src/upnote/
│   ├── __init__.py      public API
│   ├── constants.py     fixed UUIDs, RSA key, NOTSpace enum
│   ├── crypto.py        AES / RSA, key and IV derivation, challenge solving
│   ├── parsing.py       typed values (_T/V, L/N, dates, number sets), both directions
│   ├── session.py       PronoteSession: HTTP, request/response encoding
│   ├── client.py        instance discovery, login, ENT login
│   ├── ent/             ENT / CAS helpers (EntProvider contract, generic CAS form login)
│   ├── user.py          the logged-in user and their resource
│   └── timetable.py     PageEmploiDuTemps
├── tests/               offline tests, one file per module
├── examples/            runnable scripts
├── docs/PROTOCOL.md
├── CHANGELOG.md
├── .github/workflows/tests.yml
├── pyproject.toml
└── LICENSE
```

One module per concern, and one module per PRONOTE function family: a new
endpoint (grades, homework, ...) is a new `src/upnote/<name>.py` plus
`tests/test_<name>.py`, with no change to the core.

## Running the tests

```bash
pip install -e ".[dev]"
pytest
```

The test files also run directly, without pytest: `python3 tests/test_crypto.py`.
All 58 tests are offline: HTTP is mocked.

## Known limitations

- **Timetable verified on the demo only, and only on cancelled lessons.**
  The demo returned a full week where every lesson is cancelled (status
  "Classe absente"), so the request, signature, dates and durations are
  confirmed live, but the non-cancelled lesson and detention paths are
  covered by offline tests only.
- **Encryption and compression are unverified live.** The demo instance has
  both turned off (`sCrA`/`sCoA` false), so only the plain-text path has met
  a real server. The encrypted/compressed paths are covered by mocked tests.
- **Only the student workspace has been exercised.** Parent, teacher and
  other spaces use code paths ported from Blocksnote but never run.
- **ENT / CAS login is not verified live.** The official demo has no CAS, so
  the flow is covered by offline tests that mirror pronotepy's behaviour, not by
  a real exchange. Please try it on your school's ENT and report what happens.
  The generic CAS helper only handles plain CAS login forms; ENTs that go
  through EduConnect/SAML, a captcha or a second factor need a dedicated
  provider or browser cookies (see [`docs/PROTOCOL.md`](docs/PROTOCOL.md)).
- **Login modes:** username/password and ENT only (no QR code or app-token
  login). The `modeCompLog`/`modeCompMdp` flags are ignored, as in Blocksnote.
- **2026 challenge detection** ("exactly one AES block") rests on one
  confirmed real-world fix. If login fails with a padding error on some
  instance, start there. Details in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).
- **Parsing:** unknown typed-value codes pass through unchanged instead of
  raising.

## Contributing

Issues and PRs are welcome. When adding an endpoint:

1. Cross-check `pronotepy` and `Blocksnote` where possible. Relying on a
   single implementation is how several early bugs slipped through.
2. Add an offline test for the request and response shape (see
   `tests/test_timetable.py` for the pattern).
3. Write protocol quirks down in `docs/PROTOCOL.md`, not only in code
   comments, and add a line to `CHANGELOG.md`.

## Legal note

UpNote only implements what is needed to interoperate with a service you
already have legitimate credentials for (interoperability, in the spirit of
French IP code article L.122-6-1). It is not meant to bypass access controls
or reach data you are not authorized to see.
