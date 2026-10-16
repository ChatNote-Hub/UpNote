"""
Log in through an ENT (school portal / CAS) and print who is logged in.

The password is asked interactively and never stored. Two ways to run it:

    # 1. username + password: UpNote logs in to the CAS server the instance
    #    advertises (plain CAS forms only - see docs/PROTOCOL.md)
    python3 examples/ent_login.py https://0000000a.index-education.net/pronote/eleve.html

    # 2. cookies you exported from your browser after logging in to your ENT
    #    (works for any ENT, including EduConnect/SAML ones)
    python3 examples/ent_login.py https://0000000a.index-education.net/pronote/eleve.html \\
        --cookie TGC=... --cookie JSESSIONID=...

Treat cookies like passwords: they give access to your account. Never commit them.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from upnote import UpNoteError, get_user, login_ent


def main() -> None:
    parser = argparse.ArgumentParser(description="PRONOTE login through an ENT")
    parser.add_argument("url", help="direct URL of the workspace page, e.g. .../pronote/eleve.html")
    parser.add_argument("--cookie", action="append", default=[], metavar="NAME=VALUE", help="ENT cookie (repeatable)")
    args = parser.parse_args()

    try:
        if args.cookie:
            cookies = dict(item.split("=", 1) for item in args.cookie)
            session = login_ent(args.url, cookies=cookies)
        else:
            username = input("ENT username: ")
            password = getpass.getpass("ENT password: ")
            session = login_ent(args.url, username, password)

        user = get_user(session)
    except (UpNoteError, ValueError) as exc:
        print(f"ENT login failed: {exc}")
        return

    print(f"Logged in through the ENT as {user.full_name}")


if __name__ == "__main__":
    main()
