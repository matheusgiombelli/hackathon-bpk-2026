from __future__ import annotations
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


# TTLCache keyed by teams_conversation_id
_cache: TTLCache = TTLCache(maxsize=1000, ttl=settings.conversation_cache_ttl)


def get_pending(conversation_id: str) -> Optional[PendingAction]:
    return _cache.get(conversation_id)


def set_pending(conversation_id: str, action: PendingAction) -> None:
    _cache[conversation_id] = action


def clear_pending(conversation_id: str) -> None:
    _cache.pop(conversation_id, None)
