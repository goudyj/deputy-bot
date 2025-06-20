"""
Sentry models for issues and statistics
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SentryIssue(BaseModel):
    """Represents a Sentry issue"""

    id: str
    title: str
    culprit: str | None = None
    permalink: str
    short_id: str
    status: str
    level: str
    type: str
    count: int
    user_count: int
    first_seen: datetime
    last_seen: datetime
    project: dict[str, Any]
    metadata: dict[str, Any] | None = None
    tags: list[dict[str, Any]] = []


class SentryStats(BaseModel):
    """Represents Sentry statistics for a period"""

    period: str
    total_events: int
    total_issues: int
    resolved_issues: int
    new_issues: int
    top_issues: list[SentryIssue]


class SentrySearchFilter(BaseModel):
    """Search filters for Sentry issues"""

    query: str = ""
    status: str = "unresolved"  # unresolved, resolved, ignored
    level: str = ""  # error, warning, info, debug
    project: str = ""
    environment: str = ""
    period: str = "24h"  # Only 24h and 7d supported
    sort: str = "date"  # date, priority, freq, user
    limit: int = 10
