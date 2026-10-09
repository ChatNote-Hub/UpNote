"""
Fetch and print a timetable.

By default prints the current calendar week (Monday to Sunday). Pass a
school-week number to ask for that week instead.

Usage:
    python3 examples/timetable.py
    python3 examples/timetable.py 12
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from upnote import NOTSpace, UpNoteError, get_timetable, get_user, group_by_day, login
from upnote.timetable import Detention, Lesson

DEMO_URL = "https://demo.index-education.net/pronote/eleve.html"
DEMO_USERNAME = "demonstration"
DEMO_PASSWORD = "pronotevs"


def current_week_range() -> tuple[datetime, datetime]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def main() -> None:
    try:
        session = login(DEMO_URL, DEMO_USERNAME, DEMO_PASSWORD, workspace_type=NOTSpace.STUDENT)
        user = get_user(session)

        if len(sys.argv) > 1:
            slots = get_timetable(session, user.resource, week_number=int(sys.argv[1]))
        else:
            start, end = current_week_range()
            slots = get_timetable(session, user.resource, start=start, end=end)
    except UpNoteError as exc:
        print(f"Request failed: {exc}")
        return

    print(f"Timetable for {user.full_name} - {len(slots)} slot(s)\n")

    for day in group_by_day(slots):
        print(day.date.strftime("%A %d %B %Y"))
        for slot in day.slots:
            times = f"{slot.start:%H:%M}-{slot.end:%H:%M}"
            if isinstance(slot, Detention):
                print(f"  {times}  DETENTION ({slot.state})")
            elif isinstance(slot, Lesson):
                flag = "  [CANCELED]" if slot.canceled else ""
                rooms = ", ".join(slot.rooms) or "-"
                teachers = ", ".join(slot.teachers) or "-"
                print(f"  {times}  {slot.subject or '?'}  |  {teachers}  |  {rooms}{flag}")
        print()


if __name__ == "__main__":
    main()
