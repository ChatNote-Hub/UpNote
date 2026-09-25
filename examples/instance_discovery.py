"""
Discover which workspaces (student, parent, teacher, ...) are available on
a given PRONOTE instance, without logging in.

Usage:
    python3 examples/instance_discovery.py https://demo.index-education.net/pronote/eleve.html
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pronote_wrapper.client import Instance
from pronote_wrapper.constants import NOTSpace

SPACE_NAMES = {space.value: space.name for space in NOTSpace}


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://demo.index-education.net/pronote/eleve.html"

    instance = Instance.create_from_url(url)

    print(f"Instance root: {instance.source}")
    print(f"Version: {instance.version}")
    print(f"CAS/ENT configured: {'yes' if instance.cas else 'no'}")
    if instance.cas:
        print(f"  CAS url: {instance.cas.url}")

    print("\nAvailable workspaces:")
    for workspace in instance.workspaces:
        type_name = SPACE_NAMES.get(int(workspace.type), f"unknown ({workspace.type})")
        delegated = " (delegated)" if workspace.delegated else ""
        print(f"  - {workspace.name} [{type_name}]{delegated} -> {workspace.url}")


if __name__ == "__main__":
    main()
