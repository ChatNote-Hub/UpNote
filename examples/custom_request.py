"""
Log in, then send a custom appelfonction request using session.post().

This uses "ParametresUtilisateur", a function that returns the logged-in
user's general settings/profile - a reasonable first call to sanity-check
that a session is fully working end-to-end.

Usage:
    python3 examples/custom_request.py
"""
import json
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

    try:
        data = session.post("ParametresUtilisateur", {})
    except PronoteError as exc:
        print(f"Request failed: {exc}")
        return

    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
