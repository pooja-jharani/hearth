from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.lanes import auto_day_window, day_window, focus_window, lanes_html

TZ = ZoneInfo("Asia/Kolkata")
MEMBERS = [{"name": "Mom", "color": "#0F766E", "initials": "M"}, {"name": "Dad", "color": "#B45309", "initials": "D"},
           {"name": "Rohan", "color": "#4F46E5", "initials": "R"}]


def ev(i, title, sh, eh, who, **kw):
    return {"id": i, "title": title, "start": f"2026-10-22T{sh}:00+05:30", "end": f"2026-10-22T{eh}:00+05:30",
            "attendees": who, "status": "active", **kw}


def test_overlap_in_one_lane_stacks_into_two_rows_and_flags_clash():
    evs = [ev(1, "Review", "17", "18", ["Mom"]), ev(2, "Call", "17", "18", ["Mom"])]
    conf = [{"id": "c", "type": "PERSON_CLASH", "event_ids": [1, 2]}]
    html = lanes_html(evs, MEMBERS, conf, TZ, day_window(date(2026, 10, 22), TZ))
    assert html.count('class="lbar clash"') == 2
    assert "top:4px" in html and "top:34px" in html  # two sub-rows
    assert "! Review" in html and "! Call" in html


def test_coverage_subject_is_striped_and_bar_position_is_proportional():
    evs = [ev(1, "PTM", "17", "18", ["Rohan"], needs_adult=True)]
    conf = [{"id": "c", "type": "COVERAGE_CLASH", "event_ids": [1, 2]}]
    html = lanes_html(evs, MEMBERS, conf, TZ, day_window(date(2026, 10, 22), TZ))
    assert "stripe" in html and "needs an adult" in html
    assert "left:66.67%" in html  # 17:00 in a 07:00 to 22:00 window = 10/15


def test_compact_hides_uninvolved_lanes_and_focus_window_hugs_events():
    evs = [ev(1, "PTM", "17", "18", ["Rohan"])]
    w = focus_window(evs, TZ)
    assert (w[1] - w[0]).total_seconds() >= 3 * 3600
    html = lanes_html(evs, MEMBERS, [], TZ, w, compact=True)
    assert "Rohan" in html and "Mom" not in html


def test_titles_are_escaped_and_events_outside_window_dropped():
    evs = [ev(1, "<script>x</script>", "17", "18", ["Mom"]), ev(2, "Night", "23", "23", ["Mom"])]
    evs[1]["end"] = "2026-10-22T23:30:00+05:30"
    html = lanes_html(evs, MEMBERS, [], TZ, day_window(date(2026, 10, 22), TZ))
    assert "<script>" not in html and "&lt;script&gt;" in html and "Night" not in html


def test_now_marker_only_inside_window():
    w = day_window(date(2026, 10, 22), TZ)
    inside = lanes_html([], MEMBERS, [], TZ, w, now_dt=datetime(2026, 10, 22, 10, 0, tzinfo=TZ))
    outside = lanes_html([], MEMBERS, [], TZ, w, now_dt=datetime(2026, 10, 23, 10, 0, tzinfo=TZ))
    assert "now-line" in inside and "now-line" not in outside


def test_auto_day_window_fits_events_and_has_sane_defaults():
    d = date(2026, 10, 22)
    lo, hi = auto_day_window([ev(1, "PTM", "17", "18", ["Rohan"])], d, TZ)
    assert lo.hour <= 15 and hi.hour >= 19 and (hi - lo).total_seconds() >= 8 * 3600
    assert hi.hour <= 23 and lo.hour >= 6
    lo, hi = auto_day_window([], d, TZ)
    assert (lo.hour, hi.hour) == (8, 20)
    lo, hi = auto_day_window([ev(1, "Early", "06", "07", ["Mom"])], d, TZ)
    assert lo.hour == 6
