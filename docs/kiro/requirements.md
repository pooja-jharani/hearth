# Requirements (starting point to import into Kiro; refine it there and keep screenshots as evidence)

1. As a parent, I can add one or several events by speech or text, so that nobody has to type into a calendar.
   - WHEN a user adds an event THEN the system SHALL save it and return any conflicts with a one-sentence reason.
2. As a parent, I get clashes explained and fixed.
   - WHEN an event needing an adult has no free parent and no attending adult THEN the system SHALL report a COVERAGE_CLASH.
   - WHEN asked, the system SHALL rank at most 3 fixes and apply none without confirmation; every change SHALL be undoable.
3. As a family, we save standing rules by speech ("Dadi can't do evening pickups") that every plan is checked against.
4. As a family, chores go to the member with the lowest recent load, with the reason stated; children only get kid-friendly chores.
5. As a parent, I approve events my child adds; children cannot move or delete adults' events.
6. As a developer, any MCP client can use the server over Streamable HTTP (spec 2025-11-25).
