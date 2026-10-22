"""Hearth: the Streamlit app. Run with `python run.py` (starts the MCP server too)."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import streamlit as st
from streamlit_calendar import calendar

from app import ics, ui, voice
from app.agent import HearthAgent, update_state
from app.backend import MCPBackend
from app.cards import cards_from_events, conflict_cards
from app.embedded import ensure_server
from app.lanes import auto_day_window, focus_window, lanes_html
from app.types import ToolEvent
from server.services.common import TZ, now

st.set_page_config(page_title="Hearth", page_icon="🏠", layout="wide", initial_sidebar_state="collapsed")
st.markdown(ui.CSS, unsafe_allow_html=True)

WRITE_TOOLS = {"add_event", "add_events_bulk", "commit_action", "undo_last", "approve_event", "add_rule",
               "remove_rule", "assign_chore", "complete_chore", "ask_member", "respond_request"}
SAMPLES = ["Rohan's PTM is Thursday at 5 at school", "I have a client call Thursday 5 to 6",
           "What's happening this week?"]


# ------------------------------------------------------------------ services
@st.cache_resource
def _server():
    ensure_server()
    return True


def boot():
    if "backend" in st.session_state:
        return
    _server()
    url = os.getenv("HEARTH_MCP_URL", f"http://127.0.0.1:{os.getenv('HEARTH_PORT', '8765')}/mcp")
    backend = MCPBackend(url)
    try:
        info = backend.handshake()
        members = backend.call("list_members", {})["members"]
    except Exception:  # noqa: BLE001
        st.markdown('<div class="banner bad">I can\'t reach the Hearth server right now. '
                    'Start everything with <code>python run.py</code>, then reload this page.</div>',
                    unsafe_allow_html=True)
        if st.button("Retry"):
            st.rerun()
        st.stop()
    ss = st.session_state
    ss.backend, ss.info = backend, info
    ss.agent = HearthAgent(backend)
    ss.members = {m["name"]: m for m in members}
    ss.agent_state, ss.cards, ss.reply, ss.last_text = {}, [], "", ""
    ss.cal_v, ss.audio = 0, None
    ss.voice_ok = voice.available()


boot()
ss = st.session_state
backend: MCPBackend = ss.backend
agent: HearthAgent = ss.agent


def speaker() -> str:
    return ss.get("speaker") or "Mom"


def set_cards(cards: list[dict]):
    ss.cards = cards


def say_out(text: str):
    ss.reply = text
    if text and ss.get("voice_on", False) and ss.voice_ok:
        audio, why = voice.speak(text)
        ss.audio = audio
        if why:
            ss.voice_note = why


def after_events(events: list[ToolEvent]):
    if any(e.name in WRITE_TOOLS for e in events):
        ss.cal_v += 1


def send(text: str):
    ss.last_text = text
    with st.spinner("Checking the week…"):
        reply = agent.respond(speaker(), text, ss.agent_state)
    cards = cards_from_events(reply.events)
    if reply.error:
        cards = [{"id": "err", "kind": "error", "text": reply.text, "retry": True}]
    set_cards(cards)
    say_out(reply.text)
    after_events(reply.events)


# ----------------------------------------------------------- card callbacks
def run_tool(name: str, args: dict) -> list[ToolEvent]:
    r = backend.call(name, args)
    ev = [ToolEvent(name, args, r)]
    update_state(ss.agent_state, ev)
    after_events(ev)
    return ev


def on_suggest(cid: str):
    ev = run_tool("suggest_resolutions", {"conflict_id": cid})
    set_cards(cards_from_events(ev))
    say_out(ev[0].result.get("say", ""))


def on_option(opt: dict):
    reply = agent.apply_option(speaker(), opt, ss.agent_state)
    set_cards(cards_from_events(reply.events) if reply.events else [])
    say_out(reply.text)


def on_confirm(pid: int):
    ev = run_tool("commit_action", {"pending_action_id": pid})
    set_cards(cards_from_events(ev))
    say_out(ev[0].result.get("say", ""))


def on_cancel():
    ss.agent_state["pending_id"] = None
    set_cards([])
    say_out("Okay, I've left everything as it was.")


def on_undo():
    ev = run_tool("undo_last", {"actor": speaker()})
    set_cards(cards_from_events(ev))
    say_out(ev[0].result.get("say", ""))


def on_approve(eid: int):
    ev = run_tool("approve_event", {"event_id": eid, "actor": speaker()})
    set_cards(cards_from_events(ev))
    say_out(ev[0].result.get("say", ""))


def on_answer(rid: int, accept: bool):
    ev = run_tool("respond_request", {"request_id": rid, "actor": speaker(), "accept": accept})
    set_cards(cards_from_events(ev))
    say_out(ev[0].result.get("say", ""))


def on_complete(cid: int):
    ev = run_tool("complete_chore", {"chore_id": cid})
    say_out(ev[0].result.get("say", ""))


def on_add_chore():
    title = ss.get("new_chore", "").strip()
    if not title:
        return
    ev = run_tool("assign_chore", {"title": title, "effort": ss.get("new_effort", 2),
                                   "kid_ok": ss.get("new_kid_ok", False)})
    set_cards(cards_from_events(ev))
    say_out(ev[0].result.get("say", ""))
    ss.new_chore = ""


def on_review(conflicts: list[dict]):
    set_cards(conflict_cards(conflicts)[:5])
    say_out(conflicts[0]["why"] if conflicts else "")


def on_sample(text: str):
    send(text)


def on_circular():
    text = ss.get("circular_text", "").strip()
    if text:
        send("Circular from school:\n" + text)


def on_import_ics():
    f = ss.get("ics_file")
    if f is None:
        return
    try:
        parsed = ics.import_ics(f.getvalue().decode("utf-8", "replace"), TZ)
    except Exception:  # noqa: BLE001
        say_out("I couldn't read that calendar file.")
        return
    evs = [e for e in parsed["events"] if not e["all_day"]][:30]
    skipped = len(parsed["skipped"]) + len(parsed["events"]) - len(evs)
    if not evs:
        say_out("I found no timed events in that file." + (f" {skipped} were skipped." if skipped else ""))
        return
    payload = [{"title": e["title"], "start": e["start"], "end": e["end"], "location": e["location"],
                "attendees": [speaker()]} for e in evs]
    ev = run_tool("add_events_bulk", {"events": payload, "created_by": speaker()})
    set_cards(cards_from_events(ev))
    say_out(ev[0].result.get("say", "Imported.") + (f" Skipped {skipped} (repeating, all-day or unreadable)." if skipped else ""))


# ------------------------------------------------------------------- render
def members_html(names: list[str]) -> str:
    return ui.chips(names, ss.members)


def render_card(card: dict, kp: str = ""):
    k, cid = card["kind"], card["id"]
    with st.container(border=True):
        if k == "event":
            e = card["event"]
            note = ""
            if card.get("assumed"):
                note += '<span class="pill">assumed 1 hour</span>'
            if card.get("approval") or e.get("status") == "pending_approval":
                note += '<span class="pill red">waiting for a parent</span>'
            if e.get("needs_adult"):
                note += '<span class="pill">needs an adult</span>'
            st.markdown(f'<div class="card-title">{ui.esc(e["title"])}</div>'
                        f'<div class="card-sub">{ui.when(e["start"], e["end"])}'
                        f'{" · " + ui.esc(e["location"]) if e.get("location") else ""}</div>'
                        f'<div style="margin-top:.4rem">{members_html(e["attendees"])}</div>'
                        f'<div style="margin-top:.3rem">{note}</div>', unsafe_allow_html=True)
        elif k == "bulk":
            st.markdown(f'<div class="card-title">Added {len(card["events"])} events</div>', unsafe_allow_html=True)
            for e in card["events"]:
                st.markdown(f'<div class="card-sub"><b>{ui.esc(e["title"])}</b> · {ui.when(e["start"], e["end"])} '
                            f'· {members_html(e["attendees"])}</div>', unsafe_allow_html=True)
            for f in card["failed"]:
                st.markdown(f'<div class="why">Couldn\'t add {ui.esc(f.get("title") or "one item")}: '
                            f'{ui.esc(f["error"]["message"])}</div>', unsafe_allow_html=True)
        elif k == "conflict":
            c = card["conflict"]
            label = {"COVERAGE_CLASH": "Needs an adult", "PERSON_CLASH": "Double-booked",
                     "RULE_VIOLATION": "Breaks a family rule"}.get(c["type"], "Clash")
            st.markdown(f'<span class="pill red">{label}</span>'
                        f'<div class="why" style="margin-top:.35rem">{ui.esc(c["why"])}</div>'
                        f'<div style="margin-top:.4rem">{members_html(c["people"])}</div>', unsafe_allow_html=True)
            tl = mini_timeline(c["event_ids"], conflicts=[c])
            if tl:
                st.markdown(tl, unsafe_allow_html=True)
            st.button("What can we do?", key=f"{kp}sug-{cid}", on_click=on_suggest, args=(c["id"],))
        elif k == "options":
            st.markdown(f'<div class="card-title">Ways to fix it</div>'
                        f'<div class="card-sub">{ui.esc(card["conflict"]["why"])}</div>', unsafe_allow_html=True)
            for o in card["options"]:
                st.markdown(f'<div style="margin:.5rem 0 .15rem"><b>{o["rank"]}. {ui.esc(o["label"])}</b></div>'
                            f'<div class="card-sub">{ui.esc(o["reason"])}</div>', unsafe_allow_html=True)
                btn = {"move": "Move it", "add_attendee": o["label"].split(" to ")[0], "reassign": "Switch it",
                       "keep": "Keep as is"}[o["kind"]]
                st.button(btn, key=f"{kp}opt-{cid}-{o['rank']}", on_click=on_option, args=(o,))
        elif k == "confirm":
            p = card["preview"]
            st.markdown(f'<div class="card-title">{ui.esc(card["text"].replace(" Say yes to confirm.", ""))}</div>',
                        unsafe_allow_html=True)
            for c in p.get("new_conflicts", []):
                st.markdown(f'<div class="why">{ui.esc(c["why"])}</div>', unsafe_allow_html=True)
            if p.get("kind") == "move" and p.get("event_id") in EVENTS:
                after = {**EVENTS[p["event_id"]], "start": p["to"], "end": p["to_end"],
                         "attendees": p["attendees_after"]}
                st.caption("How it will look")
                st.markdown(mini_timeline([p["event_id"]], replace=after, conflicts=p.get("new_conflicts", [])),
                            unsafe_allow_html=True)
            a, b = st.columns(2)
            a.button("Yes, do it", key=f"{kp}yes-{cid}", type="primary", on_click=on_confirm, args=(card["pending_id"],))
            b.button("Cancel", key=f"{kp}no-{cid}", on_click=on_cancel)
        elif k == "done":
            ok = not card.get("conflicts")
            st.markdown(f'<span class="pill{"" if ok else " red"}">{"All clear" if ok else "Still a clash"}</span>'
                        f'<div class="card-title" style="margin-top:.35rem">{ui.esc(card["text"])}</div>',
                        unsafe_allow_html=True)
            if card.get("undo"):
                st.button("Undo", key=f"{kp}undo-{cid}", on_click=on_undo)
        elif k == "rule":
            r = card["rule"]
            st.markdown(f'<span class="pill">New family rule</span>'
                        f'<div class="card-title" style="margin-top:.35rem">{ui.esc(r["description"])}</div>'
                        f'<div class="card-sub">“{ui.esc(r["source_text"])}”. Every plan is checked against it.</div>',
                        unsafe_allow_html=True)
        elif k == "rules":
            st.markdown('<div class="card-title">Family rules</div>', unsafe_allow_html=True)
            for r in card["rules"] or []:
                st.markdown(f'<div class="card-sub">• {ui.esc(r["description"])}</div>', unsafe_allow_html=True)
            if not card["rules"]:
                st.caption("No rules yet. Try saying “Dadi can't do evening pickups”.")
        elif k == "chore":
            c = card["chore"]
            st.markdown(f'<div class="card-title">{ui.esc(c["title"])} → {members_html([c["assigned_to"]])}</div>'
                        f'<div class="card-sub">{ui.esc(card["reason"])}</div>', unsafe_allow_html=True)
        elif k == "chores":
            st.markdown('<div class="card-title">Open chores</div>', unsafe_allow_html=True)
            for c in card["chores"]:
                st.markdown(f'<div class="card-sub">• {ui.esc(c["title"])} · {ui.esc(c["assigned_to"] or "nobody")}</div>',
                            unsafe_allow_html=True)
        elif k == "summary":
            d = card["data"]
            st.markdown(f'<div class="card-title">{ui.esc(d["label"])}</div>'
                        f'<span class="pill">{d["counts"]["events"]} events</span>'
                        f'<span class="pill{" red" if d["counts"]["conflicts"] else ""}">{d["counts"]["conflicts"]} clashes</span>'
                        f'<span class="pill">{d["counts"]["open_chores"]} open chores</span>', unsafe_allow_html=True)
            for h in d["highlights"]:
                st.markdown(f'<div class="card-sub">• {ui.esc(h)}</div>', unsafe_allow_html=True)
        elif k == "guard":
            d = card["data"]
            st.markdown(f'<div class="card-title">Week Guard · next {d["days"]} days</div>', unsafe_allow_html=True)
            if not d["risks"]:
                st.markdown('<span class="pill">All clear</span>', unsafe_allow_html=True)
            for r in d["risks"][:5]:
                red = r["severity"] == "high"
                st.markdown(f'<div style="margin:.3rem 0"><span class="pill{" red" if red else ""}">{ui.esc(r["severity"])}</span>'
                            f'{ui.esc(r["why"])}</div>', unsafe_allow_html=True)
        elif k == "slots":
            st.markdown('<div class="card-title">Free times</div>', unsafe_allow_html=True)
            for s in card["slots"]:
                st.markdown(f'<div class="card-sub">• {ui.when(s["start"], s["end"])}</div>', unsafe_allow_html=True)
            if not card["slots"]:
                st.caption(card["text"])
        elif k == "approvals":
            st.markdown('<div class="card-title">Inbox</div>', unsafe_allow_html=True)
            if not card["events"] and not card.get("requests"):
                st.caption("Nothing waiting.")
            for e in card["events"]:
                st.markdown(f'<div class="card-sub">Approve: {ui.esc(e["title"])} · {ui.esc(e["created_by"])}</div>',
                            unsafe_allow_html=True)
            for r in card.get("requests", []):
                st.markdown(f'<div class="card-sub">{ui.esc(r["from"])} asked {ui.esc(r["to"])} to come to '
                            f'{ui.esc(r["event"]["title"])}</div>', unsafe_allow_html=True)
        elif k == "asked":
            r = card["request"]
            st.markdown(f'<span class="pill">Request sent</span>'
                        f'<div class="card-title" style="margin-top:.35rem">Asked {members_html([r["to"]])}</div>'
                        f'<div class="card-sub">{ui.esc(r["event"]["title"])} · {ui.when(r["event"]["start"], r["event"]["end"])}'
                        f'</div><div class="card-sub">Nothing changes until {ui.esc(r["to"])} answers. '
                        f'Switch to {ui.esc(r["to"])} above to answer.</div>', unsafe_allow_html=True)
        elif k == "load":
            d = card["data"]
            st.markdown(f'<div class="card-title">Planning load · {d["days"]} days</div>'
                        f'<div class="card-sub">{ui.esc(d["say"])}</div>', unsafe_allow_html=True)
            top = max([m["organised"] for m in d["per_member"]] + [1])
            for m in d["per_member"]:
                st.markdown(f'<div style="margin-top:.4rem">{members_html([m["member"]])} '
                            f'<span class="card-sub">{m["organised"]} organised · {m["events"]} events · '
                            f'{m["hours"]} h · {m["chore_points"]} chore pts</span>'
                            f'<div class="bar"><span style="width:{100 * m["organised"] / top}%"></span></div></div>',
                            unsafe_allow_html=True)
        elif k == "error":
            st.markdown(f'<div class="why">{ui.esc(card["text"])}</div>', unsafe_allow_html=True)
            if card.get("retry"):
                st.button("Retry", key=f"{kp}retry-{cid}", on_click=lambda: send(ss.last_text))
        else:
            st.markdown(f'<div class="card-title">{ui.esc(card.get("title", ""))}</div>'
                        f'<div class="card-sub">{ui.esc(card.get("text", ""))}</div>', unsafe_allow_html=True)


def week_window():
    t = now().astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return t - timedelta(days=2), t + timedelta(days=21)


EVENTS: dict[int, dict] = {}
CONS: list[dict] = []
CHORES: dict = {}
INBOX: dict = {}


def refresh():
    """Read the calendar once per run through MCP; every view below draws from this snapshot."""
    lo, hi = week_window()
    args = {"from_time": lo.isoformat(), "to_time": hi.isoformat()}
    evs = backend.call("list_events", args).get("events", [])
    EVENTS.clear()
    EVENTS.update({e["id"]: e for e in evs})
    CONS[:] = backend.call("detect_conflicts", args).get("conflicts", [])
    CHORES.clear()
    CHORES.update(backend.call("list_chores", {}))
    INBOX.clear()
    INBOX.update(backend.call("list_pending_approvals", {}))


def my_requests() -> list[dict]:
    return [r for r in INBOX.get("requests", []) if r["to"] == speaker()]


def render_request_card(r: dict, kp: str):
    with st.container(border=True):
        e = r["event"]
        st.markdown(f'<span class="pill red">{ui.esc(r["from"])} is asking you</span>'
                    f'<div class="card-title" style="margin-top:.35rem">Can you come to {ui.esc(e["title"])}?</div>'
                    f'<div class="card-sub">{ui.when(e["start"], e["end"])}'
                    f'{" · " + ui.esc(e["location"]) if e.get("location") else ""}</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        a.button("Yes, I'll go", key=f"{kp}rq-yes-{r['id']}", type="primary", on_click=on_answer, args=(r["id"], True))
        b.button("Can't make it", key=f"{kp}rq-no-{r['id']}", on_click=on_answer, args=(r["id"], False))


def mini_timeline(ids: list[int], replace: dict | None = None, conflicts: list[dict] | None = None) -> str:
    """A small per-person timeline around some events; `replace` previews a changed event."""
    base = [EVENTS[i] for i in ids if i in EVENTS]
    if replace:
        base = [e for e in base if e["id"] != replace["id"]] + [replace]
    if not base:
        return ""
    lo, hi = focus_window(base, TZ)
    ctx = []
    for e in EVENTS.values():
        if replace and e["id"] == replace["id"]:
            continue
        if datetime.fromisoformat(e["start"]) < hi and datetime.fromisoformat(e["end"]) > lo:
            ctx.append(e)
    if replace:
        ctx.append(replace)
    return lanes_html(ctx, list(ss.members.values()), conflicts or [], TZ, (lo, hi), compact=True,
                      aria_label="Timeline of the events involved")


def calendar_events() -> tuple[list[dict], dict]:
    clash_ids = {i for c in CONS for i in c["event_ids"]}
    out = []
    for e in EVENTS.values():
        first = ss.members.get(e["attendees"][0]) if len(e["attendees"]) == 1 else None
        color = first["color"] if first else "#5B6770"
        pending = e["status"] == "pending_approval"
        clash = e["id"] in clash_ids
        out.append({
            "id": str(e["id"]), "title": ("! " if clash else "") + ("(pending) " if pending else "") + e["title"],
            "start": e["start"], "end": e["end"], "backgroundColor": "#FDECEA" if clash else color,
            "borderColor": "#B42318" if clash else color, "textColor": "#B42318" if clash else "#FFFFFF",
            "classNames": ["pending"] if pending else [],
        })
    return out, {"clashes": CONS}


def render_panel(kp: str):
    for r in my_requests():
        render_request_card(r, kp)
    if ss.cards:
        for card in ss.cards:
            render_card(card, kp)
    else:
        with st.container(border=True):
            st.markdown('<div class="card-title">Say something to get started</div>'
                        '<div class="card-sub">Add plans, ask what\'s coming up, or tell me a family rule. '
                        'I check every change for clashes.</div>', unsafe_allow_html=True)
            for i, s in enumerate(SAMPLES):
                st.button(s, key=f"{kp}sample-{i}", on_click=on_sample, args=(s,))


def shift_day(n: int):
    ss.day = (ss.get("day") or now().astimezone(TZ).date()) + timedelta(days=n)


def reset_day():
    ss.day = now().astimezone(TZ).date()


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### Settings")
    st.toggle("Elder mode (bigger text, fewer things)", key="elder")
    st.toggle("Speak replies (Amazon Polly)", key="voice_on", disabled=not ss.voice_ok,
              help="Needs AWS credentials" if not ss.voice_ok else None)
    if not ss.voice_ok:
        st.caption("Voice is off: no AWS credentials found. Text works the same.")
    st.caption(f"Reply engine: **{agent.provider}**")
    with st.expander("School circular"):
        st.text_area("Paste the text of a circular", key="circular_text", height=120,
                     placeholder="Annual Day on Nov 5 at 10 am\nPTM on Nov 12 at 4 pm")
        st.button("Add its events", on_click=on_circular)
    with st.expander("Calendar file (.ics)"):
        st.download_button("Download family calendar", data=ics.export_ics(list(EVENTS.values())),
                           file_name="hearth-family.ics", mime="text/calendar", disabled=not EVENTS)
        st.file_uploader("Import a calendar file", type=["ics"], key="ics_file")
        st.button("Add its events", key="ics-add", on_click=on_import_ics)
    st.toggle("Under the hood", key="hood", help="Show the raw MCP traffic")

if ss.get("elder"):
    st.markdown(ui.ELDER_CSS, unsafe_allow_html=True)

# ------------------------------------------------------------- input first
prompt = st.chat_input("Tell the family calendar something…")
if prompt:
    send(prompt)
refresh()

# ------------------------------------------------------------------- header
h1, h2 = st.columns([1, 2])
with h1:
    st.markdown('<h1 class="hearth">Hearth</h1><div class="tagline">The family calendar that talks back.</div>',
                unsafe_allow_html=True)
with h2:
    st.pills("Speaking as", list(ss.members), default="Mom", key="speaker", label_visibility="collapsed")
    st.markdown(f'<div class="tagline">Speaking as {members_html([speaker()])}</div>', unsafe_allow_html=True)

inbox_n = len(my_requests()) + (len(INBOX.get("events", [])) if ss.members[speaker()]["is_adult"] else 0)
tab_today, tab_week, tab_chores, tab_inbox = st.tabs(
    ["Today", "Week", "Chores", f"Inbox ({inbox_n})" if inbox_n else "Inbox"])

with tab_today:
    today_d = now().astimezone(TZ).date()
    day: date = ss.get("day") or today_d
    n1, n2, n3, n4 = st.columns([0.6, 0.6, 5, 1])
    n1.button("‹", key="day-prev", on_click=shift_day, args=(-1,), help="Previous day")
    n2.button("›", key="day-next", on_click=shift_day, args=(1,), help="Next day")
    n3.markdown(f'<div class="card-title" style="padding-top:.45rem;font-size:1.15rem">'
                f'{"Today, " if day == today_d else ""}{day.strftime("%A %d %B")}</div>', unsafe_allow_html=True)
    n4.button("Today", key="day-today", on_click=reset_day)
    day_evs = sorted((e for e in EVENTS.values() if e["start"][:10] == day.isoformat()), key=lambda e: e["start"])
    day_ids = {e["id"] for e in day_evs}
    day_cons = [c for c in CONS if set(c["event_ids"]) & day_ids]
    upcoming = [e for e in day_evs if day != today_d or datetime.fromisoformat(e["end"]) > now().astimezone(TZ)]
    h_a, h_b, h_c = st.columns(3)
    with h_a, st.container(border=True):
        st.markdown('<div class="card-sub">Next up</div>', unsafe_allow_html=True)
        if upcoming:
            e = upcoming[0]
            st.markdown(f'<div class="card-title">{ui.esc(e["title"])}</div>'
                        f'<div class="card-sub">{ui.when(e["start"], e["end"])}</div>'
                        f'<div style="margin-top:.3rem">{members_html(e["attendees"])}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="card-title">Nothing more planned</div>', unsafe_allow_html=True)
    with h_b, st.container(border=True):
        st.markdown('<div class="card-sub">Needs attention</div>', unsafe_allow_html=True)
        if day_cons:
            st.markdown(f'<div class="why">{ui.esc(day_cons[0]["why"])}</div>', unsafe_allow_html=True)
            st.button("Review", key="today-review", on_click=on_review, args=(day_cons,))
        else:
            st.markdown('<span class="pill">All clear</span>', unsafe_allow_html=True)
    with h_c, st.container(border=True):
        st.markdown('<div class="card-sub">Chores open</div>', unsafe_allow_html=True)
        open_c = [c for c in CHORES.get("chores", []) if c["status"] == "open"]
        if open_c:
            st.markdown(f'<div class="card-title">{len(open_c)} open</div>'
                        f'<div class="card-sub">{ui.esc(open_c[0]["title"])} · {ui.esc(open_c[0]["assigned_to"] or "nobody")}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<span class="pill">All done</span>', unsafe_allow_html=True)
    t_left, t_right = st.columns([3, 2], gap="large")
    with t_left:
        st.markdown("##### Who is where")
        if ss.get("elder"):
            for e in day_evs:
                st.markdown(f"**{ui.when(e['start'], e['end'])}**  \n{e['title']}")
            if not day_evs:
                st.write("Nothing planned.")
        else:
            st.markdown(lanes_html(day_evs, list(ss.members.values()), day_cons, TZ, auto_day_window(day_evs, day, TZ),
                                   now_dt=now().astimezone(TZ) if day == today_d else None),
                        unsafe_allow_html=True)
            if not day_evs:
                st.caption("A free day. Say something like “Dentist at 10 am” to add a plan.")
    with t_right:
        render_panel("t-")

with tab_week:
    cal_events, meta = calendar_events()
    soon = [c for c in meta["clashes"]]
    if soon:
        b1, b2 = st.columns([5, 1])
        b1.markdown(f'<div class="banner bad">! {len(soon)} clash{"es" if len(soon) != 1 else ""} coming up. '
                    f'{ui.esc(soon[0]["why"])}</div>', unsafe_allow_html=True)
        b2.button("Review", on_click=on_review, args=(soon,))
    else:
        st.markdown('<div class="banner ok">No clashes coming up.</div>', unsafe_allow_html=True)

    left, right = st.columns([3, 2], gap="large")
    with left:
        if ss.get("elder"):
            st.markdown("#### Today and tomorrow")
            lo = now().astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            day_evs = backend.call("list_events", {"from_time": lo.isoformat(),
                                                   "to_time": (lo + timedelta(days=2)).isoformat()}).get("events", [])
            for e in day_evs or []:
                st.markdown(f"**{ui.when(e['start'], e['end'])}**  \n{e['title']}")
            if not day_evs:
                st.write("Nothing planned.")
        else:
            lo, _ = week_window()
            today = now().astimezone(TZ).date().isoformat()
            calendar(events=cal_events, key=f"cal-{ss.cal_v}", options={
                "initialView": "timeGridWeek", "initialDate": today, "height": 600, "scrollTime": "14:00:00", "nowIndicator": True,
                "slotMinTime": "07:00:00", "slotMaxTime": "22:00:00", "allDaySlot": False,
                "headerToolbar": {"left": "prev,next today", "center": "title", "right": "timeGridWeek,listWeek"},
                "timeZone": str(TZ), "firstDay": 1, "expandRows": True, "eventDisplay": "block",
            }, custom_css=".fc-event.pending{opacity:.65;border-style:dashed !important}"
                         ".fc{font-size:.85rem}.fc-toolbar-title{font-size:1.05rem !important}")
    with right:
        render_panel("w-")

with tab_chores:
    data = CHORES
    scores = data.get("scores", {})
    top = max(list(scores.values()) + [1])
    st.markdown("##### Who has carried the load (last 14 days)")
    for name, pts in scores.items():
        st.markdown(f'{members_html([name])} <span class="card-sub">{pts} points</span>'
                    f'<div class="bar"><span style="width:{100 * pts / top}%"></span></div>', unsafe_allow_html=True)
    st.markdown("##### Open chores")
    open_chores = [c for c in data.get("chores", []) if c["status"] == "open"]
    if not open_chores:
        st.caption("Nothing open. Try “Who should do dishes?”")
    for c in open_chores:
        a, b = st.columns([4, 1])
        a.markdown(f'**{ui.esc(c["title"])}** · {members_html([c["assigned_to"]]) if c["assigned_to"] else "nobody"}',
                   unsafe_allow_html=True)
        b.button("Done", key=f"done-{c['id']}", on_click=on_complete, args=(c["id"],))
    with st.expander("Add a chore"):
        st.text_input("Chore", key="new_chore")
        st.slider("Effort (points)", 1, 5, 2, key="new_effort")
        st.checkbox("Fine for kids", key="new_kid_ok")
        st.button("Assign fairly", on_click=on_add_chore)

with tab_inbox:
    adult = ss.members[speaker()]["is_adult"]
    pend = INBOX.get("events", [])
    mine = my_requests()
    if not pend and not mine:
        st.caption("Nothing is waiting. Requests for you and events that Rohan adds show up here.")
    for r in mine:
        render_request_card(r, "i-")
    for e in pend:
        with st.container(border=True):
            st.markdown(f'**{ui.esc(e["title"])}** · {ui.when(e["start"], e["end"])} · from {members_html([e["created_by"]])}',
                        unsafe_allow_html=True)
            if adult:
                st.button("Approve", key=f"appr-{e['id']}", on_click=on_approve, args=(e["id"],))
            else:
                st.caption("Only a grown-up can approve this.")

# -------------------------------------------------------------------- reply
if ss.reply:
    st.markdown(f'<div class="reply">{ui.esc(ss.reply)}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="reply empty">Hearth will answer here, in plain words.</div>', unsafe_allow_html=True)
if ss.get("audio"):
    st.audio(ss.audio, format="audio/mp3", autoplay=True)
    ss.audio = None
if ss.get("voice_note"):
    st.caption(f"Voice skipped: {ss.voice_note}")
    ss.voice_note = None

# ------------------------------------------------------------ protocol view
if ss.get("hood") and not ss.get("elder"):
    st.markdown("---")
    st.markdown("#### Under the hood: Protocol Inspector")
    st.caption(f"Standalone MCP server at `{backend.url}` · negotiated protocol version "
               f"**{ss.info['protocolVersion']}** · server **{ss.info['serverInfo']['name']}** "
               f"{ss.info['serverInfo'].get('version', '')}. Raw JSON-RPC, newest first.")
    shown = 0
    for item in reversed(backend.trace):
        msg = item["msg"]
        label = msg.get("method") or ("result" if "result" in msg else "error")
        if label in ("notifications/initialized",):
            continue
        with st.expander(f'{datetime.fromtimestamp(item["t"]).strftime("%H:%M:%S")} · {item["dir"]} · {label}'
                         + (f' · {msg["params"]["name"]}' if label == "tools/call" else ""), expanded=shown == 0):
            st.code(json.dumps(msg, indent=2)[:4000], language="json")
        shown += 1
        if shown >= 10:
            break
