"""Each user's results, kept in Supabase so they outlive the process.

The in-memory task store forgets everything on restart. With Supabase
configured, every completed task is also written to the project's
``analyses`` table, and the history and result endpoints read it back.

Every call is made *as the user*: with their own access token and the
project's publishable key, never a service key. Row level security on the
table is therefore what keeps one user's history from another's -- a bug here
could not leak someone else's results, because the database would refuse.

Saving is best effort. An analysis that ran is not failed because the history
service hiccuped; the result is still returned and kept in memory.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app import USER_AGENT
from app.auth import User
from app.config.logging_config import get_logger
from app.config.settings import Settings, get_settings

logger = get_logger("history")

TABLE = "analyses"
SUMMARY_COLUMNS = "id,query,status,outcome,answer,tool,created_at"


class HistoryUnavailable(Exception):
    """The history table could not be reached."""


def _request(
    user: User,
    method: str,
    path: str,
    settings: Settings,
    body: Any = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    url = f"{settings.supabase_url}/rest/v1/{path}"
    headers = {
        "apikey": settings.supabase_publishable_key,
        "Authorization": f"Bearer {user.token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        **(extra_headers or {}),
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise HistoryUnavailable(f"history service answered HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise HistoryUnavailable(f"history service unreachable: {error}") from error
    return json.loads(raw) if raw else None


def save(user: User, response: dict[str, Any], settings: Settings | None = None) -> bool:
    """Record one task response for ``user``. Returns whether it was stored."""
    settings = settings or get_settings()
    row = {
        "id": response["task_id"],
        "user_id": user.id,
        "query": response["query"][:2000],
        "status": response["status"],
        "outcome": response["outcome"],
        "answer": response["answer"],
        "tool": response.get("tool"),
        "response": response,
    }
    try:
        _request(user, "POST", TABLE, settings, body=row,
                 extra_headers={"Prefer": "return=minimal"})
    except HistoryUnavailable as error:
        logger.warning("result not saved to history", extra={"task_id": row["id"], "reason": str(error)})
        return False
    return True


def fetch(user: User, task_id: str, settings: Settings | None = None) -> dict[str, Any] | None:
    """One of ``user``'s stored task responses, or ``None``."""
    settings = settings or get_settings()
    query = urllib.parse.urlencode({"id": f"eq.{task_id}", "select": "response"})
    rows = _request(user, "GET", f"{TABLE}?{query}", settings)
    if not rows:
        return None
    return rows[0]["response"]


def recent(user: User, limit: int, settings: Settings | None = None) -> list[dict[str, Any]]:
    """``user``'s most recent tasks, newest first, as summary rows."""
    settings = settings or get_settings()
    query = urllib.parse.urlencode(
        {"select": SUMMARY_COLUMNS, "order": "created_at.desc", "limit": str(limit)}
    )
    return _request(user, "GET", f"{TABLE}?{query}", settings) or []


__all__ = ["HistoryUnavailable", "fetch", "recent", "save"]
