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

_PRIORITY_MAP = {
    "alta": "High", "high": "High", "urgente": "Highest", "blocker": "Highest",
    "crítica": "Highest", "critica": "Highest", "crítico": "Highest", "critico": "Highest",
    "média": "Medium", "media": "Medium", "normal": "Medium", "medium": "Medium",
    "baixa": "Low", "low": "Low",
    "mínima": "Lowest", "minima": "Lowest", "lowest": "Lowest",
    "highest": "Highest",
}
_ISSUE_TYPE_MAP = {
    "bug": "Bug", "erro": "Bug", "problema": "Bug", "falha": "Bug",
    "história": "Story", "historia": "Story", "story": "Story",
    "epic": "Epic",
}

_STATUS_TARGET_MAP = {
    "em andamento": "in_progress", "in progress": "in_progress", "andamento": "in_progress",
    "iniciado": "in_progress", "começar": "in_progress", "iniciar": "in_progress",
    "concluído": "done", "concluido": "done", "feito": "done", "done": "done",
    "finalizado": "done", "fechado": "done", "resolver": "done",
    "a fazer": "pending", "pendente": "pending", "reabrir": "pending", "to do": "pending",
}

logger = structlog.get_logger(__name__)

_TICKET_KEY_RE = re.compile(r'\b([A-Za-z]+-\d+)\b')
_COMMENT_RE = re.compile(
    r'(?:coment[ea](?:r|ndo)?|adiciona(?:r)?(?:\s+um?)?\s*coment[aá]rio|posta(?:r)?)\s+(?:n[oa]\s+)?([A-Za-z]+-\d+)\s*[:\-]\s*(.+)',
    re.IGNORECASE,
)
_DETAIL_RE = re.compile(
    r'(?:detalha(?:r)?|detalhes?\s*(?:d[oa])?|abr(?:e|ir)|ver?|mostra(?:r)?|abre|exibe(?:r)?|info(?:rma[cç][oõ]es?)?\s*(?:d[oa])?|o\s+que\s+[eé]|status\s+d[oa]?)\s+([A-Za-z]+-\d+)',
    re.IGNORECASE,
)
_OVERDUE_RE = re.compile(r'\b(atrasad[ao]s?|vencid[ao]s?|em\s+atraso|late|overdue|prazo\s+vencid[ao]?)\b', re.IGNORECASE)
_PENDING_RE = re.compile(r'\b(pendentes?|a\s+fazer|to\s*do|em\s+aberto|abertos?|n[aã]o\s+(?:feitos?|iniciados?))\b', re.IGNORECASE)
_INPROG_RE = re.compile(r'\b(em\s+andamento|in\s+progress|fazendo|executand[ao]|trabalhando)\b', re.IGNORECASE)
_DONE_RE = re.compile(r'\b(conclu[ií]d[ao]s?|feitos?|done|finalizado|resolvid[ao]s?|fechad[ao]s?)\b', re.IGNORECASE)
_LIST_RE = re.compile(
    r'\b(lista(?:r)?|listar?|quais?|meus?\s+(?:tickets?|tiquetes?)|status\s+dos?|tickets?|tiquetes?|ticks?|tarefas?|atividades?|demandas?|issues?|cards?|atividade)\b',
    re.IGNORECASE,
)
_PROJECT_RE = re.compile(r'\b(?:projeto\s+)?([A-Z]{2,10})\b')
_HELP_RE = re.compile(r'\b(ajuda|help|oi|ol[aá]|inicio|o\s+que\s+voc[eê]|comandos?|como\s+usar)\b', re.IGNORECASE)

_CREATE_RE = re.compile(
    r'\b(?:cri[ae](?:r)?|nov[oa]\s+(?:ticket|tarefa|bug|issue|card)|abr(?:e|ir)\s+(?:um?a?\s+)?(?:ticket|tarefa)|adiciona(?:r)?\s+(?:um?a?\s+)?(?:ticket|tarefa))\b',
    re.IGNORECASE,
)
_TRANSITION_RE = re.compile(
    r'\b(?:move?r?|mud[ae](?:r)?|atualiza(?:r)?|passa(?:r)?|coloca(?:r)?|mover)\s+(?:[ao]\s+)?([A-Za-z]+-\d+)\s+(?:para\s+)?(.+)',
    re.IGNORECASE,
)
_CLOSE_RE = re.compile(
    r'\b(?:fecha(?:r)?|conclu[ií](?:r)?|finaliza(?:r)?|resolve(?:r)?|fechar)\s+(?:[ao]\s+)?([A-Za-z]+-\d+)\b',
    re.IGNORECASE,
)
_START_RE = re.compile(
    r'\b(?:come[cç]a(?:r)?|inicia(?:r)?|começar|iniciar)\s+(?:[ao]\s+)?([A-Za-z]+-\d+)\b',
    re.IGNORECASE,
)
_PRIORITY_RE = re.compile(
    r'\b(?:mud[ae](?:r)?|altera(?:r)?|atualiza(?:r)?)\s+(?:a?\s*)?prioridade\s+(?:d[oa]\s+)?([A-Za-z]+-\d+)\s+(?:para\s+)?(.+)',
    re.IGNORECASE,
)


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

    # Close intent (fecha KAN-7)
    close_match = _CLOSE_RE.search(msg)
    if close_match:
        return await _handle_transition(close_match.group(1).upper(), "done", deps)

    # Start intent (começa KAN-9)
    start_match = _START_RE.search(msg)
    if start_match:
        return await _handle_transition(start_match.group(1).upper(), "in_progress", deps)

    # Transition intent (move KAN-5 para em andamento)
    transition_match = _TRANSITION_RE.search(msg)
    if transition_match:
        key = transition_match.group(1).upper()
        raw_status = transition_match.group(2).strip().lower()
        target = _STATUS_TARGET_MAP.get(raw_status)
        if target:
            return await _handle_transition(key, target, deps)

    # Priority intent (muda prioridade do KAN-8 para alta)
    priority_match = _PRIORITY_RE.search(msg)
    if priority_match:
        key = priority_match.group(1).upper()
        raw_priority = priority_match.group(2).strip().lower()
        priority = _PRIORITY_MAP.get(raw_priority)
        if priority:
            return await _handle_priority(key, priority, deps)

    # Create intent
    if _CREATE_RE.search(msg):
        # Extract project key and summary from message
        project = _extract_project(msg) or "KAN"
        # Extract summary after colon or dash
        summary_match = re.search(r'[:\-]\s*(.+)$', msg, re.IGNORECASE)
        summary = summary_match.group(1).strip() if summary_match else None
        if summary:
            issue_type_raw = None
            for kw, it in _ISSUE_TYPE_MAP.items():
                if kw in msg.lower():
                    issue_type_raw = it
                    break
            priority_raw = None
            for kw, pv in _PRIORITY_MAP.items():
                if kw in msg.lower():
                    priority_raw = pv
                    break
            return await _handle_create(project, summary, issue_type_raw or "Task", priority_raw, deps)
        return "Para criar um ticket informe o resumo. Exemplo: `cria ticket no KAN: implementar login`"

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


async def _handle_create(
    project: str, summary: str, issue_type: str, priority: Optional[str], deps: Deps
) -> str:
    conv_cache.set_pending(
        deps.conversation_id,
        PendingAction(tool="criar_ticket", args={
            "project": project, "summary": summary,
            "issue_type": issue_type, "priority": priority,
        }),
    )
    return fmt.format_create_ticket_confirmation(project, summary, issue_type, priority)


async def _handle_transition(chave: str, target_status: str, deps: Deps) -> str:
    try:
        ticket = await deps.jira.get_ticket(chave)
    except Exception as e:
        logger.error("keyword_transition_error", error=str(e))
        return fmt.format_jira_unavailable()

    if ticket is None:
        return fmt.format_ticket_not_found(chave)

    conv_cache.set_pending(
        deps.conversation_id,
        PendingAction(tool="atualizar_status", args={"chave": chave, "status": target_status}),
    )
    return fmt.format_update_status_confirmation(chave, target_status)


async def _handle_priority(chave: str, priority: str, deps: Deps) -> str:
    try:
        ticket = await deps.jira.get_ticket(chave)
    except Exception as e:
        logger.error("keyword_priority_error", error=str(e))
        return fmt.format_jira_unavailable()

    if ticket is None:
        return fmt.format_ticket_not_found(chave)

    conv_cache.set_pending(
        deps.conversation_id,
        PendingAction(tool="atualizar_prioridade", args={"chave": chave, "priority": priority}),
    )
    return fmt.format_update_priority_confirmation(chave, priority)
