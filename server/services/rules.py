"""Family rules: structured, learned from speech, enforced by the engine."""
from __future__ import annotations

import json
import re

from family_conflicts import Rule, describe_rule
from sqlmodel import Session, select

from ..models import FamilyRule
from . import common as c
from .common import HearthError

KINDS = ("no_after", "no_before", "no_task")


def _norm_time(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", v)
    if m:
        h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
        if m.group(3) == "pm":
            h += 12
        return f"{h:02d}:{mi:02d}"
    raise HearthError("bad_time", f"I couldn't read '{value}' as a time. Try something like 17:00 or 5 pm.")


def rule_dict(s: Session, r: FamilyRule) -> dict:
    p = json.loads(r.params_json or "{}")
    name = c.find_member(s, r.member_id).name
    return {
        "id": r.id, "member": name, "kind": r.kind, "time": p.get("time"), "task": p.get("task"),
        "source_text": r.source_text,
        "description": describe_rule(Rule(r.id, r.member_id, r.kind, p), name),
    }


def add_rule(s: Session, member: str, kind: str, time: str | None = None, task: str | None = None,
             source_text: str = ""):
    if kind not in KINDS:
        raise HearthError("bad_kind", f"Rule kind must be one of {', '.join(KINDS)}.")
    m = c.find_member(s, member)
    t = _norm_time(time)
    task = task.strip().lower() if task else None
    if kind in ("no_after", "no_before") and not t:
        raise HearthError("missing_time", "From what time should that rule apply?")
    if kind == "no_task" and not task:
        raise HearthError("missing_task", "Which task is it that they can't do?")
    r = FamilyRule(member_id=m.id, kind=kind, params_json=json.dumps({"time": t, "task": task}),
                   source_text=source_text or "")
    s.add(r)
    s.commit()
    d = rule_dict(s, r)
    existing = [x for x in c.conflicts_for(s) if x.id.startswith("c-RUL-") and x.id.endswith(f"-{r.id}")]
    say = f"Got it: {d['description']}. I'll check every plan against that."
    if existing:
        say += f" Heads up, {existing[0].why}"
    return {"rule": d, "existing_conflicts": c.conflict_dicts(existing), "say": say}


def list_rules(s: Session):
    rows = s.exec(select(FamilyRule).where(FamilyRule.active).order_by(FamilyRule.id)).all()
    rules = [rule_dict(s, r) for r in rows]
    say = "No family rules yet." if not rules else "Rules: " + "; ".join(r["description"] for r in rules) + "."
    return {"rules": rules, "say": say}


def remove_rule(s: Session, rule_id: int):
    r = s.get(FamilyRule, int(rule_id))
    if r is None or not r.active:
        raise HearthError("rule_not_found", "I can't find that rule.")
    d = rule_dict(s, r)
    r.active = False
    s.add(r)
    s.commit()
    return {"ok": True, "say": f"Removed: {d['description']}."}
