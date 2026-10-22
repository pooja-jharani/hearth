"""Golden scenario: replay the exact demo script through the mock agent and the real MCP server,
then check the final database state."""
import sqlite3
from datetime import date

from app.agent import HearthAgent
from app.nlu import parse_event, parse_rule


def say(agent, state, who, text):
    return agent.respond(who, text, state)


def rows(db, sql):
    with sqlite3.connect(db) as c:
        return c.execute(sql).fetchall()


def test_golden_demo_script(server, backend):
    url, db = server
    agent, st = HearthAgent(backend, "mock"), {}

    r = say(agent, st, "Mom", "Tuesday gym at 7, Wednesday tuition 6 to 7, Friday Nani's birthday dinner")
    assert [e.name for e in r.events] == ["add_events_bulk"] and "Added 3 events" in r.text

    r = say(agent, st, "Mom", "Rohan's PTM is Thursday at 5 at school")
    assert r.events[0].result["event"]["needs_adult"] and r.events[0].result["conflicts"] == []

    r = say(agent, st, "Dad", "I have a client call Thursday 5 to 6")
    assert r.events[0].result["conflicts"][0]["type"] == "COVERAGE_CLASH"
    assert "both Mom and Dad are busy" in r.text

    r = say(agent, st, "Dad", "What can we do?")
    opts = r.events[0].result["options"]
    assert [o["kind"] for o in opts] == ["move", "add_attendee", "keep"]

    r = say(agent, st, "Dad", "Move the call to 6:30")
    assert r.events[0].name == "list_events" and r.events[-1].name == "move_event"
    assert st["pending_id"] and "Say yes to confirm" in r.text

    r = say(agent, st, "Dad", "yes")
    assert r.events[0].name == "commit_action" and "No clashes left" in r.text and st["pending_id"] is None

    r = say(agent, st, "Dad", "undo")
    assert "back to" in r.text
    r = say(agent, st, "Dad", "What can we do?")
    r = say(agent, st, "Dad", "option 1")
    assert r.events[-1].name == "move_event"
    say(agent, st, "Dad", "yes")

    r = say(agent, st, "Mom", "Dadi can't do evening pickups")
    assert r.events[0].name == "add_rule" and "Dadi won't do pickups at or after 5 pm" in r.text

    r = say(agent, st, "Mom", "Dadi will pick up Rohan from tuition Friday at 6")
    assert r.events[0].result["conflicts"][0]["type"] == "RULE_VIOLATION"

    r = say(agent, st, "Mom", "Who should do dishes?")
    assert r.events[0].name == "assign_chore" and "points in the last 14 days" in r.text

    r = say(agent, st, "Mom", "What's happening this week?")
    assert r.events[0].name == "family_summary"
    r = say(agent, st, "Mom", "Any risks next week?")
    assert r.events[0].name == "week_guard"

    # final database state
    ev = {t: (s, st_) for t, s, st_ in rows(db, "select title, start_utc, status from event")}
    assert ev["Client call"][0].startswith("2026-10-22 13:00")  # 18:30 IST
    assert ev["Client call"][1] == "active"
    assert ev["Rohan's PTM"][0].startswith("2026-10-22 11:30")  # 17:00 IST, never moved
    assert rows(db, "select count(*) from familyrule where active=1")[0][0] == 1
    assert rows(db, "select count(*) from chore where title='Dishes' and status='open'")[0][0] == 1
    undone = rows(db, "select count(*) from auditlog where undone=1")[0][0]
    assert undone == 1


def test_unknown_input_gets_a_helpful_reply(backend):
    r = HearthAgent(backend, "mock").respond("Mom", "blah blah", {})
    assert "didn't quite catch" in r.text


def test_parsers():
    today = date(2026, 10, 20)
    ev = parse_event("Dadi will pick up Rohan from tuition Friday at 6", "Mom", today)
    assert ev["attendees"] == ["Dadi", "Rohan"] and ev["start"] == "2026-10-23T18:00:00"
    assert parse_event("I have a client call Thursday 5 to 6", "Dad", today)["end"] == "2026-10-22T18:00:00"
    assert parse_rule("Dad won't do school runs after 6 pm")["time"] == "18:00"
    assert parse_rule("hello there") is None


def test_ask_dadi_loop(server, backend):
    """Clash -> options -> 'Ask them' -> Dadi's inbox -> Dadi says yes -> she is attending and the clash is gone."""
    agent, st = HearthAgent(backend, "mock"), {}
    say(agent, st, "Mom", "Rohan's PTM is Thursday at 5 at school")
    say(agent, st, "Dad", "I have a client call Thursday 5 to 6")
    r = say(agent, st, "Dad", "What can we do?")
    opt = next(o for o in r.events[0].result["options"] if o["kind"] == "add_attendee")
    r = agent.apply_option("Dad", opt, st)
    assert r.events[-1].name == "ask_member"
    inbox = backend.call("list_pending_approvals", {"member": "Dadi"})
    assert len(inbox["requests"]) == 1
    r = say(agent, st, "Dadi", "yes")
    assert r.events[0].name == "respond_request"
    assert backend.call("detect_conflicts", {})["conflicts"] == []
    assert backend.call("list_pending_approvals", {"member": "Dadi"})["requests"] == []


def test_decline_request_keeps_clash(server, backend):
    agent, st = HearthAgent(backend, "mock"), {}
    say(agent, st, "Mom", "Rohan's PTM is Thursday at 5 at school")
    say(agent, st, "Dad", "I have a client call Thursday 5 to 6")
    say(agent, st, "Mom", "ask Dadi to attend the PTM")
    r = say(agent, st, "Dadi", "I can't make it")
    assert r.events[0].name == "respond_request"
    assert backend.call("detect_conflicts", {})["conflicts"]
