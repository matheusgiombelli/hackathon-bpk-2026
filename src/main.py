import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from botbuilder.schema import Activity
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import settings
from src.observability.logging_config import configure_logging

logger = structlog.get_logger(__name__)

_CONFIRM_RE = re.compile(r'\b(sim|yes|confirmar|confirmo|ok|pode|claro|positivo|s)\b', re.IGNORECASE)
_REJECT_RE  = re.compile(r'\b(n[aã]o|no|cancelar|cancela|negativo)\b', re.IGNORECASE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("logs", exist_ok=True)
    configure_logging(log_level=settings.log_level, log_file=settings.log_file)
    logger.info("startup", port=settings.port, model=settings.openrouter_model)
    yield
    logger.info("shutdown")


app = FastAPI(title="Jira Teams Bot — Biopark Hackathon", lifespan=lifespan)

_static = Path(__file__).parent.parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

_adapter = None
_bot = None


def _get_adapter_and_bot():
    global _adapter, _bot
    if _adapter is None:
        from src.adapters.teams import BotApp, create_adapter
        _adapter = create_adapter()
        _bot = BotApp()
    return _adapter, _bot


# ── Web chat endpoint ────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "webchat-default"
    user_email: str = "User"


@app.get("/", response_class=HTMLResponse)
async def root():
    html = _static / "index.html"
    if html.exists():
        return HTMLResponse(html.read_text(encoding="utf-8"))
    return HTMLResponse("<h2>Bot running. POST /chat to interact.</h2>")


@app.post("/chat")
async def chat(req: ChatRequest):
    from src.cache import conversational as conv_cache
    from src.identity import resolver as identity_resolver
    from src.jira.client import JiraClient
    from src.nlu.tools import Deps

    jira = JiraClient()
    account_id = await identity_resolver.resolve(req.user_email, jira)
    if not account_id:
        return {"response": "Não consegui identificar seu usuário. Verifique o mapeamento em data/user_mapping.json."}

    deps = Deps(account_id=account_id, jira=jira, conversation_id=req.conversation_id)
    response = await _process_chat_turn(req.message, deps, jira, account_id)

    conv_cache.add_turn(req.conversation_id, "user", req.message)
    conv_cache.add_turn(req.conversation_id, "assistant", response)
    return {"response": response}


async def _process_chat_turn(message: str, deps, jira, account_id: str) -> str:
    from src.cache import conversational as conv_cache
    from src.formatting.responses import (
        format_assign_success,
        format_comment_success,
        format_create_ticket_success,
        format_jira_unavailable,
        format_update_priority_success,
        format_update_status_failed,
        format_update_status_success,
    )
    from src.nlu import agent as nlu

    pending = conv_cache.get_pending(deps.conversation_id)

    if pending and _CONFIRM_RE.search(message):
        conv_cache.clear_pending(deps.conversation_id)
        try:
            if pending.tool == "comentar_ticket":
                await jira.add_comment(pending.args["chave"], pending.args["texto"], account_id)
                return format_comment_success(pending.args["chave"])

            if pending.tool == "criar_ticket":
                key = await jira.create_ticket(
                    project_key=pending.args["project"],
                    summary=pending.args["summary"],
                    issue_type=pending.args.get("issue_type", "Task"),
                    priority=pending.args.get("priority"),
                    account_id=account_id,
                )
                return format_create_ticket_success(key, pending.args["summary"])

            if pending.tool == "atualizar_status":
                ok = await jira.transition_ticket(pending.args["chave"], pending.args["status"])
                if ok:
                    return format_update_status_success(pending.args["chave"], pending.args["status"])
                return format_update_status_failed(pending.args["chave"])

            if pending.tool == "atualizar_prioridade":
                await jira.update_priority(pending.args["chave"], pending.args["priority"])
                return format_update_priority_success(pending.args["chave"], pending.args["priority"])

            if pending.tool == "atribuir_ticket":
                await jira.assign_ticket(pending.args["chave"], account_id)
                return format_assign_success(pending.args["chave"])
        except Exception:
            return format_jira_unavailable()

        return "Ação confirmada."

    if pending and _REJECT_RE.search(message):
        conv_cache.clear_pending(deps.conversation_id)
        return "Ação cancelada."

    return await nlu.run(message, deps)


# ── Bot Framework endpoint ───────────────────────────────────────────────────

@app.post("/api/messages")
async def messages(request: Request):
    if "application/json" not in request.headers.get("Content-Type", ""):
        return Response(status_code=415)

    body = await request.json()
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    adapter, bot = _get_adapter_and_bot()
    try:
        await adapter.process_activity(activity, auth_header, bot.on_turn)
    except Exception as e:
        logger.warning("process_activity_error", error=str(e))

    # Send reply directly via httpx (bypasses SDK connector issues with emulator)
    from src.adapters.teams import pending_replies, send_reply_direct
    conv_id = activity.conversation.id if activity.conversation else ""
    response_text = pending_replies.pop(conv_id, None)
    if response_text and activity.service_url:
        await send_reply_direct(activity.service_url, activity, response_text)

    return Response(status_code=201)


@app.get("/health")
async def health():
    return {"status": "ok", "model": settings.openrouter_model, "jira_url": settings.jira_url}
