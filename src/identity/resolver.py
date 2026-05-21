from __future__ import annotations

import json
import os
from typing import Optional

import structlog
from cachetools import TTLCache

from src.config import settings

logger = structlog.get_logger(__name__)

_USER_MAPPING_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "user_mapping.json"
)

_static_map: dict[str, str] = {}
_cache: TTLCache = TTLCache(maxsize=500, ttl=settings.identity_cache_ttl)


def _load_static_map() -> None:
    global _static_map
    try:
        with open(_USER_MAPPING_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _static_map = {
            u["teams_email"].lower(): u["jira_account_id"]
            for u in data.get("users", [])
        }
        logger.info("identity_mapping_loaded", count=len(_static_map))
    except FileNotFoundError:
        logger.warning("identity_mapping_not_found", path=_USER_MAPPING_PATH)
    except Exception as e:
        logger.error("identity_mapping_load_error", error=str(e))


_load_static_map()


async def resolve(teams_email: str, jira_client=None) -> Optional[str]:
    """Map a Teams email to a Jira account_id. Returns None if not found."""
    key = teams_email.lower()

    if key in _cache:
        logger.debug("identity_cache_hit", email=key)
        return _cache[key]

    # Static lookup
    account_id = _static_map.get(key)
    if account_id:
        _cache[key] = account_id
        logger.info("identity_resolved_static", email=key)
        return account_id

    # Fallback: Jira API
    if jira_client:
        account_id = await jira_client.find_account_by_email(key)
        if account_id:
            _cache[key] = account_id
            logger.info("identity_resolved_jira_api", email=key)
            return account_id

    logger.warning("identity_unresolved", email=key)
    return None


def reload_mapping() -> None:
    """Hot-reload the static user mapping file."""
    _load_static_map()
    _cache.clear()
