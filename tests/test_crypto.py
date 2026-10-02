import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from upnote import crypto


def test_default_key_is_md5_of_empty_string():
    assert crypto.DEFAULT_KEY.hex() == "d41d8cd98f00b204e9800998ecf8427e"


def test_numero_ordre_sanity_check():
    """
    Known-good value from the PRONOTE protocol: the first numeroOrdre
    (message number 1, default key/iv) must always equal
    3fa959b13967e0ef176069e01e23c8d7.
    """
    assert crypto.numero_ordre(1) == "3fa959b13967e0ef176069e01e23c8d7"


def test_aes_roundtrip():
    key = crypto.md5(b"a test key")
    iv = crypto.DEFAULT_IV
    plaintext = b"a test message that is a bit longer than 16 bytes"

    ciphertext = crypto.aes_encrypt(plaintext, key, iv)
    assert crypto.aes_decrypt(ciphertext, key, iv) == plaintext


def test_remove_every_other_char():
    assert crypto.remove_every_other_char("abcdefg") == "aceg"
    assert crypto.remove_every_other_char("hello_world") == "hlowrd"


def test_challenge_roundtrip():
    """
    Simulates the server side: encrypts a known text as if it were the
    "challenge", then checks that solve_challenge produces the expected
    text (every other character, re-encrypted).
    """
    username = "demonstration"
    password = "pronotevs"
    alea = "someRandomAlea"
    iv = crypto.DEFAULT_IV

    mtp = crypto.compute_mtp(alea, password)
    key = crypto.challenge_key(username, mtp)

    original = "abcdefghijklmnop"  # even length to keep the test simple
    challenge_hex = crypto.aes_encrypt(original.encode(), key, iv).hex()

    solved_hex = crypto.solve_challenge(challenge_hex, username, password, alea, iv)

    # re-decrypt the result to check it matches "every other character" of
    # the original text
    solved_plain = crypto.aes_decrypt(bytes.fromhex(solved_hex), key, iv).decode()
    assert solved_plain == crypto.remove_every_other_char(original)


def test_aes_session_defaults_match_default_key_iv():
    aes = crypto.AESSession()
    assert aes.key == crypto.DEFAULT_KEY
    assert aes.iv == crypto.DEFAULT_IV


def test_aes_session_numero_ordre_sanity_check():
    aes = crypto.AESSession()
    assert aes.encrypt_hex("1") == "3fa959b13967e0ef176069e01e23c8d7"


def test_generate_temp_key_format():
    # per Challenge.generateTempKey: lower(username) + upper(hex(sha256(seed+password.strip())))
    key = crypto.generate_temp_key("Demonstration", "  pronotevs  ", "seed123")
    expected_digest = crypto.sha256_hex_upper(("seed123" + "pronotevs").encode())
    assert key == "demonstration" + expected_digest


def test_solve_challenge_session_roundtrip_legacy_protocol():
    """
    Legacy protocol (PRONOTE < 2026.2.5): simulates the server encrypting a
    known text as the challenge (deliberately NOT a single AES block, so
    this exercises the decrypt-and-strip path), then checks that
    solve_challenge_session correctly returns "every other character"
    re-encrypted with the same key/iv.
    """
    username = "demonstration"
    password = "pronotevs"
    seed = "someRandomSeed"

    aes = crypto.AESSession()
    aes.set_iv(b"raw-iv-material-from-server")  # raw material, will be MD5'd before use

    temp_key = crypto.generate_temp_key(username, password, seed)
    aes.set_key(temp_key.encode())

    original = "abcdefghijklmnop"
    challenge_hex = aes.encrypt_hex(original)
    assert len(bytes.fromhex(challenge_hex)) != 16  # sanity check: NOT a single block
    aes.reset_key()

    solved_hex = crypto.solve_challenge_session(aes, challenge_hex, username, password, seed)

    aes.set_key(temp_key.encode())
    solved_plain = aes.decrypt_hex(solved_hex).decode()
    assert solved_plain == crypto.remove_every_other_char(original)


def test_solve_challenge_session_single_block_is_pronote_2026_protocol():
    """
    Regression test for a real bug: since 2026-09-02, PRONOTE >= 2026.2.5
    no longer encrypts the challenge. It sends a single raw 16-byte block
    (one exact AES block) that must be directly re-encrypted (its uppercase
    hex representation) - no decrypt, no "every other character" stripping.
    Running the legacy path against this format raises a padding error,
    since the 16 raw bytes aren't real ciphertext at all.
    """
    username = "demonstration"
    password = "pronotevs"
    seed = ""  # the 2026.2.5 Identification response typically omits "alea"

    aes = crypto.AESSession()
    aes.set_iv(b"shared session iv material")

    raw_challenge = bytes(range(16))  # exactly one AES block, NOT real ciphertext
    challenge_hex = raw_challenge.hex()
    assert len(raw_challenge) == 16

    solution_hex = crypto.solve_challenge_session(aes, challenge_hex, username, password, seed)

    # Expected: AES-encrypt the uppercase hex string of the raw challenge
    # bytes directly - no decryption involved anywhere in the computation.
    temp_key = crypto.generate_temp_key(username, password, seed)
    expected_aes = crypto.AESSession()
    expected_aes.set_iv(b"shared session iv material")
    expected_aes.set_key(temp_key.encode())
    expected_hex = expected_aes.encrypt_hex(challenge_hex.upper())

    assert solution_hex == expected_hex


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
