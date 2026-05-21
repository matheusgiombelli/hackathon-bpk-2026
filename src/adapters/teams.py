"""
Teams adapter — Layer 1.
Thin wrapper: extracts user info from Bot Framework Activity,
orchestrates the 7-layer pipeline, and sends the response back.
"""
from __future__ import annotations

import re
import uuid

import structlog
from botbuilder.core import (
    ActivityHandler,
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity, ActivityTypes

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


def create_adapter() -> BotFrameworkAdapter:
    adapter_settings = BotFrameworkAdapterSettings(
        app_id=settings.microsoft_app_id,
        app_password=settings.microsoft_app_password,
    )
    adapter = BotFrameworkAdapter(adapter_settings)

    async def on_error(context: TurnContext, error: Exception):
        logger.error("adapter_error", error=str(error), type=type(error).__name__)
        await context.send_activity("Ocorreu um erro interno. Tente novamente.")

    adapter.on_turn_error = on_error
    return adapter


class BotApp(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext) -> None:
        activity: Activity = turn_context.activity
        correlation_id = str(uuid.uuid4())

        # Extract user info (Layer 1)
        teams_email = (
            (activity.from_property and activity.from_property.name) or ""
        )
        # Try aadObjectId path first, fall back to from.name
        if hasattr(activity, "from_property") and activity.from_property:
            fp = activity.from_property
            # In real Teams, the email is often in from_property.name or channel_data
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
            # For local emulator testing without real Teams: use email as account_id stub
            if settings.microsoft_app_id == "":
                account_id = f"stub:{teams_email or 'emulator-user'}"
                logger.warning("identity_stub_mode", account_id=account_id)
            else:
                await turn_context.send_activity(format_identity_unknown())
                return

        # Check for pending confirmation (pre-NLU)
        pending = conv_cache.get_pending(conversation_id)
        if pending:
            response = await self._handle_confirmation(pending, message_text, account_id, conversation_id)
            if response is not None:
                await turn_context.send_activity(response)
                logger.info("response_sent", length=len(response))
                return

        # Layers 3-6 — NLU → Authorization → Jira → Format
        deps = Deps(
            account_id=account_id,
            jira=_jira_client,
            conversation_id=conversation_id,
        )

        response = await nlu.run(message_text, deps)

        logger.info("response_sent", length=len(response))
        await turn_context.send_activity(response)

    async def _handle_confirmation(
        self,
        pending: conv_cache.PendingAction,
        message: str,
        account_id: str,
        conversation_id: str,
    ) -> str | None:
        """
        Returns a response string if the message is a confirmation/rejection,
        or None if it should fall through to NLU.
        """
        if _CONFIRM_RE.search(message):
            conv_cache.clear_pending(conversation_id)
            if pending.tool == "comentar_ticket":
                chave = pending.args["chave"]
                texto = pending.args["texto"]
                try:
                    await _jira_client.add_comment(chave, texto, account_id)
                    from src.formatting.responses import format_comment_success
                    return format_comment_success(chave)
                except RuntimeError:
                    return format_jira_unavailable()
                except Exception as e:
                    logger.error("confirm_comment_error", error=str(e))
                    return format_jira_unavailable()
            return "Ação confirmada."

        elif _REJECT_RE.search(message):
            conv_cache.clear_pending(conversation_id)
            return "Ação cancelada."

        # Not a clear confirmation/rejection — let NLU handle it
        # but first clear the stale pending action
        conv_cache.clear_pending(conversation_id)
        return None

    async def on_members_added_activity(self, members_added, turn_context: TurnContext) -> None:
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    "Olá! 👋 Sou o assistente de tickets Jira da Biopark.\n\n"
                    "Posso te ajudar com:\n"
                    "• Ver seus tickets pendentes ou atrasados\n"
                    "• Detalhar um ticket específico\n"
                    "• Registrar comentários em tickets\n\n"
                    "Experimente: _\"Quais meus tickets estão atrasados?\"_"
                )
