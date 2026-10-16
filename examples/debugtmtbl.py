import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from upnote import NOTSpace, get_timetable, get_user, login

session = login(
    "https://demo.index-education.net/pronote/eleve.html",
    "demonstration",
    "pronotevs",
    workspace_type=NOTSpace.STUDENT,
)
user = get_user(session)

start = datetime(2026, 10, 5)
slots = get_timetable(session, user.resource, start=start, end=start + timedelta(days=6))

for key in ("estAnnule", "Statut", "hintRealise", "CouleurFond"):
    print(key, "=", repr(slots[0].raw.get(key)))
print(sorted(slots[0].raw))