from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from family_conflicts import Appt, Person, Rule, apply_option, detect, free_slots, suggest

TZ = ZoneInfo("Asia/Kolkata")
MOM, DAD, ROHAN, DADI = 1, 2, 3, 4
PEOPLE = [
    Person(MOM, "Mom", "parent", True),
    Person(DAD, "Dad", "parent", True),
    Person(ROHAN, "Rohan", "child", False),
    Person(DADI, "Dadi", "grandparent", True),
]


def at(h, m=0, day=22):
    return datetime(2026, 10, day, h, m, tzinfo=TZ).astimezone(timezone.utc)


def appt(i, title, sh, eh, att, sm=0, em=0, **kw):
    return Appt(i, title, at(sh, sm), at(eh, em), tuple(att), **kw)


def ptm():
    return appt(1, "Rohan's PTM", 17, 18, [ROHAN], needs_adult=True, movable=False, location="school")


def mom_review():
    return appt(2, "Mom's team review", 17, 18, [MOM], movable=False)


def call():
    return appt(3, "Client call", 17, 18, [DAD])


def test_back_to_back_is_not_a_clash():
    a = appt(1, "Gym", 17, 18, [DAD])
    b = appt(2, "Call", 18, 19, [DAD])
    assert detect([a, b], PEOPLE, [], TZ) == []


def test_person_clash_overlap():
    a = appt(1, "Gym", 17, 18, [DAD])
    b = appt(2, "Call", 17, 19, [DAD], sm=30)
    cs = detect([a, b], PEOPLE, [], TZ)
    assert [c.type for c in cs] == ["PERSON_CLASH"]
    assert cs[0].people == ("Dad",)
    assert "Dad is booked for both" in cs[0].why


def test_coverage_ok_when_one_parent_free():
    assert detect([ptm(), mom_review()], PEOPLE, [], TZ) == []


def test_coverage_clash_when_both_parents_busy():
    cs = detect([ptm(), mom_review(), call()], PEOPLE, [], TZ)
    assert [c.type for c in cs] == ["COVERAGE_CLASH"]
    assert cs[0].why == "Rohan's PTM at 5 pm needs an adult, and both Mom and Dad are busy."
    assert cs[0].severity == "high"


def test_coverage_ok_if_adult_attends():
    p = appt(1, "Rohan's PTM", 17, 18, [ROHAN, DADI], needs_adult=True, movable=False)
    assert detect([p, mom_review(), call()], PEOPLE, [], TZ) == []


def test_rule_violation_and_task_matching():
    rule = Rule(1, DADI, "no_after", {"time": "17:00", "task": "pickup", "source_text": "Dadi can't do evening pickups"})
    late = appt(5, "Rohan tuition pick-up", 18, 19, [DADI, ROHAN])
    early = appt(6, "Rohan school pickup", 15, 16, [DADI, ROHAN])
    other = appt(7, "Bhajan", 19, 20, [DADI])
    cs = detect([late, early, other], PEOPLE, [rule], TZ)
    assert [(c.type, c.event_ids) for c in cs] == [("RULE_VIOLATION", (5,))]
    assert "Dadi can't do evening pickups" in cs[0].why


def test_resolution_ranking_matches_demo():
    appts = [ptm(), mom_review(), call()]
    c = detect(appts, PEOPLE, [], TZ)[0]
    opts = suggest(c, appts, PEOPLE, [], TZ)
    assert opts[0].kind == "move" and opts[0].event_id == 3
    # PTM is at school, so the call moves to 6:30 pm (30 minute travel gap)
    assert opts[0].new_start == at(18, 30)
    assert opts[1].kind == "add_attendee" and opts[1].add_member == DADI
    assert opts[-1].kind == "keep" and len(opts) == 3
    # applying either real option clears the conflict
    for o in opts[:2]:
        assert detect(apply_option(o, appts), PEOPLE, [], TZ) == []


def test_fixed_events_never_move():
    a = appt(1, "Fixed", 17, 18, [DAD], movable=False)
    b = appt(2, "Fixed too", 17, 18, [DAD], movable=False)
    c = detect([a, b], PEOPLE, [], TZ)[0]
    assert [o.kind for o in suggest(c, [a, b], PEOPLE, [], TZ)] == ["keep"]


def test_moves_stay_in_waking_hours_and_create_no_new_clash():
    a = appt(1, "Late a", 20, 21, [DAD], movable=False)
    b = appt(2, "Late b", 20, 21, [DAD])
    c = detect([a, b], PEOPLE, [], TZ)[0]
    for o in suggest(c, [a, b], PEOPLE, [], TZ):
        if o.kind == "move":
            assert o.new_end.astimezone(TZ).hour <= 21
            assert detect(apply_option(o, [a, b]), PEOPLE, [], TZ) == []


def test_rule_violation_resolution_reassigns_to_parent():
    rule = Rule(1, DADI, "no_after", {"time": "17:00", "task": "pickup"})
    late = appt(5, "Rohan tuition pickup", 18, 19, [DADI], movable=False)
    c = detect([late], PEOPLE, [rule], TZ)[0]
    opts = suggest(c, [late], PEOPLE, [rule], TZ)
    assert opts[0].kind == "reassign" and opts[0].remove_member == DADI
    assert detect(apply_option(opts[0], [late]), PEOPLE, [rule], TZ) == []


def test_free_slots_respect_attendees_and_waking_hours():
    busy = appt(1, "Call", 10, 12, [DAD])
    slots = free_slots([busy], PEOPLE, [DAD], 60, at(8), at(21), TZ)
    assert slots[0][0] == at(8)
    assert all(not (s < busy.end and busy.start < e) for s, e in slots)
    late = free_slots([], PEOPLE, [DAD], 120, at(20), at(23), TZ)
    assert late == []  # would end after 21:00


def test_free_slots_needs_adult_requires_free_parent():
    mom = appt(1, "Mom", 9, 12, [MOM])
    dad = appt(2, "Dad", 9, 12, [DAD])
    slots = free_slots([mom, dad], PEOPLE, [ROHAN], 60, at(9), at(14), TZ, needs_adult=True)
    assert slots[0][0] >= at(12)
