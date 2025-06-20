"""
Sentry integration service for error monitoring and issue retrieval
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from deputy.models.config import SentryConfig
from deputy.models.sentry import SentryIssue, SentrySearchFilter, SentryStats


class SentryIntegration:
    """Service for interacting with Sentry API"""

    def __init__(self, config: SentryConfig):
        self.config = config
        self.base_url = "https://sentry.io/api/0"
        self.headers = {
            "Authorization": f"Bearer {config.auth_token}",
            "Content-Type": "application/json",
        }

    def _parse_duration(self, period: str) -> tuple[datetime, str]:
        """Parse duration string - only supports '24h' and '7d'"""
        now = datetime.now(UTC)

        # Only allow specific periods
        if period == "24h":
            return now - timedelta(hours=24), "24h"
        elif period == "7d":
            return now - timedelta(days=7), "14d"  # Use 14d API period, filter to 7d
        else:
            # Invalid period - raise error instead of defaulting
            raise ValueError(
                f"Invalid period '{period}'. Only '24h' and '7d' are supported."
            )

    async def _make_request(
        self, endpoint: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make authenticated request to Sentry API"""
        url = f"{self.base_url}/{endpoint}"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=self.headers, params=params
            ) as response:
                response.raise_for_status()
                return await response.json()

    async def get_top_issues(
        self, period: str = "24h", limit: int = 10, status: str = "unresolved"
    ) -> list[SentryIssue]:
        """Get top Sentry issues for a given period"""
        if not self.config.is_configured():
            raise ValueError("Sentry is not properly configured")

        start_time, api_period = self._parse_duration(period)

        params = {
            "query": f"is:{status}",
            "sort": "freq",
            "limit": limit,
            "statsPeriod": api_period,
        }

        endpoint = f"projects/{self.config.org}/{self.config.project}/issues/"
        data = await self._make_request(endpoint, params)

        issues = []
        for issue_data in data:
            issue = SentryIssue(
                id=issue_data["id"],
                title=issue_data["title"],
                culprit=issue_data.get("culprit"),
                permalink=issue_data["permalink"],
                short_id=issue_data["shortId"],
                status=issue_data["status"],
                level=issue_data["level"],
                type=issue_data["type"],
                count=issue_data.get("count", 0),
                user_count=issue_data.get("userCount", 0),
                first_seen=datetime.fromisoformat(
                    issue_data["firstSeen"].replace("Z", "+00:00")
                ),
                last_seen=datetime.fromisoformat(
                    issue_data["lastSeen"].replace("Z", "+00:00")
                ),
                project=issue_data["project"],
                metadata=issue_data.get("metadata"),
                tags=issue_data.get("tags", []),
            )

            # For 7d period, filter to last 7 days (since we use 14d API period)
            if period == "7d" and issue.last_seen >= start_time:
                issues.append(issue)
            elif period == "24h":
                issues.append(issue)

        # Sort by count (frequency) and limit
        issues.sort(key=lambda x: x.count, reverse=True)
        return issues[:limit]

    async def search_issues(self, filters: SentrySearchFilter) -> list[SentryIssue]:
        """Search Sentry issues with filters"""
        if not self.config.is_configured():
            raise ValueError("Sentry is not properly configured")

        # Build query string
        query_parts = []
        if filters.status:
            query_parts.append(f"is:{filters.status}")
        if filters.level:
            query_parts.append(f"level:{filters.level}")
        if filters.environment:
            query_parts.append(f"environment:{filters.environment}")
        if filters.query:
            query_parts.append(filters.query)

        query = " ".join(query_parts)

        start_time, api_period = self._parse_duration(filters.period)

        params = {
            "query": query,
            "sort": filters.sort,
            "limit": filters.limit,
            "statsPeriod": api_period,
        }

        endpoint = f"projects/{self.config.org}/{self.config.project}/issues/"
        data = await self._make_request(endpoint, params)

        issues = []
        for issue_data in data:
            issue = SentryIssue(
                id=issue_data["id"],
                title=issue_data["title"],
                culprit=issue_data.get("culprit"),
                permalink=issue_data["permalink"],
                short_id=issue_data["shortId"],
                status=issue_data["status"],
                level=issue_data["level"],
                type=issue_data["type"],
                count=issue_data.get("count", 0),
                user_count=issue_data.get("userCount", 0),
                first_seen=datetime.fromisoformat(
                    issue_data["firstSeen"].replace("Z", "+00:00")
                ),
                last_seen=datetime.fromisoformat(
                    issue_data["lastSeen"].replace("Z", "+00:00")
                ),
                project=issue_data["project"],
                metadata=issue_data.get("metadata"),
                tags=issue_data.get("tags", []),
            )
            issues.append(issue)

        return issues

    async def get_issue_details(self, issue_id: str) -> SentryIssue | None:
        """Get detailed information about a specific Sentry issue"""
        if not self.config.is_configured():
            raise ValueError("Sentry is not properly configured")

        try:
            endpoint = f"issues/{issue_id}/"
            issue_data = await self._make_request(endpoint)

            return SentryIssue(
                id=issue_data["id"],
                title=issue_data["title"],
                culprit=issue_data.get("culprit"),
                permalink=issue_data["permalink"],
                short_id=issue_data["shortId"],
                status=issue_data["status"],
                level=issue_data["level"],
                type=issue_data["type"],
                count=issue_data.get("count", 0),
                user_count=issue_data.get("userCount", 0),
                first_seen=datetime.fromisoformat(
                    issue_data["firstSeen"].replace("Z", "+00:00")
                ),
                last_seen=datetime.fromisoformat(
                    issue_data["lastSeen"].replace("Z", "+00:00")
                ),
                project=issue_data["project"],
                metadata=issue_data.get("metadata"),
                tags=issue_data.get("tags", []),
            )
        except Exception:
            return None

    async def get_project_stats(self, period: str = "24h") -> SentryStats:
        """Get project statistics for a given period"""
        if not self.config.is_configured():
            raise ValueError("Sentry is not properly configured")

        start_time, api_period = self._parse_duration(period)

        # Get top issues for the period
        top_issues = await self.get_top_issues(period, limit=5)

        # Get issue counts
        issues_endpoint = f"projects/{self.config.org}/{self.config.project}/issues/"

        # Total issues
        total_params = {"statsPeriod": api_period}
        total_data = await self._make_request(issues_endpoint, total_params)
        total_issues = len(total_data)

        # Resolved issues
        resolved_params = {"query": "is:resolved", "statsPeriod": api_period}
        resolved_data = await self._make_request(issues_endpoint, resolved_params)
        resolved_issues = len(resolved_data)

        # Calculate total events from top issues
        total_events = sum(issue.count for issue in top_issues)

        # New issues (approximate by checking first_seen)
        new_issues = sum(1 for issue in top_issues if issue.first_seen >= start_time)

        return SentryStats(
            period=period,
            total_events=total_events,
            total_issues=total_issues,
            resolved_issues=resolved_issues,
            new_issues=new_issues,
            top_issues=top_issues,
        )

    def format_issue_summary(self, issue: SentryIssue) -> str:
        """Format a Sentry issue for display in chat"""
        level_emoji = {
            "error": "🔴",
            "warning": "🟡",
            "info": "🔵",
            "debug": "⚪",
        }.get(issue.level, "❓")

        # Format count
        count_str = (
            f"{issue.count:,}" if issue.count < 1000 else f"{issue.count / 1000:.1f}k"
        )

        # Format time
        time_ago = self._format_time_ago(issue.last_seen)

        return (
            f"{level_emoji} **{issue.short_id}**: {issue.title}\n"
            f"   💥 {count_str} events • 👥 {issue.user_count} users • ⏰ {time_ago}\n"
            f"   🔗 {issue.permalink}"
        )

    def _format_time_ago(self, dt: datetime) -> str:
        """Format datetime as 'X time ago'"""
        now = datetime.now(UTC)
        delta = now - dt

        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours}h ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes}m ago"
        else:
            return "just now"
