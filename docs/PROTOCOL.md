# PRONOTE protocol notes

Everything UpNote knows about how PRONOTE's web protocol works, gathered by
cross-referencing `pronotepy`'s written spec, its source, the `Blocksnote`
source tree, and live testing against the official demo instance. Where the
sources disagree, this document says so.


All communication (after the initial HTML page) is JSON over HTTP(S), with
optional zlib compression and AES-CBC encryption of the `dataSec` field.

## 1. Instance / workspace discovery

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

## 2. Session creation

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
404. See [CHANGELOG](../CHANGELOG.md).

## 3. `FonctionParametres` - establishing the AES IV

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

## 4. Key/IV derivation - a detail both sources agree on

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

## 5. Login (`Identification` + `Authentification`)

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

### ⚠️ Challenge format changed on 2026-09-02 (PRONOTE >= 2026.2.5)

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

## 6. Response envelope

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
[CHANGELOG](../CHANGELOG.md)).

## 7. Compression - a real asymmetry between requests and responses

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

## 8. Typed value wrappers

Beyond login, PRONOTE wraps many response fields as
`{"_T": <type_code>, "V": <value>}` (numbers, dates, "number sets" like
grade scales) and uses `"L"`/`"N"` as short keys for `"label"`/`"id"` on a
lot of objects. `parsing.py` (ported from
`structures/parsing/{Parser,DateParser,NumberSet}.ts`) undoes both. Not
every type code is handled yet - see [Known limitations](../README.md#known-limitations).

## 9. Timetable (`PageEmploiDuTemps`)

First data endpoint, ported from `routes/PageEmploiDuTemps/*` in Blocksnote.

```
POST .../appelfonction/<a>/<h>/<no>
{ "id": "PageEmploiDuTemps",
  "dataSec": { "Signature": { "onglet": 16 },
               "data": { ...flags..., "numeroSemaine": 12, "ressource": {"G": 4, "N": "<id>"} } } }
```

- **Resource**: the user's own `(G, N)` pair, taken from the `ressource`
  field of `ParametresUtilisateur`. Note that response parsing renames `N`
  to `id`, so the request must rebuild `{"G": ..., "N": ...}` from it.
- **Dual-case keys**: `numeroSemaine`, `dateDebut`, `dateFin` and
  `ressource` are each sent twice, as `key` and `Key` (`NumeroSemaine`...).
- **Period**: either `numeroSemaine` (school-week number), or an explicit
  `dateDebut`/`dateFin` pair of type-7 dates, which win if both are given.
- **Date encoding**: `"D/M/YYYY H:M:S"` with no zero-padding
  (`2026-03-05 08:05:00` -> `"5/3/2026 8:5:0"`).
- **Signature**: `onglet` is 16 for students, parents and teachers, 60 for
  administrators and 171 for school life. Parent, accompanying and
  enterprise spaces also send `membre` (the resource whose timetable is read).
- **Response**: `ListeCours` is a list of courses. `DateDuCours` is a type-7
  date; `duree` is a number of time slots, converted to hours with
  `General.PlacesParHeure` from the `FonctionParametres` response. Details
  live in `ListeContenus`, a list of labelled entries keyed by kind code:
  `2` groups, `3` teachers, `16` subject, `17` rooms, `34` staff. A course
  with `estRetenue` set is a detention rather than a lesson.

Not ported yet: the `excluded` flag (Blocksnote derives it from the
`absences.joursCycle` exclusions, but its day-index expression has an
operator-precedence quirk, so it is left out until verified live).

## 10. ENT / CAS login

Schools whose PRONOTE sits behind an ENT (school portal) authenticate through
a CAS single sign-on instead of PRONOTE's own password check. Sources: the
`pronotepy` protocol notes and its `_login` code; Blocksnote only reads the CAS
info and always sends `pourENT: false`, so there is no second implementation
to cross-check against.

**Where to find out whether an instance uses a CAS**: `InfoMobileApp.json`
(see section 1) carries `CAS: {actif, casURL, jetonCAS}`. UpNote reads
`actif` and `casURL`; the purpose of `jetonCAS` is not documented anywhere
we found, so it is ignored.

**Flow**

1. Authenticate against the ENT/CAS and keep the cookies (single sign-on
   cookie, usually `TGC`). This step is ENT-specific.
2. `GET <root>/<workspace>.html` **with those cookies**, using the regular
   desktop page (not the `mobile.*` one) and a desktop User-Agent, which is
   what pronotepy does. PRONOTE bounces through the CAS, gets a ticket, and
   returns its page, whose `Start({...})` attributes now include two extra
   values, `e` and `f`. Without valid cookies it returns the CAS login page
   instead, so there is no `Start(` call to parse. (A direct login with
   `?login=true` is the opposite: it stops PRONOTE from redirecting to the ENT.)
3. `FonctionParametres` as usual.
4. `Identification` with `pourENT: true` and **`identifiant` set to `e`**.
5. The key material for the challenge is **`upper(hex(sha256(f)))`** - the
   hash of `f` alone: no username prefix and no `alea`, unlike the password
   login. The challenge itself is solved exactly as in section 5, including
   the 2026-09-02 single-block format.
6. `Authentification`, then decrypt `cle` with the same key material, as usual.

**What UpNote automates**: step 1 for ENTs whose login page is a plain CAS form
(`upnote.ent.cas_login`: GET `<cas>/login?service=...`, fill the form's
username/password fields, keep its hidden fields such as `execution`, POST
without following the redirect, treat a redirect as success and a returned
login form as failure). Everything else is a provider
(`upnote.ent.EntProvider`) or cookies you supply.

**Known gaps**

- ENTs that hand the login to EduConnect/SAML (a common setup), or that add a
  captcha or a second factor, are not covered by the generic CAS helper: they
  need a dedicated provider, or browser cookies passed to `login_ent(cookies=...)`.
- The `service` URL sent to the CAS defaults to the PRONOTE root
  (`https://host/pronote/`), which is what an existing ENT helper was seen
  targeting. A CAS that only accepts another service URL needs
  `cas_provider(..., service=...)`.
- Not verified against a live ENT. The official demo has no CAS
  (`CAS.actif` is false), so this flow is covered by offline tests that mirror
  pronotepy's behaviour, not by a real exchange.

