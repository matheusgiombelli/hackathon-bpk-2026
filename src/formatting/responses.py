from __future__ import annotations
from typing import List
from src.jira.models import JiraTicket


def format_ticket_list(tickets: List[JiraTicket], total_available: int | None = None) -> str:
    if not tickets:
        return "Nenhum ticket encontrado com os critérios informados."

    lines = []
    for t in tickets:
        status_tag = f"**{t.status}**"
        delay_info = ""
        if t.is_overdue:
            delay_info = f" — ⚠️ atraso de {t.days_overdue} dia(s)"
        elif t.days_since_update >= 7:
            delay_info = f" — sem atualização há {t.days_since_update} dia(s)"

        priority = f" [{t.priority}]" if t.priority else ""
        lines.append(f"• `{t.key}`{priority} — {t.summary} — {status_tag}{delay_info}")

    result = "\n".join(lines)

    if total_available and total_available > len(tickets):
        result += f"\n\n_(mostrando {len(tickets)} de {total_available} tickets. Use filtros para refinar.)_"

    return result


def format_ticket_detail(ticket: JiraTicket) -> str:
    assignee = ticket.assignee.display_name if ticket.assignee else "Não atribuído"
    reporter = ticket.reporter.display_name if ticket.reporter else "—"
    due = ticket.due_date.strftime("%d/%m/%Y") if ticket.due_date else "Sem prazo"
    overdue_line = f"\n⚠️ **Atrasado** há {ticket.days_overdue} dia(s)" if ticket.is_overdue else ""

    return (
        f"**{ticket.key}** — {ticket.summary}\n"
        f"Projeto: {ticket.project_name} (`{ticket.project_key}`)\n"
        f"Status: **{ticket.status}**\n"
        f"Prioridade: {ticket.priority or '—'}\n"
        f"Responsável: {assignee}\n"
        f"Solicitante: {reporter}\n"
        f"Prazo: {due}\n"
        f"Última atualização: há {ticket.days_since_update} dia(s)"
        f"{overdue_line}"
    )


def format_comment_confirmation(ticket_key: str, text: str) -> str:
    return (
        f"Confirma o seguinte comentário no ticket **{ticket_key}**?\n\n"
        f"> {text}\n\n"
        f"Responda **sim** para confirmar ou **não** para cancelar."
    )


def format_comment_success(ticket_key: str) -> str:
    return f"✅ Comentário registrado com sucesso no ticket **{ticket_key}**."


def format_permission_denied(ticket_key: str, action: str = "visualizar") -> str:
    return f"❌ Você não tem permissão para {action} o ticket **{ticket_key}**."


def format_ticket_not_found(ticket_key: str) -> str:
    return f"Ticket **{ticket_key}** não encontrado ou não acessível."


def format_jira_unavailable() -> str:
    return "⚠️ Não consegui acessar o Jira no momento. Tente novamente em alguns instantes."


def format_identity_unknown() -> str:
    return (
        "Não consegui identificar seu usuário no Jira. "
        "Entre em contato com o administrador para configurar o mapeamento."
    )
