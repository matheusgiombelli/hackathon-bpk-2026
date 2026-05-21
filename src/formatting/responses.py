from __future__ import annotations
from typing import List
from src.jira.models import JiraComment, JiraTicket


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
    created = ticket.created.strftime("%d/%m/%Y")
    updated = ticket.updated.strftime("%d/%m/%Y")
    overdue_line = f"\n⚠️ **Atrasado** há {ticket.days_overdue} dia(s)" if ticket.is_overdue else ""

    return (
        f"**{ticket.key}** — {ticket.summary}\n"
        f"Projeto: {ticket.project_name} (`{ticket.project_key}`)\n"
        f"Status: **{ticket.status}**\n"
        f"Prioridade: {ticket.priority or '—'}\n"
        f"Responsável: {assignee}\n"
        f"Solicitante: {reporter}\n"
        f"Criado em: {created}\n"
        f"Última atualização: {updated}\n"
        f"Prazo: {due}"
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


_STATUS_LABELS = {"in_progress": "Em andamento", "done": "Concluído", "pending": "A fazer"}
_PRIORITY_LABELS = {"Highest": "Crítica", "High": "Alta", "Medium": "Média", "Low": "Baixa", "Lowest": "Mínima"}


def format_create_ticket_confirmation(project: str, summary: str, issue_type: str, priority: str | None) -> str:
    priority_line = f"\nPrioridade: **{_PRIORITY_LABELS.get(priority, priority)}**" if priority else ""
    return (
        f"Confirma a criação do ticket?\n\n"
        f"Projeto: **{project.upper()}**\n"
        f"Tipo: **{issue_type}**\n"
        f"Resumo: _{summary}_"
        f"{priority_line}\n\n"
        f"Responda **sim** para confirmar ou **não** para cancelar."
    )


def format_create_ticket_success(key: str, summary: str) -> str:
    return f"✅ Ticket **{key}** criado com sucesso!\n_{summary}_"


def format_update_status_confirmation(key: str, status: str) -> str:
    label = _STATUS_LABELS.get(status, status)
    return (
        f"Confirma a mudança de status do ticket **{key}** para **{label}**?\n\n"
        f"Responda **sim** para confirmar ou **não** para cancelar."
    )


def format_update_status_success(key: str, status: str) -> str:
    return f"✅ Status do ticket **{key}** atualizado para **{_STATUS_LABELS.get(status, status)}**."


def format_update_status_failed(key: str) -> str:
    return f"⚠️ Não consegui alterar o status do **{key}**. Verifique as transições disponíveis no Jira."


def format_update_priority_confirmation(key: str, priority: str) -> str:
    label = _PRIORITY_LABELS.get(priority, priority)
    return (
        f"Confirma a mudança de prioridade do ticket **{key}** para **{label}**?\n\n"
        f"Responda **sim** para confirmar ou **não** para cancelar."
    )


def format_update_priority_success(key: str, priority: str) -> str:
    return f"✅ Prioridade do ticket **{key}** atualizada para **{_PRIORITY_LABELS.get(priority, priority)}**."


def format_comments_list(ticket_key: str, comments: List[JiraComment]) -> str:
    if not comments:
        return f"Nenhum comentário no ticket **{ticket_key}**."
    lines = [f"**Comentários de {ticket_key}** (mais recentes primeiro):"]
    for c in comments:
        when = c.created.strftime("%d/%m %H:%M")
        body = c.body.replace("\n", " ")
        if len(body) > 280:
            body = body[:280] + "…"
        lines.append(f"• _{c.author}_ — {when}\n  > {body}")
    return "\n".join(lines)


def format_assign_confirmation(ticket_key: str) -> str:
    return (
        f"Confirma atribuir o ticket **{ticket_key}** a você?\n\n"
        f"Responda **sim** para confirmar ou **não** para cancelar."
    )


def format_assign_success(ticket_key: str) -> str:
    return f"✅ Ticket **{ticket_key}** atribuído a você."


def format_search_empty(query: str) -> str:
    return f"Nenhum ticket encontrado para a busca _{query}_."
