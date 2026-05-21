import os
from contextlib import asynccontextmanager

import structlog
from botbuilder.schema import Activity
from fastapi import FastAPI, Request, Response

from src.config import settings
from src.observability.logging_config import configure_logging

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("logs", exist_ok=True)
    configure_logging(log_level=settings.log_level, log_file=settings.log_file)
    logger.info("startup", port=settings.port, model=settings.openrouter_model)
    yield
    logger.info("shutdown")


app = FastAPI(title="Jira Teams Bot — Biopark Hackathon", lifespan=lifespan)

# Lazy init to allow settings to be fully loaded first
_adapter = None
_bot = None


def _get_adapter_and_bot():
    global _adapter, _bot
    if _adapter is None:
        from src.adapters.teams import BotApp, create_adapter
        _adapter = create_adapter()
        _bot = BotApp()
    return _adapter, _bot


@app.post("/api/messages")
async def messages(request: Request):
    if "application/json" not in request.headers.get("Content-Type", ""):
        return Response(status_code=415)

    body = await request.json()
    activity = Activity().deserialize(body)
    auth_header = request.headers.get("Authorization", "")

    adapter, bot = _get_adapter_and_bot()
    invoke_response = await adapter.process_activity(activity, auth_header, bot.on_turn)

    if invoke_response:
        return Response(
            content=invoke_response.body,
            status_code=invoke_response.status,
            media_type="application/json",
        )
    return Response(status_code=201)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": settings.openrouter_model,
        "jira_url": settings.jira_url,
    }


@app.get("/")
async def root():
    return {"message": "Jira Teams Bot is running. POST to /api/messages"}
