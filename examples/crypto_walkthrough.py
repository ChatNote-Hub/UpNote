"""
Standalone demo of the crypto layer - no network needed.

Shows the low-level building blocks used everywhere else in this project:
key/iv derivation, the numeroOrdre sanity check, and challenge solving.

Usage:
    python3 examples/crypto_walkthrough.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from upnote import crypto


def main() -> None:
    print("--- Default key/iv ---")
    print(f"DEFAULT_KEY = {crypto.DEFAULT_KEY.hex()}")
    print(f"DEFAULT_IV  = {crypto.DEFAULT_IV.hex()}")

    print("\n--- numeroOrdre sanity check ---")
    aes = crypto.AESSession()
    no_1 = aes.encrypt_hex("1")
    expected = "3fa959b13967e0ef176069e01e23c8d7"
    print(f"encrypt('1') = {no_1}")
    print(f"expected     = {expected}")
    print(f"match: {no_1 == expected}")

    print("\n--- Key/iv derivation from raw material ---")
    aes.set_key(b"some raw key material")
    aes.set_iv(b"some raw iv material")
    print(f"used key = MD5(key material) = {aes.key.hex()}")
    print(f"used iv  = MD5(iv material)  = {aes.iv.hex()}")

    print("\n--- Challenge solving (simulated server) ---")
    username = "demonstration"
    password = "pronotevs"
    seed = "exampleSeed123"

    server_aes = crypto.AESSession()
    server_aes.set_iv(b"shared session iv material")
    temp_key = crypto.generate_temp_key(username, password, seed)
    server_aes.set_key(temp_key.encode())

    plaintext_challenge = "thisIsAFakeChallengeTextFromServer"
    challenge_hex = server_aes.encrypt_hex(plaintext_challenge)
    server_aes.reset_key()
    print(f"tempKey = {temp_key}")
    print(f"fake challenge (hex) = {challenge_hex}")

    client_aes = crypto.AESSession()
    client_aes.set_iv(b"shared session iv material")
    solution_hex = crypto.solve_challenge_session(client_aes, challenge_hex, username, password, seed)
    print(f"solution (hex) = {solution_hex}")

    # Only for demonstration: decrypt the solution to show what the server
    # would see - a real server does this internally.
    client_aes.set_key(temp_key.encode())
    solved_plain = client_aes.decrypt_hex(solution_hex).decode()
    print(f"decrypted solution = {solved_plain!r}")
    print(f"expected (every other char) = {crypto.remove_every_other_char(plaintext_challenge)!r}")


if __name__ == "__main__":
    main()
