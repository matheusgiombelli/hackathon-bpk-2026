"""
Keyword-based NLU fallback — used when OPENROUTER_API_KEY is not set.
No LLM required. Covers the main demo scenarios.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from src.cache import conversational as conv_cache
from src.cache.conversational import PendingAction
from src.formatting import responses as fmt
from src.jira.client import JiraClient
from src.nlu.tools import Deps
from src.rules.authorization import usuario_pode_comentar, usuario_pode_ver

logger = structlog.get_logger(__name__)

_TICKET_KEY_RE = re.compile(r'\b([A-Z]+-\d+)\b')
_COMMENT_RE = re.compile(
    r'(?:coment[ea](?:r|ndo)?|adiciona(?:r)? coment[aá]rio)\s+(?:n[oa]\s+)?([A-Z]+-\d+)\s*[:\-]\s*(.+)',
    re.IGNORECASE,
)
_DETAIL_RE = re.compile(
    r'(?:detalha(?:r)?|detalhes?\s+d[oa]?|abrir?|ver?|mostra(?:r)?|info(?:rma[cç][oõ]es?)?\s+d[oa]?)\s+([A-Z]+-\d+)',
    re.IGNORECASE,
)
_OVERDUE_RE = re.compile(r'\b(atrasad[ao]s?|vencid[ao]s?|em\s+atraso)\b', re.IGNORECASE)
_PENDING_RE = re.compile(r'\b(pendentes?|a\s+fazer|to\s*do|em\s+aberto|abertos?)\b', re.IGNORECASE)
_INPROG_RE = re.compile(r'\b(em\s+andamento|in\s+progress|fazendo|executand[ao])\b', re.IGNORECASE)
_DONE_RE = re.compile(r'\b(conclu[ií]d[ao]s?|feitos?|done|finalizado)\b', re.IGNORECASE)
_LIST_RE = re.compile(
    r'\b(lista(?:r)?|listar?|quais?|meus?\s+tickets?|status\s+dos?|tickets?|tarefa|tarefas)\b',
    re.IGNORECASE,
)
_PROJECT_RE = re.compile(r'\b(?:projeto\s+)?([A-Z]{2,10})\b')

_HELP_RE = re.compile(r'\b(ajuda|help|oi|ol[aá]|inicio|start|o\s+que\s+voc[eê])\b', re.IGNORECASE)


def _extract_project(text: str) -> Optional[str]:
    skip = {'OS', 'EM', 'NO', 'NA', 'DE', 'DO', 'DA', 'UM', 'UMA', 'EU', 'ME',
            'SE', 'NÃO', 'NAO', 'SIM', 'COM', 'POR', 'PARA', 'OS', 'AS', 'IS',
            'IN', 'TO', 'AT', 'BE', 'OK', 'JA', 'JÁ', 'VER', 'BOT', 'LLM'}
    for m in _PROJECT_RE.finditer(text):
        word = m.group(1).upper()
        if word not in skip and len(word) >= 2:
            return word
    return None


async def run(user_message: str, deps: Deps) -> str:
    msg = user_message.strip()

    # Help
    if _HELP_RE.search(msg) and len(msg) < 30:
        return (
            "Olá! Posso te ajudar com:\n"
            "• `meus tickets` — listar seus tickets\n"
            "• `tickets atrasados` — ver o que está em atraso\n"
            "• `tickets em andamento` — ver o que está sendo feito\n"
            "• `detalha KAN-4` — ver detalhes de um ticket\n"
            "• `comente no KAN-4: seu comentário` — adicionar comentário\n"
        )

    # Comment intent
    comment_match = _COMMENT_RE.search(msg)
    if comment_match:
        chave = comment_match.group(1).upper()
        texto = comment_match.group(2).strip()
        return await _handle_comment(chave, texto, deps)

    # Detail intent
    detail_match = _DETAIL_RE.search(msg)
    if detail_match:
        chave = detail_match.group(1).upper()
        return await _handle_detail(chave, deps)

    # Ticket key mentioned without explicit verb → detail
    keys = _TICKET_KEY_RE.findall(msg.upper())
    if keys and not _LIST_RE.search(msg):
        return await _handle_detail(keys[0], deps)

    # List intent
    atrasados = bool(_OVERDUE_RE.search(msg))
    status = None
    if _PENDING_RE.search(msg):
        status = 'pendente'
    elif _INPROG_RE.search(msg):
        status = 'em_andamento'
    elif _DONE_RE.search(msg):
        status = 'concluido'

    projeto = _extract_project(msg) if not atrasados else _extract_project(msg)

    if _LIST_RE.search(msg) or atrasados or status or 'ticket' in msg.lower() or 'tarefa' in msg.lower():
        return await _handle_list(deps, status=status, projeto=projeto, atrasados=atrasados)

    # Fallback
    return (
        "Não entendi o comando. Exemplos do que posso fazer:\n"
        "• `meus tickets` — listar todos os seus tickets\n"
        "• `tickets atrasados` — ver tickets em atraso\n"
        "• `detalha KAN-4` — ver detalhes de um ticket específico\n"
        "• `comente no KAN-4: seu texto` — adicionar comentário"
    )


async def _handle_list(deps: Deps, status=None, projeto=None, atrasados=False) -> str:
    try:
        tickets = await deps.jira.search_tickets(
            account_id=deps.account_id,
            status=status,
            projeto=projeto,
            atrasados=atrasados,
            limite=10,
        )
    except Exception as e:
        logger.error("keyword_list_error", error=str(e))
        return fmt.format_jira_unavailable()

    visible = [t for t in tickets if usuario_pode_ver(deps.account_id, t)]
    return fmt.format_ticket_list(visible, total_available=len(tickets) if len(tickets) > len(visible) else None)


async def _handle_detail(chave: str, deps: Deps) -> str:
    try:
        ticket = await deps.jira.get_ticket(chave)
    except Exception as e:
        logger.error("keyword_detail_error", error=str(e))
        return fmt.format_jira_unavailable()

    if ticket is None:
        return fmt.format_ticket_not_found(chave)
    if not usuario_pode_ver(deps.account_id, ticket):
        return fmt.format_permission_denied(chave, "visualizar")
    return fmt.format_ticket_detail(ticket)


async def _handle_comment(chave: str, texto: str, deps: Deps) -> str:
    try:
        ticket = await deps.jira.get_ticket(chave)
    except Exception as e:
        logger.error("keyword_comment_error", error=str(e))
        return fmt.format_jira_unavailable()

    if ticket is None:
        return fmt.format_ticket_not_found(chave)
    if not usuario_pode_comentar(deps.account_id, ticket):
        return fmt.format_permission_denied(chave, "comentar em")

    conv_cache.set_pending(
        deps.conversation_id,
        PendingAction(tool="comentar_ticket", args={"chave": chave, "texto": texto}),
    )
    return fmt.format_comment_confirmation(chave, texto)
