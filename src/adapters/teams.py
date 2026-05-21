"""
Teams adapter — Layer 1.
Thin wrapper: extracts user info from Bot Framework Activity,
orchestrates the 7-layer pipeline, and sends the response back.
"""
from __future__ import annotations

import re
import uuid

import httpx
import structlog
from botbuilder.core import (
    ActivityHandler,
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity

from src.identity import resolver as identity_resolver
from src.cache import conversational as conv_cache
from src.config import settings
from src.formatting.responses import format_identity_unknown, format_jira_unavailable
from src.jira.client import JiraClient
from src.nlu import agent as nlu
from src.nlu.tools import Deps

logger = structlog.get_logger(__name__)

_CONFIRM_RE = re.compile(r"\b(sim|yes|confirmar|confirmo|ok|pode|claro|positivo|s)\b", re.IGNORECASE)
_REJECT_RE = re.compile(r"\b(n[aã]o|no|cancelar|cancela|cancel|negativo|n)\b", re.IGNORECASE)

_jira_client = JiraClient()

# Stores pending replies: conversation_id → response text
# main.py reads this after process_activity to send via httpx
pending_replies: dict[str, str] = {}


def create_adapter() -> BotFrameworkAdapter:
    app_id = settings.microsoft_app_id or None
    app_password = settings.microsoft_app_password or None
    adapter_settings = BotFrameworkAdapterSettings(
        app_id=app_id,
        app_password=app_password,
    )
    adapter = BotFrameworkAdapter(adapter_settings)

    async def on_error(context: TurnContext, error: Exception):
        logger.error("adapter_error", error=str(error), type=type(error).__name__)

    adapter.on_turn_error = on_error
    return adapter


async def send_reply_direct(service_url: str, activity: Activity, text: str) -> bool:
    """Send reply directly via httpx, bypassing botbuilder SDK connector."""
    conv_id = activity.conversation.id if activity.conversation else ""
    reply_to_id = activity.id or ""
    from_id = (activity.recipient.id if activity.recipient else "") or "bot"
    from_name = (activity.recipient.name if activity.recipient else "") or "Bot"

    reply_body = {
        "type": "message",
        "text": text,
        "textFormat": "plain",
        "locale": "pt-BR",
        "from": {"id": from_id, "name": from_name},
        "conversation": {"id": conv_id},
        "replyToId": reply_to_id,
    }

    # Try reply_to_activity first, fall back to send_to_conversation
    urls = [
        f"{service_url}/v3/conversations/{conv_id}/activities/{reply_to_id}",
        f"{service_url}/v3/conversations/{conv_id}/activities",
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in urls:
            try:
                resp = await client.post(
                    url,
                    json=reply_body,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code < 300:
                    logger.info("reply_sent_direct", url=url, status=resp.status_code)
                    return True
                logger.warning("reply_attempt_failed", url=url, status=resp.status_code, body=resp.text[:500])
            except Exception as e:
                logger.warning("reply_attempt_error", url=url, error=repr(e), type=type(e).__name__)

    return False


class BotApp(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity: Activity = turn_context.activity
        correlation_id = str(uuid.uuid4())

        # Extract user info (Layer 1)
        teams_email = (activity.from_property and activity.from_property.name) or ""
        channel_data = activity.channel_data or {}
        if "from" in channel_data and "userPrincipalName" in channel_data.get("from", {}):
            teams_email = channel_data["from"]["userPrincipalName"]

        conversation_id = activity.conversation.id if activity.conversation else correlation_id
        message_text = (activity.text or "").strip()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            teams_email=teams_email,
            conversation_id=conversation_id,
        )

        logger.info("message_received", text_length=len(message_text))

        if not message_text:
            return

        # Layer 2 — Resolve identity
        account_id = await identity_resolver.resolve(teams_email, _jira_client)
        if not account_id:
            if settings.microsoft_app_id == "":
                account_id = "712020:e6cacdff-637c-41b8-a960-49711fe6dc2f"
                logger.info("identity_emulator_mode", account_id=account_id)
            else:
                pending_replies[conversation_id] = format_identity_unknown()
                return

        # Check for pending confirmation (pre-NLU)
        pending = conv_cache.get_pending(conversation_id)
        if pending:
            response = await self._handle_confirmation(pending, message_text, account_id, conversation_id)
            if response is not None:
                pending_replies[conversation_id] = response
                logger.info("response_stored", length=len(response))
                return

        # Layers 3-6 — NLU → Authorization → Jira → Format
        deps = Deps(
            account_id=account_id,
            jira=_jira_client,
            conversation_id=conversation_id,
        )

        response = await nlu.run(message_text, deps)
        pending_replies[conversation_id] = response
        logger.info("response_stored", length=len(response))

    async def _handle_confirmation(
        self,
        pending: conv_cache.PendingAction,
        message: str,
        account_id: str,
        conversation_id: str,
    ) -> str | None:
        if _CONFIRM_RE.search(message):
            conv_cache.clear_pending(conversation_id)
            if pending.tool == "comentar_ticket":
                chave = pending.args["chave"]
                texto = pending.args["texto"]
                try:
                    await _jira_client.add_comment(chave, texto, account_id)
                    from src.formatting.responses import format_comment_success
                    return format_comment_success(chave)
                except Exception as e:
                    logger.error("confirm_comment_error", error=str(e))
                    return format_jira_unavailable()
            return "Acao confirmada."

        elif _REJECT_RE.search(message):
            conv_cache.clear_pending(conversation_id)
            return "Acao cancelada."

        conv_cache.clear_pending(conversation_id)
        return None

    async def on_members_added_activity(self, members_added, turn_context: TurnContext) -> None:
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                activity = turn_context.activity
                conv_id = activity.conversation.id if activity.conversation else ""
                pending_replies[conv_id] = (
                    "Ola! Sou o assistente de tickets Jira da Biopark.\n\n"
                    "Experimente: meus tickets, tickets atrasados, detalha KAN-5"
                )
