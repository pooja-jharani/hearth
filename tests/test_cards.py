from app.cards import cards_from_events
from app.types import ToolEvent


def test_clash_card_follows_event_card():
    ev = {"id": 1, "title": "Client call", "start": "2026-10-22T17:00:00+05:30", "end": "2026-10-22T18:00:00+05:30",
          "attendees": ["Dad"], "status": "active"}
    cs = [{"id": "c-COV-2", "type": "COVERAGE_CLASH", "why": "x", "people": ["Mom", "Dad"], "event_ids": [2, 1]}]
    out = cards_from_events([ToolEvent("list_events", {}, {"events": []}),
                             ToolEvent("add_event", {}, {"ok": True, "event": ev, "conflicts": cs})])
    assert [c["kind"] for c in out] == ["event", "conflict"]


def test_errors_become_one_calm_card():
    out = cards_from_events([ToolEvent("add_event", {}, {"ok": False, "say": "Which day?"})])
    assert out == [{"id": out[0]["id"], "kind": "error", "text": "Which day?"}]


def test_confirm_and_done_cards():
    out = cards_from_events([
        ToolEvent("move_event", {}, {"ok": True, "pending_action_id": 7, "preview": {"title": "x"}, "say": "Shall I?"}),
        ToolEvent("commit_action", {}, {"ok": True, "say": "Done.", "undo_available": True, "conflicts_after": []})])
    assert [c["kind"] for c in out] == ["confirm", "done"] and out[0]["pending_id"] == 7


def test_language_code():
    from app.voice import language_code
    assert language_code("आज शाम पाँच बजे PTM है") == "hi-IN"
    assert language_code("PTM is at 5 pm") == "en-IN"
    assert language_code("") == "en-IN"
