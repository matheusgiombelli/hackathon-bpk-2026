"""
Pydantic AI tool definitions — Layer 3.
The jira_account_id is NEVER a parameter; it is injected via RunContext.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog
from pydantic_ai import RunContext

from src.cache import conversational as conv_cache
from src.cache.conversational import PendingAction
from src.formatting import responses as fmt
from src.jira.client import JiraClient
from src.rules.authorization import usuario_pode_comentar, usuario_pode_ver

logger = structlog.get_logger(__name__)


@dataclass
class Deps:
    account_id: str
    jira: JiraClient
    conversation_id: str


async def listar_tickets(
    ctx: RunContext[Deps],
    status: Optional[str] = None,
    projeto: Optional[str] = None,
    atrasados: bool = False,
    limite: int = 10,
) -> str:
    """
    List Jira tickets for the current user.

    Args:
        status: Filter by status — 'pendente', 'em_andamento', 'concluido', or None for all.
        projeto: Filter by project key (e.g. 'CARM', 'SPF01', 'ELIO').
        atrasados: If True, return only overdue tickets.
        limite: Maximum number of results (default 10).
    """
    from src.config import settings

    capped = min(limite, settings.ticket_list_limit)
    deps = ctx.deps
    logger.info("tool_listar_tickets", status=status, projeto=projeto, atrasados=atrasados)

    try:
        tickets = await deps.jira.search_tickets(
            account_id=deps.account_id,
            status=status,
            projeto=projeto,
            atrasados=atrasados,
            limite=capped + 5,  # fetch a few extra to get total count
        )
    except RuntimeError:
        return fmt.format_jira_unavailable()
    except Exception as e:
        logger.error("tool_listar_tickets_error", error=str(e))
        return fmt.format_jira_unavailable()

    total = len(tickets)
    visible = [t for t in tickets if usuario_pode_ver(deps.account_id, t)][:capped]

    return fmt.format_ticket_list(visible, total_available=total if total > capped else None)


async def detalhar_ticket(
    ctx: RunContext[Deps],
    chave: str,
) -> str:
    """
    Get full details of a specific Jira ticket.

    Args:
        chave: Ticket key (e.g. 'CARM-145', 'SPF01-23').
    """
    deps = ctx.deps
    logger.info("tool_detalhar_ticket", chave=chave)

    try:
        ticket = await deps.jira.get_ticket(chave.upper())
    except RuntimeError:
        return fmt.format_jira_unavailable()
    except Exception as e:
        logger.error("tool_detalhar_ticket_error", error=str(e))
        return fmt.format_jira_unavailable()

    if ticket is None:
        return fmt.format_ticket_not_found(chave.upper())

    if not usuario_pode_ver(deps.account_id, ticket):
        logger.warning(
            "authorization_denied",
            tool="detalhar_ticket",
            ticket=chave,
            result="denied",
        )
        return fmt.format_permission_denied(chave.upper(), "visualizar")

    return fmt.format_ticket_detail(ticket)


async def comentar_ticket(
    ctx: RunContext[Deps],
    chave: str,
    texto: str,
) -> str:
    """
    Request to add a comment to a Jira ticket. Always requires user confirmation first.

    Args:
        chave: Ticket key (e.g. 'CARM-145').
        texto: Comment text to add.
    """
    deps = ctx.deps
    chave = chave.upper()
    logger.info("tool_comentar_ticket_requested", chave=chave)

    try:
        ticket = await deps.jira.get_ticket(chave)
    except RuntimeError:
        return fmt.format_jira_unavailable()
    except Exception as e:
        logger.error("tool_comentar_ticket_error", error=str(e))
        return fmt.format_jira_unavailable()

    if ticket is None:
        return fmt.format_ticket_not_found(chave)

    if not usuario_pode_comentar(deps.account_id, ticket):
        logger.warning(
            "authorization_denied",
            tool="comentar_ticket",
            ticket=chave,
            result="denied",
        )
        return fmt.format_permission_denied(chave, "comentar em")

    # Save as pending action — execution happens only after user confirmation
    conv_cache.set_pending(
        deps.conversation_id,
        PendingAction(tool="comentar_ticket", args={"chave": chave, "texto": texto}),
    )

    return fmt.format_comment_confirmation(chave, texto)


async def pedir_esclarecimento(
    ctx: RunContext[Deps],
    motivo: str,
    sugestoes: Optional[list[str]] = None,
) -> str:
    """
    Ask the user to clarify an ambiguous request.

    Args:
        motivo: Why the request was ambiguous.
        sugestoes: Optional list of possible interpretations.
    """
    msg = f"Preciso de mais informações: {motivo}"
    if sugestoes:
        opts = "\n".join(f"• {s}" for s in sugestoes)
        msg += f"\n\nO que você quis dizer?\n{opts}"
    return msg


async def comando_fora_de_escopo(
    ctx: RunContext[Deps],
    motivo: str,
) -> str:
    """
    Inform the user that the requested action is outside the bot's scope.

    Args:
        motivo: Why the request is out of scope.
    """
    return (
        f"Não consigo ajudar com isso: {motivo}\n\n"
        "Posso te ajudar com:\n"
        "• Listar seus tickets (pendentes, em andamento, atrasados)\n"
        "• Detalhar um ticket específico\n"
        "• Registrar comentários em tickets\n"
        "• Filtrar por projeto, status ou prioridade"
    )
