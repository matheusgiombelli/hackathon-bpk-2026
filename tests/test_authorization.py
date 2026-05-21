"""
Unit tests for the authorization layer — no LLM, no network.
This is the security floor of the system.
"""
from datetime import datetime, timezone, timedelta

import pytest

from src.jira.models import JiraTicket, JiraUser
from src.rules.authorization import usuario_pode_comentar, usuario_pode_ver

NOW = datetime.now(tz=timezone.utc)


def make_user(account_id: str) -> JiraUser:
    return JiraUser(account_id=account_id, display_name=f"User {account_id}")


def make_ticket(
    key: str = "CARM-1",
    assignee_id: str | None = "user-a",
    reporter_id: str | None = "user-b",
    due_days: int | None = None,
    status: str = "In Progress",
) -> JiraTicket:
    due = NOW + timedelta(days=due_days) if due_days is not None else None
    return JiraTicket(
        key=key,
        summary="Test ticket",
        project_key="CARM",
        project_name="Carmel",
        status=status,
        assignee=make_user(assignee_id) if assignee_id else None,
        reporter=make_user(reporter_id) if reporter_id else None,
        created=NOW,
        updated=NOW,
        due_date=due,
    )


# ─── usuario_pode_ver ────────────────────────────────────────────────────────

def test_assignee_can_view():
    ticket = make_ticket(assignee_id="alice", reporter_id="bob")
    assert usuario_pode_ver("alice", ticket) is True


def test_reporter_can_view():
    ticket = make_ticket(assignee_id="alice", reporter_id="bob")
    assert usuario_pode_ver("bob", ticket) is True


def test_unrelated_user_cannot_view():
    ticket = make_ticket(assignee_id="alice", reporter_id="bob")
    assert usuario_pode_ver("carol", ticket) is False


def test_no_assignee_reporter_can_view():
    ticket = make_ticket(assignee_id=None, reporter_id="bob")
    assert usuario_pode_ver("bob", ticket) is True


def test_no_assignee_no_reporter_nobody_can_view():
    ticket = make_ticket(assignee_id=None, reporter_id=None)
    assert usuario_pode_ver("alice", ticket) is False


# ─── usuario_pode_comentar ───────────────────────────────────────────────────

def test_assignee_can_comment():
    ticket = make_ticket(assignee_id="alice", reporter_id="bob")
    assert usuario_pode_comentar("alice", ticket) is True


def test_reporter_can_comment():
    ticket = make_ticket(assignee_id="alice", reporter_id="bob")
    assert usuario_pode_comentar("bob", ticket) is True


def test_unrelated_user_cannot_comment():
    ticket = make_ticket(assignee_id="alice", reporter_id="bob")
    assert usuario_pode_comentar("carol", ticket) is False


# ─── JiraTicket.is_overdue ───────────────────────────────────────────────────

def test_ticket_is_overdue():
    ticket = make_ticket(due_days=-3, status="In Progress")
    assert ticket.is_overdue is True


def test_ticket_not_overdue_future_due():
    ticket = make_ticket(due_days=5, status="In Progress")
    assert ticket.is_overdue is False


def test_done_ticket_not_overdue_even_if_past_due():
    ticket = make_ticket(due_days=-3, status="Done")
    assert ticket.is_overdue is False


def test_no_due_date_not_overdue():
    ticket = make_ticket(due_days=None, status="In Progress")
    assert ticket.is_overdue is False
