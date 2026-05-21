import hashlib
import json
from typing import Any, Optional
from cachetools import TTLCache

from src.config import settings

_cache: TTLCache = TTLCache(maxsize=500, ttl=settings.jira_cache_ttl)


def _make_key(account_id: str, operation: str, params: dict) -> str:
    raw = json.dumps({"account_id": account_id, "op": operation, "params": params}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def get(account_id: str, operation: str, params: dict) -> Optional[Any]:
    return _cache.get(_make_key(account_id, operation, params))


def set(account_id: str, operation: str, params: dict, value: Any) -> None:
    _cache[_make_key(account_id, operation, params)] = value


def invalidate_ticket(ticket_key: str) -> None:
    to_remove = [k for k in _cache if ticket_key in str(_cache[k])]
    for k in to_remove:
        _cache.pop(k, None)
