from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from cachetools import TTLCache

from src.config import settings


@dataclass
class PendingAction:
    tool: str           # e.g. "comentar_ticket"
    args: dict          # tool arguments
    created_at: datetime = field(default_factory=datetime.utcnow)


# Pending actions awaiting "sim/não" confirmation.
_cache: TTLCache = TTLCache(maxsize=1000, ttl=settings.conversation_cache_ttl)

# Short rolling history per conversation_id — last N turns of {role, content}.
_history_cache: TTLCache = TTLCache(maxsize=1000, ttl=settings.conversation_cache_ttl)
_MAX_HISTORY_TURNS = 6


def get_pending(conversation_id: str) -> Optional[PendingAction]:
    return _cache.get(conversation_id)


def set_pending(conversation_id: str, action: PendingAction) -> None:
    _cache[conversation_id] = action


def clear_pending(conversation_id: str) -> None:
    _cache.pop(conversation_id, None)


def add_turn(conversation_id: str, role: str, content: str) -> None:
    """Append a turn (role: 'user' | 'assistant') to the conversation history."""
    hist = _history_cache.get(conversation_id)
    if hist is None:
        hist = deque(maxlen=_MAX_HISTORY_TURNS)
    hist.append({"role": role, "content": content})
    _history_cache[conversation_id] = hist


def get_history(conversation_id: str) -> list[dict]:
    hist = _history_cache.get(conversation_id)
    return list(hist) if hist else []


def clear_history(conversation_id: str) -> None:
    _history_cache.pop(conversation_id, None)
