from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel


class JiraUser(BaseModel):
    account_id: str
    display_name: str
    email_address: Optional[str] = None


class JiraComment(BaseModel):
    author: str
    body: str
    created: datetime


class JiraTicket(BaseModel):
    key: str
    summary: str
    project_key: str
    project_name: str
    status: str
    priority: Optional[str] = None
    assignee: Optional[JiraUser] = None
    reporter: Optional[JiraUser] = None
    created: datetime
    updated: datetime
    due_date: Optional[datetime] = None

    @property
    def is_overdue(self) -> bool:
        if self.due_date is None:
            return False
        done_statuses = {"done", "concluído", "resolved", "closed", "cancelado"}
        if self.status.lower() in done_statuses:
            return False
        now = datetime.now(tz=timezone.utc)
        due = self.due_date if self.due_date.tzinfo else self.due_date.replace(tzinfo=timezone.utc)
        return now > due

    @property
    def days_since_update(self) -> int:
        now = datetime.now(tz=timezone.utc)
        upd = self.updated if self.updated.tzinfo else self.updated.replace(tzinfo=timezone.utc)
        return (now - upd).days

    @property
    def days_overdue(self) -> int:
        if not self.is_overdue or self.due_date is None:
            return 0
        now = datetime.now(tz=timezone.utc)
        due = self.due_date if self.due_date.tzinfo else self.due_date.replace(tzinfo=timezone.utc)
        return (now - due).days
