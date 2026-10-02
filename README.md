# UpNote

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)

An unofficial, from-scratch Python client for the [PRONOTE](https://www.index-education.com/fr/logiciel-gestion-vie-scolaire-college-lycee-pronote.php)
protocol, built by reverse engineering PRONOTE alongside two existing
implementations, and validated with unit tests where possible.

> **Status: alpha.** Login (username/password) works end-to-end against the
> official demo instance. Data-fetching endpoints (grades, timetable,
> homework, ...) are not implemented yet. See [Known limitations](#known-limitations).

## Table of contents

- [Why this exists](#why-this-exists)
- [Installation](#installation)
- [Usage](#usage)
- [Examples](#examples)
- [Protocol overview](#protocol-overview)
- [Project layout](#project-layout)
- [Running the tests](#running-the-tests)
- [Known limitations](#known-limitations)
- [Changelog](#changelog)
- [Contributing](#contributing)
- [Legal note](#legal-note)

## Why this exists

PRONOTE (by Index-Education) doesn't publish a public API for student/parent
accounts. Several community projects have reverse-engineered its web
protocol over the years:

- [`pronotepy`](https://github.com/bain3/pronotepy) (Python, in maintenance
  mode) - has a
  [written protocol description](https://github.com/bain3/pronotepy/blob/master/PRONOTE%20protocol.md)
- [`Blocksnote`](https://github.com/BlocksHub/Blocksnote) (TypeScript,
  actively developed) - no written docs yet, but a clean, readable,
  actively-maintained source tree

UpNote cross-references both (protocol doc + two independent source trees)
to build a Python implementation and to catch inconsistencies between
what's documented and what the code actually does. Several real
discrepancies were found this way - see [Changelog](#changelog).

## Installation

Not published to PyPI yet. Install from source, editable, with the `dev`
extras (pytest/mypy/ruff):

```bash
git clone https://github.com/ChatNote-Hub/UpNote.git
cd UpNote
pip install -e ".[dev]"
```

Runtime dependencies only (`requests`, `cryptography`):

```bash
pip install -e .
```

## Usage

```python
from upnote import login, NOTSpace

session = login(
    "https://demo.index-education.net/pronote/eleve.html",
    "demonstration",
    "pronotevs",
    workspace_type=NOTSpace.STUDENT,
)

# session.aes now holds the final, authenticated session key.
# session.post(function_name, data) can be used for further requests:
data = session.post("ParametresUtilisateur", {})
```

## Examples

```bash
# No network needed - safe to run anywhere, demonstrates the crypto layer in isolation
python3 examples/crypto_walkthrough.py

# Needs network - lists available workspaces on an instance
python3 examples/instance_discovery.py https://demo.index-education.net/pronote/eleve.html

# Needs network - full login against the demo instance
python3 examples/basic_login.py

# Needs network - login + one authenticated request
python3 examples/custom_request.py
```

`crypto_walkthrough.py` has no external dependencies beyond this package
and runs fully offline; the other three perform real HTTP requests.

## Protocol overview

All communication (after the initial HTML page) is JSON over HTTP(S), with
optional zlib compression and AES-CBC encryption of the `dataSec` field.

### 1. Instance / workspace discovery

Two approaches exist:

- **pronotepy's approach**: `GET <root>/eleve.html` (or `parent.html`,
  etc.) directly, and parse the returned HTML.
- **Blocksnote's approach** (cleaner, undocumented in pronotepy):
  `GET <root>InfoMobileApp.json?id=<INFO_MOBILE_ID>` returns a JSON list of
  available workspaces (`espaces`) and whether a CAS/ENT is configured,
  without any HTML parsing. `INFO_MOBILE_ID` is a fixed UUID hard-coded in
  the mobile app / eleve.js.

UpNote uses the `InfoMobileApp.json` approach (see `client.py`,
`Instance.create_from_url`).

### 2. Session creation

```
GET <root><workspace_url>?fd=1&bydlg=<BYPASS_ID>
```

`BYPASS_ID` is another fixed UUID (seen only in Blocksnote's source, not in
pronotepy's docs) - likely skips a "your browser/app version is outdated"
interstitial.

A successful response is HTML with a `<body onload="Start({...})">`
attribute:

```html
<body onload="try { Start ({h:'2052117',sCrA:true,sCoA:true,a:6,d:true}) } catch (e) { ... }">
```

- `h` - session id
- `sCrA` - whether requests should be **encrypted** (`true`/`false`)
- `sCoA` - whether requests should be **compressed** (`true`/`false`)
- `a` - workspace type id (matches `NOTSpace` in `constants.py`)
- `d` - present and `true` on the demo instance

**Real bug found here**: `InfoMobileApp.json` returns workspace URLs
*without* a leading slash (e.g. `"mobile.eleve.html"`, not
`"/mobile.eleve.html"`). Joining it naively with the instance root (itself
stripped of its trailing slash) silently produced a malformed URL and a
404. See [Changelog](#changelog).

### 3. `FonctionParametres` - establishing the AES IV

```
POST <root>appelfonction/<a>/<h>/<no>
{
  "session": <h>,
  "no": "<AES-encrypted request number, hex>",
  "id": "FonctionParametres",
  "dataSec": { "data": { "Uuid": "<new iv>", "identifiantNav": null } }
}
```

- The request number (`no`) starts at 1 and is AES-encrypted with the
  **default** key/iv (empty key material, empty iv material -> see below).
  A known-good sanity check value: encrypting `"1"` with the default
  key/iv must yield `3fa959b13967e0ef176069e01e23c8d7`. It must be
  incremented by 2 for every subsequent request (responses count too).
- `Uuid` is a fresh, random 16-byte IV:
  - over **HTTPS**: sent as raw base64 (`b64encode(raw_iv)`)
  - over plain **HTTP**: RSA-PKCS1v1.5-encrypted with a hard-coded 1024-bit
    public key (same modulus/exponent found in both pronotepy, 2023, and
    Blocksnote, 2026 - just represented in different bases, decimal vs hex;
    it has not rotated in three years)
- **Timing matters**: the request is built and encrypted with the *old*
  iv, then the session iv is updated to the new one, and the *response* is
  decrypted with the *new* iv. This is the only request where the iv used
  to build vs. decrypt differs.

### 4. Key/IV derivation - a detail both sources agree on

Neither the raw AES key material nor the raw IV material is ever used
directly. Both are always passed through MD5 first:

```
used_key = MD5(key_material)
used_iv  = MD5(iv_material) if iv_material else 16 zero bytes
```

With empty key/iv material (the initial state), this correctly produces:

- `used_key = MD5(b"") = d41d8cd98f00b204e9800998ecf8427e`
- `used_iv  = 16 zero bytes`

This is implemented as `AESSession` in `crypto.py`.

### 5. Login (`Identification` + `Authentification`)

```
POST .../Identification
{ "identifiant": "<username>", "genreEspace": <a>, "genreConnexion": 0,
  "pourENT": false, "demandeConnexionAppliMobile": false, ... }
```

Response:

```json
{ "alea": "<seed>", "challenge": "<hex-encoded AES ciphertext>", "modeCompMdp": 0, "modeCompLog": 0 }
```

`tempKey = lower(username) + upper(hex(sha256(alea + password.strip())))`,
used as the session AES key material (i.e. used key = `MD5(tempKey)`), for
the rest of this step. How the `challenge` itself gets solved then depends
on which protocol version the server speaks - see the next section.

#### ⚠️ Challenge format changed on 2026-09-02 (PRONOTE >= 2026.2.5)

Until September 2, 2026, PRONOTE instances sent the challenge as real AES
ciphertext, solved like this:

1. Decrypt `challenge` (hex) with the current session key/iv
2. Keep every other character of the decrypted text (`"abcdefg" ->
   "aceg"`) - this discards "alea" noise interleaved into the plaintext
3. Re-encrypt that shortened text with the same key/iv, hex-encode it -
   this is the `challenge` solution

**Since 2026-09-02, PRONOTE >= 2026.2.5 no longer encrypts the challenge at
all.** It sends a single raw 16-byte block (exactly one AES block, with
nothing interleaved to strip) and expects the client to directly
AES-encrypt the **uppercase hex string of that block** - no decrypt, no
stripping step. This matches the official PRONOTE 2026 client JS
(`getNouveauChallenge()`), which only ever encrypts the received string,
never decrypts it.

Every client built against the old behavior (`pronotepy` included - see
[#346](https://github.com/bain3/pronotepy/issues/346) and
[#348](https://github.com/bain3/pronotepy/issues/348)) fails on affected
instances with an AES padding error, because it tries to decrypt 16 bytes
that were never ciphertext to begin with. The `alea` field is also
typically absent from the `Identification` response on these instances.

**Detection**: `UpNote` checks whether the hex-decoded challenge is
exactly 16 bytes (one AES block). A legacy ciphertext is essentially never
exactly one block (it carries the original interleaved-with-alea text,
which runs longer), so block-length is a reliable signal - more reliable
than "try to decrypt, see if the padding looks valid", since a wrong key
still produces valid-looking PKCS7 padding by chance about 1 time in 256.
See `solve_challenge_session` in `crypto.py`.

```
POST .../Authentification
{ "challenge": "<solution>", "connexion": 0, "espace": <a> }
```

Response contains `cle` (hex, AES-encrypted with the *tempKey*-derived
key): decrypting it yields a comma-separated list of byte values
(`"10,2,159,..."`). Converting those to raw bytes and using **that** as
the new key material (i.e. final used key = `MD5(bytes([10, 2, 159, ...]))`)
gives the session's real, ongoing AES key. From this point on, the
session is authenticated.

> **Note on `modeCompLog`/`modeCompMdp`**: pronotepy's written protocol doc
> says these two flags (returned in the `Identification` response) should
> conditionally control whether the username/password get lowercased
> before computing the challenge. Blocksnote's actual source code ignores
> these flags entirely and *always* lowercases the username and strips the
> password. UpNote follows Blocksnote's (simpler, and it's the
> actively-maintained implementation) behavior. This is a candidate spot
> for a bug if login fails against non-demo instances with mixed-case
> credentials.

### 6. Response envelope

Every decrypted/decompressed response body - regardless of whether
encryption/compression are on - is shaped like:

```json
{ "data": { /* the actual useful fields */ }, "_Signature_": { /* ... */ } }
```

mirroring the `{Signature, data}` shape sent in every outgoing request.
`PronoteSession._process_response` unwraps this and returns `data`
directly - so e.g. the `Identification` response's `challenge` and `alea`
fields are accessed as `data["challenge"]`, not
`data["data"]["challenge"]`. Missing this unwrap step was a real bug (see
[Changelog](#changelog)).

### 7. Compression - a real asymmetry between requests and responses

Confirmed identically in both `pronotepy` and `Blocksnote`'s source code,
this is subtle enough to be worth calling out explicitly:

**Outgoing request compression** does *not* compress the raw UTF-8 bytes
of the JSON payload. It compresses the **hex string representation** of
those bytes:

```
json_bytes = utf8(json.dumps(payload))
hex_string = json_bytes.hex()              # <- extra detour
compressed = raw_deflate(utf8(hex_string), level=6)
```

**Incoming response decompression** does *not* do this detour - inflating
a response's `dataSec` yields the JSON's UTF-8 bytes directly:

```
json_bytes = raw_inflate(response_bytes)
payload = json.loads(json_bytes.decode())  # no hex step
```

If you implement only one side by analogy with the other, requests to the
server will fail to parse (or worse, silently misparse) - the two
directions are genuinely not mirror images of each other.

### 8. Typed value wrappers

Beyond login, PRONOTE wraps many response fields as
`{"_T": <type_code>, "V": <value>}` (numbers, dates, "number sets" like
grade scales) and uses `"L"`/`"N"` as short keys for `"label"`/`"id"` on a
lot of objects. `parsing.py` (ported from
`structures/parsing/{Parser,DateParser,NumberSet}.ts`) undoes both. Not
every type code is handled yet - see [Known limitations](#known-limitations).

## Project layout

```
UpNote/
├── src/
│   └── upnote/
│       ├── __init__.py     - public API (login, NOTSpace, UpNoteError, ...)
│       ├── constants.py    - fixed UUIDs, RSA key, NOTSpace enum
│       ├── crypto.py       - AES/RSA primitives, key/iv derivation, challenge solving
│       ├── parsing.py      - typed-value unwrapping (_T/V, L/N, dates, number sets)
│       ├── session.py      - PronoteSession: HTTP layer, request/response encoding
│       └── client.py       - Instance discovery + full login flow
├── tests/
│   ├── test_crypto.py      - crypto primitives, incl. the numeroOrdre sanity check
│   ├── test_session.py     - request/response encoding, mocked HTTP (no network)
│   └── test_parsing.py     - typed-value parser
├── examples/
│   ├── crypto_walkthrough.py  - crypto layer only, no network needed
│   ├── instance_discovery.py  - list the workspaces available on an instance
│   ├── basic_login.py         - full username/password login
│   └── custom_request.py      - login, then one appelfonction call
├── .github/workflows/tests.yml
├── pyproject.toml
├── LICENSE
└── README.md
```

A `src/` layout is used deliberately: it prevents accidentally importing
the package from the repo root instead of the installed copy, which is the
standard, scalable convention for a Python package meant to grow (more
routes/, more parsing types, eventually published to PyPI).

## Running the tests

```bash
pip install -e ".[dev]"
pytest -v
```

The test files are also runnable directly without pytest (no test
framework dependency required):

```bash
python3 tests/test_crypto.py
python3 tests/test_session.py
python3 tests/test_parsing.py
```

23/23 tests currently pass.

## Known limitations

- Only username/password login is implemented (no QR code login, no ENT
  login, no mobile app token login).
- Only `FonctionParametres` / `Identification` / `Authentification` are
  implemented - no actual data-fetching endpoints yet (timetable, grades,
  homework, etc.).
- `parsing.py`'s typed-value handling covers the type codes seen so far
  (numbers, dates, number sets) but is not exhaustive; unknown type codes
  are passed through as-is rather than raised, which is safe but may hide
  a field that needs real parsing once data endpoints are implemented.
- The `modeCompLog`/`modeCompMdp` handling described above is a known
  simplification.
- The single-AES-block detection for the 2026-09-02 challenge format
  change is based on one confirmed real-world fix (see Changelog) rather
  than UpNote's own testing against multiple live instances. It's possible
  some PRONOTE versions/configurations need a slightly different signal
  than "exactly 16 bytes" - if login fails with a padding error on a
  specific instance, that's the first place to look.

## Changelog

- **Fixed** (real server behavior change, not a bug in this project's
  original design): since 2026-09-02, PRONOTE >= 2026.2.5 no longer
  encrypts the `Identification` challenge - it sends one raw AES block
  that must be directly re-encrypted, not decrypted-then-stripped. Without
  this fix, login fails with an AES padding error on any affected instance
  (this also breaks `pronotepy` upstream - see
  [#346](https://github.com/bain3/pronotepy/issues/346) /
  [#348](https://github.com/bain3/pronotepy/issues/348)). `UpNote` now
  auto-detects the challenge format by its decoded length and handles
  both. See [the dedicated section above](#️-challenge-format-changed-on-2026-09-02-pronote--20262-5)
  for the full story, and the Known limitations entry below for what this
  doesn't cover yet.
- **Fixed**: `InfoMobileApp.json` returns workspace URLs *without* a
  leading slash (e.g. `"mobile.eleve.html"`, not `"/mobile.eleve.html"`) -
  a real, mobile-specific HTML page, different from the desktop
  `eleve.html`. Combined with `PronoteSession` stripping the instance
  root's trailing slash, naive string concatenation produced a malformed
  URL (`.../pronotemobile.eleve.html`, missing the separator) and a 404.
  Fixed in `PronoteSession.create` by normalizing both sides before
  joining; locked in by a regression test in `test_session.py`.
- **Fixed**: every decrypted response body is an envelope shaped like
  `{"data": {...}, "_Signature_": ...}` (mirroring the `{Signature, data}`
  shape sent in requests) - the useful fields (e.g. `challenge`, `alea`)
  are one level deeper than what `_process_response` used to return,
  causing `KeyError: 'challenge'` on `Identification` even though the
  request/response cycle otherwise worked. Fixed by unwrapping `.data`,
  and added a proper `parsing.py` module (ported from
  `structures/parsing/{Parser,DateParser,NumberSet}.ts`) for typed-value
  wrappers, ahead of implementing real data endpoints.
- Renamed the project from `pronote-wrapper` to **UpNote**, moved to a
  `src/` layout, added `pyproject.toml` packaging and a CI workflow.

## Contributing

Issues and PRs are welcome. If you're adding a new PRONOTE endpoint:

1. Cross-reference both `pronotepy` and `Blocksnote`'s source where
   possible - relying on a single implementation is how the two bugs above
   slipped through.
2. Add a unit test. If the endpoint needs real network access to verify,
   still add an offline test for the request/response shape (see
   `test_session.py` for the pattern used throughout this project - manual
   HTTP mocking, no external test-framework dependency required).
3. Document any protocol quirk you find in the README, not just in code
   comments - the [Protocol overview](#protocol-overview) section exists
   specifically to save the next person from re-discovering the same
   thing.

## Legal note

UpNote only implements what's needed to interoperate with a service you
already have legitimate credentials for (interoperability, in the spirit
of French IP code Article L.122-6-1) - not to bypass access controls or
access data you're not authorized to see.
