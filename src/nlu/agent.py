"""
NLU agent — Layer 3.
Uses LLM as an intent classifier (returns JSON), then routes to keyword handlers.
This approach is more reliable with smaller local models than tool calling.
"""
from __future__ import annotations

import json
import re
import structlog

from src.config import settings
from src.nlu.tools import Deps

logger = structlog.get_logger(__name__)

_INTENT_PROMPT = """Você é um classificador de intenção para um chatbot de tickets Jira.
Analise a mensagem do usuário e retorne SOMENTE um JSON válido, sem explicações.

Intenções possíveis:
- list_tickets: listar tickets. Params: overdue (bool), status ("pending"|"in_progress"|"done"|null), project (str|null)
- ticket_detail: ver detalhes de um ticket. Params: key (ex: "KAN-5")
- add_comment: adicionar comentário. Params: key, text
- create_ticket: criar novo ticket. Params: project (str, ex: "KAN"), summary (str), issue_type ("Task"|"Bug"|"Story"), priority ("Highest"|"High"|"Medium"|"Low"|"Lowest"|null)
- update_status: mudar status de um ticket. Params: key, status ("in_progress"|"done"|"pending")
- update_priority: mudar prioridade de um ticket. Params: key, priority ("Highest"|"High"|"Medium"|"Low"|"Lowest")
- help: ajuda ou saudação
- out_of_scope: fora do escopo

Exemplos:
Usuário: "meus tickets" → {"intent":"list_tickets","params":{"overdue":false,"status":null,"project":null}}
Usuário: "tickets atrasados" → {"intent":"list_tickets","params":{"overdue":true,"status":null,"project":null}}
Usuário: "quais tarefas estão em atraso?" → {"intent":"list_tickets","params":{"overdue":true,"status":null,"project":null}}
Usuário: "me mostra o KAN-7" → {"intent":"ticket_detail","params":{"key":"KAN-7"}}
Usuário: "detalha KAN-10" → {"intent":"ticket_detail","params":{"key":"KAN-10"}}
Usuário: "comenta no KAN-5: implementação pronta" → {"intent":"add_comment","params":{"key":"KAN-5","text":"implementação pronta"}}
Usuário: "tem algo urgente?" → {"intent":"list_tickets","params":{"overdue":true,"status":null,"project":null}}
Usuário: "o que devo focar hoje?" → {"intent":"list_tickets","params":{"overdue":true,"status":null,"project":null}}
Usuário: "pendentes" → {"intent":"list_tickets","params":{"overdue":false,"status":"pending","project":null}}
Usuário: "em andamento" → {"intent":"list_tickets","params":{"overdue":false,"status":"in_progress","project":null}}
Usuário: "cria um ticket no KAN: implementar login social" → {"intent":"create_ticket","params":{"project":"KAN","summary":"Implementar login social","issue_type":"Task","priority":null}}
Usuário: "novo bug no KAN: botão salvar não funciona" → {"intent":"create_ticket","params":{"project":"KAN","summary":"Botão salvar não funciona","issue_type":"Bug","priority":"High"}}
Usuário: "cria tarefa urgente no KAN: revisar deploy" → {"intent":"create_ticket","params":{"project":"KAN","summary":"Revisar deploy","issue_type":"Task","priority":"Highest"}}
Usuário: "move o KAN-5 para em andamento" → {"intent":"update_status","params":{"key":"KAN-5","status":"in_progress"}}
Usuário: "fecha o KAN-7" → {"intent":"update_status","params":{"key":"KAN-7","status":"done"}}
Usuário: "começa o KAN-9" → {"intent":"update_status","params":{"key":"KAN-9","status":"in_progress"}}
Usuário: "muda prioridade do KAN-8 para alta" → {"intent":"update_priority","params":{"key":"KAN-8","priority":"High"}}
Usuário: "KAN-10 é crítico" → {"intent":"update_priority","params":{"key":"KAN-10","priority":"Highest"}}
Usuário: "ajuda" → {"intent":"help","params":{}}
Usuário: "qual o tempo hoje?" → {"intent":"out_of_scope","params":{}}

Mensagem do usuário: """

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)


def _use_llm() -> bool:
    return bool(settings.llm_base_url or settings.openrouter_api_key)


async def _classify_with_llm(user_message: str) -> dict | None:
    """Call LLM for intent classification. Returns parsed dict or None on failure."""
    import httpx

    if settings.llm_base_url:
        base_url = settings.llm_base_url.rstrip("/")
        api_key = settings.llm_api_key or "lm-studio"
    else:
        base_url = "https://openrouter.ai/api/v1"
        api_key = settings.openrouter_api_key

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "user", "content": _INTENT_PROMPT + f'"{user_message}"'}
        ],
        "temperature": 0.1,
        "max_tokens": 100,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            logger.info("llm_raw_response", content=content[:200])

            # Extract JSON from response
            match = _JSON_RE.search(content)
            if match:
                return json.loads(match.group())
    except Exception as e:
        logger.warning("llm_classify_failed", error=str(e))

    return None


async def run(user_message: str, deps: Deps) -> str:
    """Route message: LLM classification → handler, or keyword fallback."""
    from src.nlu import keyword_fallback

    if not _use_llm() or len(user_message.split()) <= 1:
        logger.info("nlu_mode", mode="keyword_fallback")
        return await keyword_fallback.run(user_message, deps)

    logger.info("nlu_mode", mode="llm_classifier")
    intent_data = await _classify_with_llm(user_message)

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
        )

    elif intent == "ticket_detail":
        key = params.get("key", "")
        if key:
            return await keyword_fallback._handle_detail(key.upper(), deps)

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
        return (
            "Olá! Posso te ajudar com:\n"
            "• `meus tickets` — listar seus tickets\n"
            "• `tickets atrasados` — ver o que está em atraso\n"
            "• `detalha KAN-5` — detalhes de um ticket\n"
            "• `comenta no KAN-5: texto` — adicionar comentário\n"
            "• `cria ticket no KAN: resumo` — criar novo ticket\n"
            "• `move KAN-5 para em andamento` — mudar status\n"
            "• `muda prioridade do KAN-8 para alta` — mudar prioridade\n"
        )

    elif intent == "out_of_scope":
        return (
            "Só consigo ajudar com tickets Jira.\n"
            "Tente: `meus tickets`, `tickets atrasados` ou `detalha KAN-5`."
        )

    # Fallback for unhandled cases
    return await keyword_fallback.run(user_message, deps)


def _map_status(s: str | None) -> str | None:
    mapping = {"pending": "pendente", "in_progress": "em_andamento", "done": "concluido"}
    return mapping.get(s or "", None)
