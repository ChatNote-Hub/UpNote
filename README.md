# pronote-wrapper (Python)

A from-scratch Python client for the PRONOTE protocol, built by reverse
engineering PRONOTE alongside two existing implementations, and validated
with unit tests where possible.

> **Status: work in progress.** The crypto layer and request-building logic
> are unit-tested and internally consistent, but **have not yet been
> exercised against a live PRONOTE server** (this was built in a sandboxed
> environment with no network access - see [Known limitations](#known-limitations)).

## Why this exists

PRONOTE (by Index-Education) doesn't publish a public API for student/parent
accounts. Several community projects have reverse-engineered its web
protocol over the years:

- [`pronotepy`](https://github.com/bain3/pronotepy) (Python, in maintenance mode) - has a
  [written protocol description](https://github.com/bain3/pronotepy/blob/master/PRONOTE%20protocol.md)
- [`Blocksnote`](https://github.com/BlocksHub/Blocksnote) (TypeScript, actively developed) - no
  written docs yet, but a clean, readable, actively-maintained source tree

This project cross-references both (protocol doc + two independent source
trees) to build a Python implementation and to catch inconsistencies
between what's documented and what the code actually does.

## Sources referenced

- `PRONOTE protocol.md` from `bain3/pronotepy` (written spec, may be
  slightly stale - see discrepancies below)
- `pronotepy/pronoteAPI.py` (actual Python implementation, pycryptodome-based)
- `BlocksHub/Blocksnote` source tree (TypeScript, `@noble/*` crypto libs),
  provided directly by the project owner as a zip export
- Demo instance: `https://demo.index-education.net/pronote/` (username
  `demonstration`, password `pronotevs`)

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

This project uses the `InfoMobileApp.json` approach (see `client.py`,
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

Solving the challenge (`Challenge.solve` in Blocksnote /
`_Communication.after_auth` + challenge logic in pronotepy):

1. `tempKey = lower(username) + upper(hex(sha256(alea + password.strip())))`
2. Set the session AES key material to `tempKey` (i.e. used key =
   `MD5(tempKey)`)
3. Decrypt `challenge` (hex) with the current session key/iv
4. Keep every other character of the decrypted text (`"abcdefg" ->
   "aceg"`)
5. Re-encrypt that shortened text with the same key/iv, hex-encode it -
   this is the `challenge` solution

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
> password. This implementation follows Blocksnote's (simpler, and it's
> the actively-maintained implementation) behavior. This is a candidate
> spot for a bug if login fails against non-demo instances with mixed-case
> credentials.

### 6. Compression - a real asymmetry between requests and responses

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

## Project layout

```
pronote_wrapper/
  __init__.py
  constants.py    - fixed UUIDs, RSA key, NOTSpace enum
  crypto.py       - AES/RSA primitives, key/iv derivation, challenge solving
  session.py      - PronoteSession: HTTP layer, request/response encoding
  client.py       - Instance discovery + full login flow
tests/
  test_crypto.py  - crypto primitives, incl. the numeroOrdre sanity check
  test_session.py - request/response encoding, mocked HTTP (no network)
```

## Usage

```python
from pronote_wrapper import client, constants

session = client.login(
    "https://demo.index-education.net/pronote/eleve.html",
    "demonstration",
    "pronotevs",
    workspace_type=constants.NOTSpace.STUDENT,
)

# session.aes now holds the final, authenticated session key.
# session.post(function_name, data) can be used for further requests,
# e.g. session.post("ParametresUtilisateur", {})
```

## Running the tests

No test framework dependency required (pytest wasn't installable in the
sandbox this was built in - no network access - so the test files are
runnable directly):

```bash
python3 tests/test_crypto.py
python3 tests/test_session.py
```

13/13 tests currently pass.

## Known limitations

- **Never tested against a live server.** This was built entirely in a
  network-isolated sandbox. The crypto primitives are validated against a
  known-good sanity-check value from the protocol doc, and the
  request/response encoding logic is validated by mocking HTTP calls - but
  nothing here has actually round-tripped through the real
  `demo.index-education.net` server yet. Treat `client.login(...)` as
  untested until someone runs it for real.
- Only username/password login is implemented (no QR code login, no ENT
  login, no mobile app token login).
- Only `FonctionParametres` / `Identification` / `Authentification` are
  implemented - no actual data-fetching endpoints yet (timetable, grades,
  homework, etc.).
- The `modeCompLog`/`modeCompMdp` handling described above is a known
  simplification.

## Legal note

This project only implements what's needed to interoperate with a service
you already have legitimate credentials for (interoperability, in the
spirit of French IP code Article L.122-6-1) - not to bypass access
controls or access data you're not authorized to see.
