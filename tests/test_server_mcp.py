"""Every tool through the real Python MCP client against a real server process."""
from conftest import DEMO_NOW  # noqa: F401


def call(backend, name, **kw):
    return backend.call(name, kw)


def test_handshake_negotiates_spec_2025_11_25(backend):
    info = backend.handshake()
    assert info["protocolVersion"] == "2025-11-25"
    assert info["serverInfo"]["name"] == "Hearth"


def test_tools_list_has_expected_tools(backend):
    names = {t["name"] for t in backend.list_tools()}
    expected = {"add_event", "list_events", "detect_conflicts", "find_free_slot", "suggest_resolutions",
                "move_event", "delete_event", "commit_action", "undo_last", "assign_chore", "complete_chore",
                "list_chores", "family_summary", "add_rule", "list_rules", "remove_rule", "add_events_bulk",
                "week_guard", "approve_event", "list_pending_approvals", "planning_load", "list_members"}
    assert expected <= names


def test_raw_json_rpc_is_captured(backend):
    backend.list_tools()
    methods = [m["msg"].get("method") for m in backend.trace if m["dir"] == "client → server"]
    assert "initialize" in methods and "tools/list" in methods


def test_members_and_seed(backend):
    r = call(backend, "list_members")
    assert [m["name"] for m in r["members"]] == ["Mom", "Dad", "Rohan", "Dadi"]
    assert call(backend, "list_events")["events"]  # seeded week


def test_demo_clash_fix_undo(backend):
    r = call(backend, "add_event", title="Rohan's PTM", start="2026-10-22T17:00:00", attendees=["Rohan"],
             needs_adult=True, movable=False, location="school", created_by="Mom")
    assert r["ok"] and r["conflicts"] == [] and r["assumed_duration"]
    r = call(backend, "add_event", title="Client call", start="2026-10-22T17:00:00", end="2026-10-22T18:00:00",
             created_by="Dad")
    assert [c["type"] for c in r["conflicts"]] == ["COVERAGE_CLASH"]
    cid = r["conflicts"][0]["id"]
    ev_id = r["event"]["id"]
    assert "both Mom and Dad are busy" in r["conflicts"][0]["why"]

    opts = call(backend, "suggest_resolutions", conflict_id=cid)["options"]
    assert opts[0]["kind"] == "move" and opts[0]["event_id"] == ev_id
    assert opts[0]["new_start"].startswith("2026-10-22T18:30")

    pend = call(backend, "move_event", event_id=ev_id, new_start=opts[0]["new_start"], actor="Dad")
    # nothing changes until commit
    assert call(backend, "detect_conflicts", from_time="2026-10-22T00:00:00", to_time="2026-10-23T00:00:00")["conflicts"]
    done = call(backend, "commit_action", pending_action_id=pend["pending_action_id"])
    assert done["conflicts_after"] == [] and done["undo_available"]
    assert call(backend, "detect_conflicts", from_time="2026-10-22T00:00:00", to_time="2026-10-23T00:00:00")["conflicts"] == []

    assert "back to" in call(backend, "undo_last")["say"]
    assert len(call(backend, "detect_conflicts", from_time="2026-10-22T00:00:00",
                    to_time="2026-10-23T00:00:00")["conflicts"]) == 1
    # a used pending action cannot be replayed
    again = call(backend, "commit_action", pending_action_id=pend["pending_action_id"])
    assert again["ok"] is False and again["error"]["code"] == "pending_used"


def test_move_with_new_attendee_clears_coverage(backend):
    call(backend, "add_event", title="Rohan's PTM", start="2026-10-22T17:00:00", attendees=["Rohan"],
         needs_adult=True, movable=False, created_by="Mom")
    r = call(backend, "add_event", title="Client call", start="2026-10-22T17:00:00", created_by="Dad")
    ptm = call(backend, "list_events", from_time="2026-10-22T00:00:00", to_time="2026-10-23T00:00:00")
    ptm_id = next(e["id"] for e in ptm["events"] if e["title"] == "Rohan's PTM")
    opts = call(backend, "suggest_resolutions", conflict_id=r["conflicts"][0]["id"])["options"]
    dadi = next(o for o in opts if o["kind"] == "add_attendee")
    assert dadi["event_id"] == ptm_id
    p = call(backend, "move_event", event_id=ptm_id, add_attendee="Dadi", actor="Mom")
    done = call(backend, "commit_action", pending_action_id=p["pending_action_id"])
    assert done["conflicts_after"] == []


def test_learned_rule_is_enforced_later(backend):
    r = call(backend, "add_rule", member="Dadi", kind="no_after", time="17:00", task="pickup",
             source_text="Dadi can't do evening pickups")
    assert r["ok"] and "Dadi won't do pickups at or after 5 pm" in r["say"]
    assert call(backend, "list_rules")["rules"][0]["member"] == "Dadi"
    ok = call(backend, "add_event", title="Rohan school pickup", start="2026-10-23T15:00:00",
              attendees=["Dadi", "Rohan"], created_by="Mom")
    assert ok["conflicts"] == []
    bad = call(backend, "add_event", title="Rohan tuition pickup", start="2026-10-23T18:00:00",
               attendees=["Dadi", "Rohan"], created_by="Mom")
    assert bad["conflicts"][0]["type"] == "RULE_VIOLATION"
    opts = call(backend, "suggest_resolutions", conflict_id=bad["conflicts"][0]["id"])["options"]
    assert opts[0]["kind"] == "reassign"
    assert call(backend, "remove_rule", rule_id=r["rule"]["id"])["ok"]
    assert call(backend, "list_rules")["rules"] == []


def test_chores_fair_assignment_and_complete(backend):
    r = call(backend, "assign_chore", title="Dishes", effort=2, kid_ok=True)
    assert r["chore"]["assigned_to"] in {"Dad", "Rohan"}  # lightest recent load
    assert "points in the last 14 days" in r["reason"]
    adult = call(backend, "assign_chore", title="Pay electricity bill", effort=1)
    assert adult["chore"]["assigned_to"] != "Rohan"  # not kid_ok
    done = call(backend, "complete_chore", chore_id=r["chore"]["id"])
    assert done["chore"]["status"] == "done"
    assert call(backend, "complete_chore", chore_id=r["chore"]["id"])["error"]["code"] == "already_done"
    ls = call(backend, "list_chores", status="open")
    assert all(c["status"] == "open" for c in ls["chores"]) and "Mom" in ls["scores"]


def test_bulk_add_summary_guard_load(backend):
    r = call(backend, "add_events_bulk", created_by="Mom", events=[
        {"title": "Gym", "start": "2026-10-20T19:00:00", "duration_min": 60, "attendees": ["Dad"]},
        {"title": "Tuition", "start": "2026-10-21T18:00:00", "end": "2026-10-21T19:00:00", "attendees": ["Rohan"]},
        {"title": "Nani's birthday dinner", "start": "2026-10-23T19:30:00", "attendees": ["Mom", "Dad", "Rohan"]},
        {"title": "Broken", "start": "not a date"},
    ])
    assert [x["ok"] for x in r["results"]] == [True, True, True, False]
    assert r["results"][3]["error"]["code"] == "bad_date"
    s = call(backend, "family_summary", range="week")
    assert s["counts"]["events"] >= 8 and s["highlights"]
    assert call(backend, "week_guard", days=7)["ok"]
    load = call(backend, "planning_load", days=14)
    assert {m["member"] for m in load["per_member"]} == {"Mom", "Dad", "Rohan", "Dadi"}
    assert call(backend, "undo_last")["undone"] == "add_bulk"
    assert call(backend, "family_summary", range="week")["counts"]["events"] == s["counts"]["events"] - 3


def test_week_guard_flags_clash_and_thin_coverage(backend):
    call(backend, "add_event", title="Rohan's PTM", start="2026-10-22T17:00:00", attendees=["Rohan"],
         needs_adult=True, movable=False, created_by="Mom")
    g = call(backend, "week_guard", days=7)
    assert any(r["type"] == "THIN_COVERAGE" for r in g["risks"])  # only Dad free, Mom has a review
    call(backend, "add_event", title="Client call", start="2026-10-22T17:00:00", created_by="Dad")
    g = call(backend, "week_guard", days=7)
    assert g["risks"][0]["type"] == "COVERAGE_CLASH"
    assert "risk" in g["say"]


def test_child_permissions_and_approval_inbox(backend):
    mom_ev = call(backend, "list_events")["events"][0]
    denied = call(backend, "move_event", event_id=mom_ev["id"], new_start="2026-10-21T10:00:00", actor="Rohan")
    assert denied["ok"] is False and denied["error"]["code"] == "permission"
    assert call(backend, "delete_event", event_id=mom_ev["id"], actor="Rohan")["error"]["code"] == "permission"

    r = call(backend, "add_event", title="Friend's birthday", start="2026-10-24T16:00:00", created_by="Rohan")
    assert r["needs_approval"] and r["event"]["status"] == "pending_approval"
    inbox = call(backend, "list_pending_approvals")
    assert [e["title"] for e in inbox["events"]] == ["Friend's birthday"]
    assert call(backend, "approve_event", event_id=r["event"]["id"], actor="Rohan")["error"]["code"] == "permission"
    ok = call(backend, "approve_event", event_id=r["event"]["id"], actor="Dad")
    assert ok["event"]["status"] == "active"
    assert call(backend, "list_pending_approvals")["events"] == []


def test_delete_flow_and_undo(backend):
    ev = call(backend, "list_events")["events"][0]
    p = call(backend, "delete_event", event_id=ev["id"], actor="Mom")
    call(backend, "commit_action", pending_action_id=p["pending_action_id"])
    assert all(e["id"] != ev["id"] for e in call(backend, "list_events")["events"])
    call(backend, "undo_last")
    assert any(e["id"] == ev["id"] for e in call(backend, "list_events")["events"])


def test_find_free_slot(backend):
    r = call(backend, "find_free_slot", attendees=["Mom", "Dad"], duration_min=60,
             earliest="2026-10-22T16:00:00", latest="2026-10-22T21:00:00")
    assert len(r["slots"]) == 3
    starts = [x["start"][11:16] for x in r["slots"]]
    assert starts == ["16:00", "18:00", "18:30"]  # 16:30 to 17:30 would hit Mom's 5 pm review


def test_structured_errors_never_leak_traces(backend):
    r = call(backend, "add_event", title="x", start="2026-10-22T17:00:00", attendees=["Nobody"], created_by="Mom")
    assert r["ok"] is False and r["error"]["code"] == "unknown_member" and "Traceback" not in r["say"]
    assert call(backend, "add_event", title="x", start="banana", created_by="Mom")["error"]["code"] == "bad_date"
    assert call(backend, "add_event", title="x", start="2026-10-22T17:00:00", end="2026-10-22T16:00:00",
                created_by="Mom")["error"]["code"] == "bad_range"
    assert call(backend, "suggest_resolutions", conflict_id="c-COV-999")["error"]["code"] == "conflict_not_found"
    assert call(backend, "commit_action", pending_action_id=999)["error"]["code"] == "pending_not_found"
    assert call(backend, "add_rule", member="Dadi", kind="no_after", task="pickup")["error"]["code"] == "missing_time"


def _clash(backend):
    call(backend, "add_event", title="Rohan's PTM", start="2026-10-22T17:00:00", attendees=["Rohan"],
         needs_adult=True, movable=False, location="school", created_by="Mom")
    r = call(backend, "add_event", title="Client call", start="2026-10-22T17:00:00", created_by="Dad")
    cid = r["conflicts"][0]["id"]
    opts = call(backend, "suggest_resolutions", conflict_id=cid)["options"]
    ask = next(o for o in opts if o["kind"] == "add_attendee")
    return cid, ask


def test_ask_dadi_accept_clears_clash_and_can_be_undone(backend):
    cid, opt = _clash(backend)
    day = dict(from_time="2026-10-22T00:00:00", to_time="2026-10-23T00:00:00")
    asked = call(backend, "ask_member", event_id=opt["event_id"], member=str(opt["add_member"]), actor="Dad")
    assert asked["ok"] and "asked Dadi" in asked["say"]
    # nothing changes until she answers
    assert len(call(backend, "detect_conflicts", **day)["conflicts"]) == 1
    assert call(backend, "ask_member", event_id=opt["event_id"], member="Dadi", actor="Dad")["error"]["code"] == "already_asked"

    inbox = call(backend, "list_pending_approvals", member="Dadi")
    assert [r["from"] for r in inbox["requests"]] == ["Dad"] and "request" in inbox["say"]
    assert call(backend, "list_pending_approvals", member="Mom")["requests"] == []
    rid = inbox["requests"][0]["id"]

    denied = call(backend, "respond_request", request_id=rid, actor="Mom", accept=True)
    assert denied["ok"] is False and denied["error"]["code"] == "permission"

    done = call(backend, "respond_request", request_id=rid, actor="Dadi", accept=True)
    assert done["ok"] and done["conflicts_after"] == [] and done["undo_available"]
    assert call(backend, "detect_conflicts", **day)["conflicts"] == []
    assert call(backend, "respond_request", request_id=rid, actor="Dadi", accept=True)["error"]["code"] == "already_answered"

    assert "back to" in call(backend, "undo_last")["say"]
    assert len(call(backend, "detect_conflicts", **day)["conflicts"]) == 1


def test_ask_dadi_decline_keeps_clash_and_guards(backend):
    cid, opt = _clash(backend)
    ev = opt["event_id"]
    assert call(backend, "ask_member", event_id=ev, member="Dad", actor="Dad")["error"]["code"] == "self_request"
    assert call(backend, "ask_member", event_id=ev, member="Rohan", actor="Rohan")["error"]["code"] in {"self_request", "permission"}
    r = call(backend, "ask_member", event_id=ev, member="Dadi", actor="Dad")
    out = call(backend, "respond_request", request_id=r["request"]["id"], actor="Dadi", accept=False)
    assert out["ok"] and out["undo_available"] is False and "clash is still there" in out["say"]
    assert call(backend, "list_pending_approvals", member="Dadi")["requests"] == []
    assert len(call(backend, "detect_conflicts", from_time="2026-10-22T00:00:00", to_time="2026-10-23T00:00:00")["conflicts"]) == 1
    # already attending
    other = call(backend, "ask_member", event_id=ev, member="Mom", actor="Dad")
    assert other["ok"]


def test_member_ids_work_as_arguments(backend):
    """suggest_resolutions returns numeric member ids; the tools that apply them must accept ids."""
    cid, opt = _clash(backend)
    p = call(backend, "move_event", event_id=opt["event_id"], add_attendee=opt["add_member"], actor="Mom")
    assert p["ok"], p
