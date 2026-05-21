"""
Authorization layer — pure, deterministic functions with no LLM involvement.
These are the security floor of the system.
"""
from src.jira.models import JiraTicket


def usuario_pode_ver(account_id: str, ticket: JiraTicket) -> bool:
    """User can view a ticket if they are the assignee or reporter."""
    if ticket.assignee and ticket.assignee.account_id == account_id:
        return True
    if ticket.reporter and ticket.reporter.account_id == account_id:
        return True
    return False


def usuario_pode_comentar(account_id: str, ticket: JiraTicket) -> bool:
    """User can comment only if they are the assignee or reporter."""
    return usuario_pode_ver(account_id, ticket)
