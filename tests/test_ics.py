from zoneinfo import ZoneInfo

from app.ics import export_ics, import_ics

TZ = ZoneInfo("Asia/Kolkata")
EV = {"id": 7, "title": "Rohan's PTM, school; hall", "start": "2026-10-22T17:00:00+05:30",
      "end": "2026-10-22T18:00:00+05:30", "attendees": ["Mom", "Rohan"], "needs_adult": True,
      "location": "St. Mary's", "status": "confirmed"}


def test_roundtrip():
    out = import_ics(export_ics([EV]), TZ)
    assert out["skipped"] == []
    e = out["events"][0]
    assert e["title"] == EV["title"] and e["location"] == "St. Mary's"
    assert e["start"] == EV["start"] and e["end"] == EV["end"]


def test_cancelled_not_exported():
    assert "VEVENT" not in export_ics([{**EV, "status": "cancelled"}])


def test_import_variants():
    text = "\r\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT", "SUMMARY:All day", "DTSTART;VALUE=DATE:20261025", "END:VEVENT",
        "BEGIN:VEVENT", "SUMMARY:Utc with duration", "DTSTART:20261026T040000Z", "DURATION:PT90M", "END:VEVENT",
        "BEGIN:VEVENT", "SUMMARY:Weekly yoga", "DTSTART:20261026T040000Z", "RRULE:FREQ=WEEKLY", "END:VEVENT",
        "BEGIN:VEVENT", "SUMMARY:Folded long", " title here", "DTSTART:20261027T100000", "END:VEVENT",
        "BEGIN:VEVENT", "SUMMARY:Broken", "DTSTART:garbage", "END:VEVENT", "END:VCALENDAR"])
    out = import_ics(text, TZ)
    titles = [e["title"] for e in out["events"]]
    assert titles == ["All day", "Utc with duration", "Folded longtitle here"]
    assert out["events"][1]["start"] == "2026-10-26T09:30:00+05:30"
    assert out["events"][1]["end"] == "2026-10-26T11:00:00+05:30"
    assert {s["title"]: s["reason"] for s in out["skipped"]}["Weekly yoga"].startswith("repeating")
    assert len(out["skipped"]) == 2


def test_long_line_folds_and_unfolds():
    long = {**EV, "title": "x" * 200}
    assert import_ics(export_ics([long]), TZ)["events"][0]["title"] == "x" * 200
