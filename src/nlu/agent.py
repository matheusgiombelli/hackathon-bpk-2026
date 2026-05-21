"""
NLU agent — Layer 3.
Uses LLM as an intent classifier (returns JSON), then routes to keyword handlers.
This approach is more reliable with smaller local models than tool calling.
"""
from __future__ import annotations

import json
import re
import structlog

from src.cache import conversational as conv_cache
from src.config import settings
from src.nlu.tools import Deps

logger = structlog.get_logger(__name__)

_INTENT_PROMPT_HEAD = """Você é um classificador de intenção para um chatbot de tickets Jira.
Analise a mensagem do usuário e retorne SOMENTE um JSON válido, sem explicações.

Intenções possíveis:
- list_tickets: listar tickets. Params: overdue (bool), status ("pending"|"in_progress"|"done"|null), project (str|null), priority ("Highest"|"High"|"Medium"|"Low"|"Lowest"|null), issue_type ("Bug"|"Task"|"Story"|"Epic"|null), reported_by_me (bool)
- ticket_detail: ver detalhes de um ticket. Params: key (ex: "KAN-5")
- add_comment: adicionar comentário. Params: key, text
- list_comments: listar comentários de um ticket. Params: key
- search_text: buscar tickets por texto livre. Params: query (str)
- assign_to_me: atribuir um ticket a si mesmo. Params: key
- create_ticket: criar novo ticket. Params: project (str, ex: "KAN"), summary (str), issue_type ("Task"|"Bug"|"Story"), priority ("Highest"|"High"|"Medium"|"Low"|"Lowest"|null)
- update_status: mudar status de um ticket. Params: key, status ("in_progress"|"done"|"pending")
- update_priority: mudar prioridade de um ticket. Params: key, priority ("Highest"|"High"|"Medium"|"Low"|"Lowest")
- help: ajuda ou saudação
- out_of_scope: fora do escopo

Quando houver histórico, use-o para resolver referências como "nele", "esse", "o primeiro", "no que você acabou de listar".

Exemplos:
Usuário: "meus tickets" → {"intent":"list_tickets","params":{"overdue":false,"status":null,"project":null,"priority":null,"issue_type":null,"reported_by_me":false}}
Usuário: "tickets atrasados" → {"intent":"list_tickets","params":{"overdue":true,"status":null,"project":null,"priority":null,"issue_type":null,"reported_by_me":false}}
Usuário: "meus bugs" → {"intent":"list_tickets","params":{"overdue":false,"status":null,"project":null,"priority":null,"issue_type":"Bug","reported_by_me":false}}
Usuário: "tickets urgentes" → {"intent":"list_tickets","params":{"overdue":false,"status":null,"project":null,"priority":"Highest","issue_type":null,"reported_by_me":false}}
Usuário: "tickets de alta prioridade no KAN" → {"intent":"list_tickets","params":{"overdue":false,"status":null,"project":"KAN","priority":"High","issue_type":null,"reported_by_me":false}}
Usuário: "tickets que abri" → {"intent":"list_tickets","params":{"overdue":false,"status":null,"project":null,"priority":null,"issue_type":null,"reported_by_me":true}}
Usuário: "bugs que reportei no KAN" → {"intent":"list_tickets","params":{"overdue":false,"status":null,"project":"KAN","priority":null,"issue_type":"Bug","reported_by_me":true}}
Usuário: "pendentes" → {"intent":"list_tickets","params":{"overdue":false,"status":"pending","project":null,"priority":null,"issue_type":null,"reported_by_me":false}}
Usuário: "em andamento" → {"intent":"list_tickets","params":{"overdue":false,"status":"in_progress","project":null,"priority":null,"issue_type":null,"reported_by_me":false}}
Usuário: "me mostra o KAN-7" → {"intent":"ticket_detail","params":{"key":"KAN-7"}}
Usuário: "detalha KAN-10" → {"intent":"ticket_detail","params":{"key":"KAN-10"}}
Usuário: "comentários do KAN-5" → {"intent":"list_comments","params":{"key":"KAN-5"}}
Usuário: "mostra os comments do KAN-7" → {"intent":"list_comments","params":{"key":"KAN-7"}}
Usuário: "busca tickets com login" → {"intent":"search_text","params":{"query":"login"}}
Usuário: "procura por pagamento" → {"intent":"search_text","params":{"query":"pagamento"}}
Usuário: "pega o KAN-5 pra mim" → {"intent":"assign_to_me","params":{"key":"KAN-5"}}
Usuário: "me atribui o KAN-7" → {"intent":"assign_to_me","params":{"key":"KAN-7"}}
Usuário: "assume KAN-9" → {"intent":"assign_to_me","params":{"key":"KAN-9"}}
Usuário: "comenta no KAN-5: implementação pronta" → {"intent":"add_comment","params":{"key":"KAN-5","text":"implementação pronta"}}
Usuário: "cria um ticket no KAN: implementar login social" → {"intent":"create_ticket","params":{"project":"KAN","summary":"Implementar login social","issue_type":"Task","priority":null}}
Usuário: "novo bug no KAN: botão salvar não funciona" → {"intent":"create_ticket","params":{"project":"KAN","summary":"Botão salvar não funciona","issue_type":"Bug","priority":"High"}}
Usuário: "move o KAN-5 para em andamento" → {"intent":"update_status","params":{"key":"KAN-5","status":"in_progress"}}
Usuário: "fecha o KAN-7" → {"intent":"update_status","params":{"key":"KAN-7","status":"done"}}
Usuário: "muda prioridade do KAN-8 para alta" → {"intent":"update_priority","params":{"key":"KAN-8","priority":"High"}}
Usuário: "ajuda" → {"intent":"help","params":{}}
Usuário: "qual o tempo hoje?" → {"intent":"out_of_scope","params":{}}
"""

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)


def _use_llm() -> bool:
    return bool(settings.llm_base_url or settings.openrouter_api_key)


def _build_prompt(user_message: str, history: list[dict]) -> str:
    history_block = ""
    if history:
        lines = []
        for turn in history[-4:]:
            role = "Usuário" if turn["role"] == "user" else "Assistente"
            content = turn["content"].replace("\n", " ")
            if len(content) > 220:
                content = content[:220] + "…"
            lines.append(f"{role}: {content}")
        history_block = "\nHistórico recente da conversa:\n" + "\n".join(lines) + "\n"

    return (
        _INTENT_PROMPT_HEAD
        + history_block
        + f'\nMensagem do usuário: "{user_message}"'
    )


async def _classify_with_llm(user_message: str, history: list[dict]) -> dict | None:
    """Call LLM for intent classification. Returns parsed dict or None on failure.

    Uses Ollama's native /api/chat when llm_base_url is set (supports think:false
    to skip Gemma's reasoning tokens). Falls back to OpenAI-compat /v1 for OpenRouter.
    """
    import httpx

    prompt = _build_prompt(user_message, history)
    messages = [{"role": "user", "content": prompt}]

    if settings.llm_base_url:
        # Local Ollama — native endpoint, disable reasoning
        base = settings.llm_base_url.rstrip("/").removesuffix("/v1")
        url = f"{base}/api/chat"
        payload = {
            "model": settings.openrouter_model,
            "messages": messages,
            "think": False,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 200},
        }
        headers = {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                content = (resp.json().get("message") or {}).get("content", "").strip()
                logger.info("llm_raw_response", content=content[:200])
                match = _JSON_RE.search(content)
                if match:
                    return json.loads(match.group())
        except Exception as e:
            logger.warning("llm_classify_failed", error=str(e))
        return None

    # OpenRouter (cloud) — OpenAI-compatible endpoint
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": settings.openrouter_model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 400,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            logger.info("llm_raw_response", content=content[:200])
            match = _JSON_RE.search(content)
            if match:
                return json.loads(match.group())
    except Exception as e:
        logger.warning("llm_classify_failed", error=str(e))

    return None


async def run(user_message: str, deps: Deps) -> str:
    """Route message: LLM classification → handler, or keyword fallback."""
    from src.nlu import keyword_fallback

    history = conv_cache.get_history(deps.conversation_id)

    if not _use_llm() or len(user_message.split()) <= 1:
        logger.info("nlu_mode", mode="keyword_fallback")
        return await keyword_fallback.run(user_message, deps)

    logger.info("nlu_mode", mode="llm_classifier", history_turns=len(history))
    intent_data = await _classify_with_llm(user_message, history)

    if not intent_data:
        logger.warning("nlu_llm_failed", fallback=True)
        return await keyword_fallback.run(user_message, deps)

    intent = intent_data.get("intent", "")
    params = intent_data.get("params", {})
    logger.info("intent_classified", intent=intent, params=str(params))

    if intent == "list_tickets":
        return await keyword_fallback._handle_list(
            deps,
            status=_map_status(params.get("status")),
            projeto=params.get("project"),
            atrasados=bool(params.get("overdue", False)),
            priority=params.get("priority"),
            issue_type=params.get("issue_type"),
            as_reporter=bool(params.get("reported_by_me", False)),
        )

    elif intent == "ticket_detail":
        key = params.get("key", "")
        if key:
            return await keyword_fallback._handle_detail(key.upper(), deps)

    elif intent == "list_comments":
        key = params.get("key", "")
        if key:
            return await keyword_fallback._handle_list_comments(key.upper(), deps)

    elif intent == "search_text":
        query = (params.get("query") or "").strip()
        if query:
            return await keyword_fallback._handle_search(query, deps)

    elif intent == "assign_to_me":
        key = params.get("key", "")
        if key:
            return await keyword_fallback._handle_assign_to_me(key.upper(), deps)

    elif intent == "add_comment":
        key = params.get("key", "")
        text = params.get("text", "")
        if key and text:
            return await keyword_fallback._handle_comment(key.upper(), text, deps)

    elif intent == "create_ticket":
        project = params.get("project") or "KAN"
        summary = params.get("summary", "").strip()
        if summary:
            return await keyword_fallback._handle_create(
                project=project.upper(),
                summary=summary,
                issue_type=params.get("issue_type") or "Task",
                priority=params.get("priority"),
                deps=deps,
            )

    elif intent == "update_status":
        key = params.get("key", "")
        status = params.get("status", "")
        if key and status:
            return await keyword_fallback._handle_transition(key.upper(), status, deps)

    elif intent == "update_priority":
        key = params.get("key", "")
        priority = params.get("priority", "")
        if key and priority:
            return await keyword_fallback._handle_priority(key.upper(), priority, deps)

    elif intent == "help":
        return _help_text()

    elif intent == "out_of_scope":
        return (
            "Só consigo ajudar com tickets Jira.\n"
            "Tente: `meus tickets`, `tickets atrasados` ou `detalha KAN-5`."
        )

    return await keyword_fallback.run(user_message, deps)


def _help_text() -> str:
    return (
        "Olá! Posso te ajudar com:\n"
        "• `meus tickets` — listar seus tickets\n"
        "• `tickets atrasados` / `urgentes` / `meus bugs` — filtros rápidos\n"
        "• `tickets que abri` — tickets que você reportou\n"
        "• `detalha KAN-5` — detalhes de um ticket\n"
        "• `comentários do KAN-5` — ver últimos comentários\n"
        "• `busca login` — procurar tickets por texto\n"
        "• `pega o KAN-5 pra mim` — atribuir a você\n"
        "• `comenta no KAN-5: texto` — adicionar comentário\n"
        "• `cria ticket no KAN: resumo` — criar novo ticket\n"
        "• `move KAN-5 para em andamento` — mudar status\n"
        "• `muda prioridade do KAN-8 para alta` — mudar prioridade\n"
    )


def _map_status(s: str | None) -> str | None:
    mapping = {"pending": "pendente", "in_progress": "em_andamento", "done": "concluido"}
    return mapping.get(s or "", None)
