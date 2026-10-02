"""
Basic login example against the PRONOTE demo instance.

Usage:
    python3 examples/basic_login.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from upnote import client, constants
from upnote.session import PronoteError

DEMO_URL = "https://demo.index-education.net/pronote/eleve.html"
DEMO_USERNAME = "demonstration"
DEMO_PASSWORD = "pronotevs"


def main() -> None:
    try:
        session = client.login(
            DEMO_URL,
            DEMO_USERNAME,
            DEMO_PASSWORD,
            workspace_type=constants.NOTSpace.STUDENT,
        )
    except PronoteError as exc:
        print(f"Login failed: {exc}")
        return

    print("Login successful.")
    print(f"Session id: {session.session_id}")
    print(f"Encryption enabled: {session.use_encryption}")
    print(f"Compression enabled: {session.use_compression}")
    print(f"Next request number: {session.request_number}")


if __name__ == "__main__":
    main()
