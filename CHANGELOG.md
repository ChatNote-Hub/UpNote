# Changelog

All notable changes to UpNote. Newest first.

## [0.3.0]

- **Added** ENT / CAS login: `login_ent(url, username, password)` for
  instances that advertise a CAS server, `login_ent(url, cookies=...)` for any
  ENT whose cookies you already have, and `login_ent(url, ..., ent=provider)`
  for custom ENT helpers. New `upnote.ent` package with the `EntProvider`
  contract, `cas_login` / `cas_provider` (a generic form-based CAS login,
  standard library only) and `EntLoginError`. See
  [the protocol notes](docs/PROTOCOL.md) and `examples/ent_login.py`.
- **Added** `crypto.generate_ent_key` and `crypto.solve_challenge_with_key`;
  `solve_challenge_session` is now a thin wrapper over the latter.
- **Added** `PronoteSession.create(..., mobile=False, cookies=...)` and
  `session.attributes` (the raw `Start({...})` values, where ENT logins find
  `e` and `f`).
- **Not verified live**: the official demo has no CAS, so this feature is
  covered by offline tests only. See Known limitations in the README.

## [0.2.0]

- **Verified live** on the official demo (PRONOTE 2026.2.7, student
  workspace): `get_user` and `get_timetable` return real data. The demo's
  week of 2026-10-05 has every lesson cancelled with the status
  "Classe absente" (`estAnnule` is a real boolean `True`), which is demo
  data, not a parsing issue. `examples/timetable.py` now prints the status
  next to `[CANCELED]`.
- **Added** the first data endpoint: the timetable (`get_timetable`,
  `PageEmploiDuTemps`), with `Lesson` / `Detention` models, per-day grouping
  and a `get_user` helper that returns the user's own resource. See
  `examples/timetable.py` and [the protocol notes](docs/PROTOCOL.md).
- **Added** request-side encoding helpers in `parsing.py` (`encode_date`,
  `encode_value`, `encode_type`, `encode_kind`), the mirror of the existing
  response decoding.
- **Added** `session.settings`: the parsed `FonctionParametres` response is
  now kept on the session (the timetable needs `General.PlacesParHeure` to
  turn a slot count into a duration).
- **Fixed** day-of-week handling for short dates (`"lundi 14h30"`):
  PRONOTE/Blocksnote index days Sunday=0, whereas the first port used
  Monday=0, which would have resolved to the wrong day. Also fixed the
  year rule for dates without a year (`"lundi 14/09"`: January-September
  resolve to next year, October-December to the current one).
- **Changed** the docs layout: protocol write-up moved to
  `docs/PROTOCOL.md`, changelog to `CHANGELOG.md`, README kept short.

## [0.1.0]

- **Confirmed working end-to-end** against the official demo instance
  (`https://demo.index-education.net/pronote/`, PRONOTE 2026.2.7): full
  login (`basic_login.py`) and an authenticated `ParametresUtilisateur`
  call (`custom_request.py`) both succeed. `parsing.py` correctly converts
  PRONOTE's typed date fields into real `datetime` objects as part of
  this - `custom_request.py` now passes `default=str` to `json.dumps`
  since the stdlib can't serialize `datetime` natively.
- **Fixed** (real server behavior change, not a bug in this project's
  original design): since 2026-09-02, PRONOTE >= 2026.2.5 no longer
  encrypts the `Identification` challenge - it sends one raw AES block
  that must be directly re-encrypted, not decrypted-then-stripped. Without
  this fix, login fails with an AES padding error on any affected instance
  (this also breaks `pronotepy` upstream - see
  [#346](https://github.com/bain3/pronotepy/issues/346) /
  [#348](https://github.com/bain3/pronotepy/issues/348)). `UpNote` now
  auto-detects the challenge format by its decoded length and handles
  both. See [the protocol notes](docs/PROTOCOL.md)
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
