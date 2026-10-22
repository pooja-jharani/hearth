---
name: family-coordinator
description: Use when a user wants to add, check, move or plan family events, chores or household rules, or asks what is coming up or who is free. Works with the Hearth MCP server.
---

# Family Coordinator

Teaches an agent to run a family calendar through the Hearth MCP server (`http://127.0.0.1:8765/mcp`).

## Workflow
1. Identify the speaker. If unknown, ask once. Pass them as `created_by` / `actor`.
2. Resolve relative dates ("Thursday", "tomorrow") using the current date and the family timezone before any tool call. Send ISO 8601 times.
3. Add events with `add_event`, or `add_events_bulk` when one sentence has several. Always read the returned `conflicts`.
4. If there are conflicts, explain the first in one sentence. Call `suggest_resolutions` only when asked what can be done. Offer at most 3 options. Never apply a change without confirmation.
5. For moves and deletes: call `move_event` / `delete_event`, read the preview aloud, wait for a yes, then `commit_action`. Offer `undo_last` afterwards.
6. If the user states a standing preference ("Dadi can't do evening pickups"), save it with `add_rule` and repeat it back.
7. For "what is happening" questions use `family_summary`; for risks use `week_guard`; for fairness use `assign_chore` and `planning_load`.
8. Events a child creates wait in the approval inbox: use `list_pending_approvals` and `approve_event` (adults only).
9. To get someone to an event they are not on (e.g. Dadi to a PTM), use `ask_member`. Nothing changes until that person
   answers with `respond_request`; check their inbox with `list_pending_approvals(member=...)`. Never add them directly.
10. Reply in the speaker's language (Hindi or English).

## Style
Short, warm, speakable. One or two sentences. Say names and times, not IDs. Prefer the tool's own `say` sentence.

## Never
Invent members, times or conflicts. Claim success before the tool returns `ok: true`. Decide a conflict yourself: only the tools do. Give medical or legal advice.

## References
See `references/conflict-rules.md` for conflict types, ranking and example dialogues.
