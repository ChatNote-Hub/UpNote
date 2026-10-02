"""
Cryptographic primitives used by the PRONOTE protocol.

pycryptodome isn't available in this sandbox (no network access for pip),
so we use `cryptography` (pyca) instead, which is already installed and is
a perfectly solid alternative anyway.

What we know about the protocol (verified against pronotepy's source code
and the Blocksnote TypeScript wrapper):
- AES-CBC with PKCS7 padding, 16-byte blocks.
- The "key" and "iv" actually used by AES-CBC are NEVER the raw material
  directly - they're always MD5(raw_material). This matches Blocksnote's
  AES class (structures/crypto/AES.ts) exactly:
      used_key = MD5(key_material)
      used_iv  = MD5(iv_material) if iv_material else 16 zero bytes
- Default key material is empty bytes -> MD5(b"") = d41d8cd98f00b204e9800998ecf8427e
- Default iv material is empty -> 16 zero bytes (not MD5(b""), see AES.ts:
  `this.iv.length ? md5(this.iv) : new Uint8Array(16)`)
"""
from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as sym_padding
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.backends import default_backend

from . import constants

# --- Defaults -----------------------------------------------------------

DEFAULT_IV = bytes(16)


def md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


DEFAULT_KEY = md5(b"")  # d41d8cd98f00b204e9800998ecf8427e


def sha256_hex_upper(data: bytes) -> str:
    """upper_case(hex(sha256(data))) - used to compute 'mtp'."""
    return hashlib.sha256(data).hexdigest().upper()


# --- AES ------------------------------------------------------------------

def aes_encrypt(data: bytes, key: bytes, iv: bytes = DEFAULT_IV) -> bytes:
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def aes_decrypt(data: bytes, key: bytes, iv: bytes = DEFAULT_IV) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend()).decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


# --- numeroOrdre ("no" field) ----------------------------------------------

def numero_ordre(n: int, key: bytes = DEFAULT_KEY, iv: bytes = DEFAULT_IV) -> str:
    """
    Encrypts the message number (starts at 1, +2 per request) and returns
    the result as hex (NOT uppercase - unlike dataSec).
    """
    return aes_encrypt(str(n).encode(), key, iv).hex()


# --- RSA (only used over plain HTTP, to transmit the AES IV) ---------------
# Modulus/exponent verified identical between pronotepy (2023) and
# Blocksnote (2026) - just represented in different bases (decimal vs hex).

RSA_1024_MODULUS = int(constants.RSA_MODULUS_HEX, 16)
RSA_1024_EXPONENT = int(constants.RSA_EXPONENT_HEX, 16)


def rsa_encrypt(data: bytes) -> bytes:
    """Encrypts with the RSA public key hard-coded in eleve.js (PKCS1 v1.5)."""
    public_numbers = rsa.RSAPublicNumbers(RSA_1024_EXPONENT, RSA_1024_MODULUS)
    public_key = public_numbers.public_key(default_backend())
    return public_key.encrypt(data, asym_padding.PKCS1v15())


# --- Key derivation for the login challenge --------------------------------

def compute_mtp(alea: str, password: str) -> str:
    """mtp = upper_case(hex(sha256(alea + password)))"""
    return sha256_hex_upper((alea + password).encode())


def challenge_key(username: str, mtp: str) -> bytes:
    """key = md5(username + mtp)"""
    return md5((username + mtp).encode())


def remove_every_other_char(text: str) -> str:
    """abcdefg -> aceg (keeps every other character, starting with the first)."""
    return text[::2]


def solve_challenge(challenge_hex: str, username: str, password: str, alea: str, iv: bytes) -> str:
    """
    Solves the PRONOTE login challenge:
    1. hex-decode + AES decrypt (key derived from username+mtp, session iv)
    2. remove every other character
    3. re-encrypt the result, return as hex
    """
    mtp = compute_mtp(alea, password)
    key = challenge_key(username, mtp)

    decrypted = aes_decrypt(bytes.fromhex(challenge_hex), key, iv)
    modified = remove_every_other_char(decrypted.decode())
    re_encrypted = aes_encrypt(modified.encode(), key, iv)
    return re_encrypted.hex()


# --- Session AES: derive key/iv on the fly (like Blocksnote's AES class) ---

class AESSession:
    """
    Mirrors `structures/crypto/AES.ts` from Blocksnote: we never store a
    directly "usable" key/iv, only the raw material. The key and iv
    actually used by AES-CBC are always recomputed as:

        used key = MD5(key_material)
        used iv  = MD5(iv_material) if iv_material is non-empty, else 16 zero bytes

    With empty key/iv material (the default), this correctly falls back to
    DEFAULT_KEY / DEFAULT_IV.
    """

    def __init__(self) -> None:
        self._key_material: bytes = b""
        self._iv_material: bytes = b""

    @property
    def key(self) -> bytes:
        return md5(self._key_material)

    @property
    def iv(self) -> bytes:
        return md5(self._iv_material) if self._iv_material else bytes(16)

    def set_key(self, material: bytes) -> None:
        self._key_material = material

    def reset_key(self) -> None:
        self._key_material = b""

    def set_iv(self, material: bytes) -> None:
        self._iv_material = material

    def reset_iv(self) -> None:
        self._iv_material = b""

    def encrypt(self, data: bytes) -> bytes:
        return aes_encrypt(data, self.key, self.iv)

    def decrypt(self, data: bytes) -> bytes:
        return aes_decrypt(data, self.key, self.iv)

    def encrypt_hex(self, data: bytes | str) -> str:
        if isinstance(data, str):
            data = data.encode()
        return self.encrypt(data).hex()

    def decrypt_hex(self, hex_str: str) -> bytes:
        return self.decrypt(bytes.fromhex(hex_str))


def generate_temp_key(username: str, password: str, seed: str) -> str:
    """
    Mirrors Challenge.generateTempKey (Blocksnote):
        tempKey = lower(username) + upper(hex(sha256(seed + password.strip())))

    Note: unlike pronotepy's protocol.md (which conditions username/password
    casing on the modeCompLog/modeCompMdp flags returned by the server),
    Blocksnote unconditionally lowercases the username and strips the
    password.
    """
    digest = hashlib.sha256((seed + password.strip()).encode()).hexdigest().upper()
    return username.lower() + digest


# A single AES block, hex-encoded, is exactly 32 hex characters (16 bytes).
# Used to detect the PRONOTE >= 2026.2.5 challenge format - see
# solve_challenge_session below.
_SINGLE_AES_BLOCK = 16


def solve_challenge_session(aes: AESSession, challenge_hex: str, username: str, password: str, seed: str) -> str:
    """
    "Session" version of solve_challenge, mirroring Blocksnote's
    Challenge.solve: uses the session's current iv, derives a temporary key
    from the password, solves the challenge, then resets the key (it will
    be derived again right after, from the password, to decrypt 'cle' in
    the Authentification response).

    Handles TWO challenge formats, auto-detected:

    - Legacy (PRONOTE < 2026.2.5): the challenge is real AES ciphertext.
      decrypt it, keep every other character of the plaintext (discarding
      the interleaved "alea" noise), re-encrypt that.
    - Current (PRONOTE >= 2026.2.5, since 2026-09-02): the server no longer
      encrypts the challenge at all. It sends a single raw 16-byte block
      (exactly one AES block - no interleaved alea, nothing to strip), and
      expects the client to directly AES-encrypt the hex representation of
      that block (uppercased) with no decrypt/strip step first. This
      matches the official PRONOTE 2026 client JS (`getNouveauChallenge()`),
      which only ever encrypts, never decrypts, the received string.

    Detection: a challenge that hex-decodes to exactly one AES block (16
    bytes) is the new format. A real legacy ciphertext is essentially never
    exactly one block (it carries the original challenge interleaved with
    alea noise, which is longer), so block-length is a reliable signal -
    more reliable than "try decrypt, see if padding is valid", since an
    outright wrong key still produces valid-looking PKCS7 padding by chance
    about 1 time in 256.
    """
    temp_key = generate_temp_key(username, password, seed)
    aes.set_key(temp_key.encode())

    challenge_bytes = bytes.fromhex(challenge_hex)

    if len(challenge_bytes) == _SINGLE_AES_BLOCK:
        text_to_encrypt = challenge_hex.upper()
    else:
        decrypted = aes.decrypt(challenge_bytes).decode()
        text_to_encrypt = remove_every_other_char(decrypted)

    encrypted_hex = aes.encrypt_hex(text_to_encrypt)

    aes.reset_key()
    return encrypted_hex
