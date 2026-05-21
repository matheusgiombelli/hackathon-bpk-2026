from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Optional

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import settings
from src.jira.models import JiraTicket, JiraUser

logger = structlog.get_logger(__name__)

# Status labels Jira → português
STATUS_MAP = {
    "pendente": ["To Do", "Open", "Backlog", "Em aberto"],
    "em_andamento": ["In Progress", "Em andamento", "In Review", "Em revisão"],
    "concluido": ["Done", "Closed", "Resolved", "Concluído", "Fechado"],
}

# português → JQL status values
STATUS_JQL_MAP: dict[str, list[str]] = {k: v for k, v in STATUS_MAP.items()}


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    timeout_seconds: int = 60
    failures: int = 0
    last_failure_time: float = 0.0
    _state: str = "closed"
    _lock: Lock = field(default_factory=Lock)

    def is_open(self) -> bool:
        with self._lock:
            if self._state == "open":
                if time.monotonic() - self.last_failure_time > self.timeout_seconds:
                    self._state = "half-open"
                    return False
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            self._state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            self.last_failure_time = time.monotonic()
            if self.failures >= self.failure_threshold:
                self._state = "open"


def _escape_jql(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def _build_jql(
    account_id: str,
    status: Optional[str],
    projeto: Optional[str],
    atrasados: bool,
) -> str:
    conditions: list[str] = [f'assignee = "{_escape_jql(account_id)}"']

    if status:
        jql_statuses = STATUS_JQL_MAP.get(status.lower(), [status])
        escaped = [f'"{_escape_jql(s)}"' for s in jql_statuses]
        conditions.append(f"status IN ({', '.join(escaped)})")

    if projeto:
        conditions.append(f'project = "{_escape_jql(projeto.upper())}"')

    if atrasados:
        conditions.append("duedate < now()")
        conditions.append('status NOT IN ("Done", "Closed", "Resolved", "Concluído")')

    conditions.append("ORDER BY updated DESC")
    return " AND ".join(c for c in conditions if "ORDER BY" not in c) + " ORDER BY updated DESC"


def _parse_ticket(issue: dict) -> JiraTicket:
    fields = issue.get("fields", {})

    def parse_user(u: Optional[dict]) -> Optional[JiraUser]:
        if not u:
            return None
        return JiraUser(
            account_id=u.get("accountId", ""),
            display_name=u.get("displayName", ""),
            email_address=u.get("emailAddress"),
        )

    def parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
            try:
                return datetime.strptime(s[:26].replace("Z", "+00:00"), fmt)
            except ValueError:
                continue
        return None

    due_raw = fields.get("duedate") or fields.get("due")
    due_dt = None
    if due_raw:
        try:
            due_dt = datetime.strptime(due_raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    priority = fields.get("priority") or {}

    return JiraTicket(
        key=issue["key"],
        summary=fields.get("summary", "(sem título)"),
        project_key=fields.get("project", {}).get("key", ""),
        project_name=fields.get("project", {}).get("name", ""),
        status=fields.get("status", {}).get("name", ""),
        priority=priority.get("name") if isinstance(priority, dict) else None,
        assignee=parse_user(fields.get("assignee")),
        reporter=parse_user(fields.get("reporter")),
        created=parse_dt(fields.get("created")) or datetime.now(tz=timezone.utc),
        updated=parse_dt(fields.get("updated")) or datetime.now(tz=timezone.utc),
        due_date=due_dt,
    )


class JiraClient:
    def __init__(self) -> None:
        token = base64.b64encode(
            f"{settings.jira_email}:{settings.jira_api_token}".encode()
        ).decode()
        self._base_url = settings.jira_url.rstrip("/")
        self._headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._timeout = httpx.Timeout(settings.jira_timeout)
        self._circuit = CircuitBreaker(
            failure_threshold=settings.jira_circuit_breaker_threshold,
            timeout_seconds=settings.jira_circuit_breaker_timeout,
        )
        self._comment_hashes: dict[str, float] = {}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None) -> dict:
        if self._circuit.is_open():
            raise RuntimeError("Jira circuit breaker is open")
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            try:
                resp = await client.get(f"{self._base_url}{path}", params=params)
                if resp.status_code == 429:
                    logger.warning("jira_rate_limit", path=path)
                    raise httpx.HTTPStatusError("429", request=resp.request, response=resp)
                resp.raise_for_status()
                self._circuit.record_success()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as e:
                self._circuit.record_failure()
                raise e

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _post(self, path: str, body: dict) -> dict:
        if self._circuit.is_open():
            raise RuntimeError("Jira circuit breaker is open")
        async with httpx.AsyncClient(headers=self._headers, timeout=self._timeout) as client:
            try:
                resp = await client.post(f"{self._base_url}{path}", json=body)
                resp.raise_for_status()
                self._circuit.record_success()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as e:
                self._circuit.record_failure()
                raise e

    async def search_tickets(
        self,
        account_id: str,
        status: Optional[str] = None,
        projeto: Optional[str] = None,
        atrasados: bool = False,
        limite: int = 10,
    ) -> list[JiraTicket]:
        jql = _build_jql(account_id, status, projeto, atrasados)
        fields = ["summary", "project", "status", "priority", "assignee", "reporter",
                  "created", "updated", "duedate"]
        logger.info("jira_search", jql=jql, limit=limite)
        # Jira Cloud deprecated GET /search — use POST /search/jql (Atlassian change #CHANGE-2046)
        data = await self._post(
            "/rest/api/3/search/jql",
            {"jql": jql, "maxResults": limite, "fields": fields},
        )
        return [_parse_ticket(issue) for issue in data.get("issues", [])]

    async def get_ticket(self, key: str) -> Optional[JiraTicket]:
        try:
            data = await self._get(f"/rest/api/3/issue/{key}")
            return _parse_ticket(data)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def add_comment(self, key: str, text: str, author_account_id: str) -> bool:
        # Idempotency: same comment within 60s → skip
        hash_key = hashlib.sha256(f"{key}:{author_account_id}:{text}".encode()).hexdigest()
        now = time.monotonic()
        if hash_key in self._comment_hashes and now - self._comment_hashes[hash_key] < 60:
            logger.info("comment_duplicate_skipped", ticket=key)
            return True
        body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
            }
        }
        await self._post(f"/rest/api/3/issue/{key}/comment", body)
        self._comment_hashes[hash_key] = now
        logger.info("comment_added", ticket=key)
        return True

    async def find_account_by_email(self, email: str) -> Optional[str]:
        try:
            data = await self._get("/rest/api/3/user/search", params={"query": email})
            users = data if isinstance(data, list) else data.get("values", [])
            for user in users:
                if user.get("emailAddress", "").lower() == email.lower():
                    return user.get("accountId")
        except Exception:
            pass
        return None
