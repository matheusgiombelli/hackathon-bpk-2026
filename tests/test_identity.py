"""Unit tests for identity resolution (static mapping)."""
import json
import os
import tempfile

import pytest

import src.identity.resolver as resolver_module


@pytest.fixture(autouse=True)
def reset_cache():
    resolver_module._cache.clear()
    yield
    resolver_module._cache.clear()


@pytest.fixture
def tmp_mapping(tmp_path):
    mapping = {
        "users": [
            {
                "teams_email": "alice@biopark.com.br",
                "teams_user_id": "29:alice",
                "jira_account_id": "jira-alice-001",
                "display_name": "Alice",
            },
            {
                "teams_email": "BOB@BIOPARK.COM.BR",
                "teams_user_id": "29:bob",
                "jira_account_id": "jira-bob-002",
                "display_name": "Bob",
            },
        ]
    }
    p = tmp_path / "user_mapping.json"
    p.write_text(json.dumps(mapping))
    original = resolver_module._USER_MAPPING_PATH
    resolver_module._USER_MAPPING_PATH = str(p)
    resolver_module._load_static_map()
    yield
    resolver_module._USER_MAPPING_PATH = original
    resolver_module._load_static_map()


@pytest.mark.asyncio
async def test_known_email_resolves(tmp_mapping):
    account_id = await resolver_module.resolve("alice@biopark.com.br")
    assert account_id == "jira-alice-001"


@pytest.mark.asyncio
async def test_email_case_insensitive(tmp_mapping):
    account_id = await resolver_module.resolve("ALICE@BIOPARK.COM.BR")
    assert account_id == "jira-alice-001"


@pytest.mark.asyncio
async def test_stored_uppercase_key_is_normalized(tmp_mapping):
    account_id = await resolver_module.resolve("bob@biopark.com.br")
    assert account_id == "jira-bob-002"


@pytest.mark.asyncio
async def test_unknown_email_returns_none(tmp_mapping):
    account_id = await resolver_module.resolve("unknown@biopark.com.br")
    assert account_id is None


@pytest.mark.asyncio
async def test_result_is_cached(tmp_mapping):
    await resolver_module.resolve("alice@biopark.com.br")
    # Corrupt the static map to prove the cached value is used
    resolver_module._static_map.clear()
    account_id = await resolver_module.resolve("alice@biopark.com.br")
    assert account_id == "jira-alice-001"
