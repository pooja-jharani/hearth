"""SQLModel tables. All datetimes are stored as naive UTC."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Member(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    role: str  # parent | child | grandparent
    is_adult: bool = True
    color: str = "#0F766E"
    initials: str = ""


class Event(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    start_utc: NaiveDatetime
    end_utc: NaiveDatetime
    location: str | None = None
    needs_adult: bool = False
    movable: bool = True
    created_by: int = Field(foreign_key="member.id")
    status: str = "active"  # active | pending_approval | cancelled
    created_at: NaiveDatetime = Field(default_factory=_utcnow)


class EventAttendee(SQLModel, table=True):
    event_id: int = Field(foreign_key="event.id", primary_key=True)
    member_id: int = Field(foreign_key="member.id", primary_key=True)


class Chore(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    effort: int = 2
    kid_ok: bool = False
    due_date: date | None = None
    assigned_to: int | None = Field(default=None, foreign_key="member.id")
    assigned_at: NaiveDatetime | None = None
    status: str = "open"  # open | done
    completed_at: NaiveDatetime | None = None


class FamilyRule(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="member.id")
    kind: str  # no_after | no_before | no_task
    params_json: str = "{}"
    source_text: str = ""
    active: bool = True


class PendingAction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    kind: str  # move | delete
    payload_json: str
    actor: int | None = None
    created_at: NaiveDatetime = Field(default_factory=_utcnow)
    expires_at: NaiveDatetime
    used: bool = False


class Approval(SQLModel, table=True):
    event_id: int = Field(foreign_key="event.id", primary_key=True)
    requested_by: int = Field(foreign_key="member.id")
    status: str = "pending"  # pending | approved
    decided_by: int | None = None


class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    action: str  # add | add_bulk | move | delete
    before_json: str = "null"
    after_json: str = "null"
    actor: int | None = None
    created_at: NaiveDatetime = Field(default_factory=_utcnow)
    undone: bool = False


class MessageLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    speaker: str
    role: str  # user | assistant
    text: str
    created_at: NaiveDatetime = Field(default_factory=_utcnow)


class HelpRequest(SQLModel, table=True):
    """One person asking another to join an event ("Dad asks Dadi to attend the PTM")."""
    id: int | None = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id")
    from_member: int = Field(foreign_key="member.id")
    to_member: int = Field(foreign_key="member.id")
    status: str = "pending"  # pending | accepted | declined
    created_at: NaiveDatetime = Field(default_factory=_utcnow)
    decided_at: NaiveDatetime | None = None
