# family-conflicts

A tiny, dependency-free Python library that finds scheduling problems in a
household calendar and ranks ways to fix them. It was extracted from
[Hearth](../../README.md), a voice-first family coordinator MCP server.

It detects three kinds of problem, each with a one-sentence `why`:

| Type | Meaning |
|------|---------|
| `PERSON_CLASH` | the same person is booked for two overlapping events |
| `COVERAGE_CLASH` | an event needs an adult and no parent is free (and no adult attends it) |
| `RULE_VIOLATION` | an event breaks a saved family rule, e.g. "Dadi can't do pickups after 5 pm" |

Time intervals are half-open, so back-to-back events never clash.

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from family_conflicts import Person, Appt, detect, suggest

tz = ZoneInfo("Asia/Kolkata")
people = [Person(1, "Mom", "parent", True), Person(2, "Dad", "parent", True),
          Person(3, "Rohan", "child", False)]
utc = lambda *a: datetime(*a, tzinfo=timezone.utc)
appts = [
    Appt(1, "Rohan's PTM", utc(2026, 10, 22, 11, 30), utc(2026, 10, 22, 12, 30), (3,), needs_adult=True, movable=False, location="school"),
    Appt(2, "Mom's review", utc(2026, 10, 22, 11, 30), utc(2026, 10, 22, 12, 30), (1,), movable=False),
    Appt(3, "Client call", utc(2026, 10, 22, 11, 30), utc(2026, 10, 22, 12, 30), (2,)),
]
conflicts = detect(appts, people, [], tz)
print(conflicts[0].why)
for opt in suggest(conflicts[0], appts, people, [], tz):
    print(opt.rank, opt.label, "-", opt.reason)
```

Run the tests with `pytest packages/family_conflicts/tests`. MIT licensed.
