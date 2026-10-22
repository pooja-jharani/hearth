# Conflict rules and example dialogues

All times are half-open: an event ending at 6 pm and one starting at 6 pm do not clash.

## Conflict types
| Type | Meaning | Severity |
|------|---------|----------|
| `PERSON_CLASH` | the same person is in two overlapping events | medium |
| `COVERAGE_CLASH` | an event with `needs_adult` has no adult attending and no parent free | high |
| `RULE_VIOLATION` | an event breaks a saved rule (`no_after`, `no_before`, `no_task`) | high |

Every conflict has an `id`, the people involved, and a one-sentence `why`. Read the `why` aloud.

## Ranking of fixes
Fewest people affected, then moving an event before asking someone to do extra, then the smallest move.
Moves stay between 8 am and 9 pm and never create a new clash. Fixed events (`movable: false`, like a PTM) never move.
When the fixed event has a location, a move keeps a 30 minute travel gap after it.
The last option is always "Keep as is".

## Example: coverage clash
User (Dad): "I have a client call Thursday 5 to 6."
Tool: `add_event` returns a `COVERAGE_CLASH`: "Rohan's PTM at 5 pm needs an adult, and both Mom and Dad are busy."
You: "Heads up: Rohan's PTM at 5 needs an adult and both you and Mom are busy."
User: "What can we do?" -> `suggest_resolutions`
You: "Option 1, move the client call to 6:30. Option 2, ask Dadi to attend the PTM. Option 3, keep as is."
User: "Do the first one." -> `move_event` (pending) -> "Shall I move Client call from 5 pm to 6:30 pm? Say yes to confirm."
User: "Yes." -> `commit_action` -> "Done. Client call is now Thursday at 6:30 pm. No clashes left."

## Example: learned rule
User: "Dadi can't do evening pickups."
You: `add_rule(member="Dadi", kind="no_after", time="17:00", task="pickup", source_text=<the sentence>)`
Reply: "Got it: Dadi won't do pickups at or after 5 pm. I'll check every plan against that."
Later: "Dadi will pick up Rohan from tuition Friday at 6" -> `RULE_VIOLATION`, with "Ask Mom to do it instead" as option 1.

## Rule kinds
- `no_after` with `time`: not at or after that time (evening = 17:00).
- `no_before` with `time`: not before that time (mornings = 12:00).
- `no_task`: never does that task. `task` is a short lowercase noun such as `pickup`.
