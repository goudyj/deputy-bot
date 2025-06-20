"""
Tests for SentryIntegration
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from deputy.models.config import SentryConfig
from deputy.models.sentry import SentrySearchFilter
from deputy.services.sentry_integration import SentryIntegration


@pytest.fixture
def mock_sentry_config():
    """Mock SentryConfig for testing"""
    return SentryConfig(
        dsn="https://key@sentry.io/project",
        org="test_org",
        project="test_project",
        auth_token="test_auth_token",
        default_period="24h",
    )


@pytest.fixture
def mock_sentry_issue_data():
    """Mock Sentry issue data"""
    return {
        "id": "12345",
        "title": "DatabaseConnectionError",
        "culprit": "src/database.py in connect",
        "permalink": "https://sentry.io/issues/12345/",
        "shortId": "TEST-1",
        "status": "unresolved",
        "level": "error",
        "type": "error",
        "count": 150,
        "userCount": 25,
        "firstSeen": "2024-06-18T10:00:00.000Z",
        "lastSeen": "2024-06-18T15:30:00.000Z",
        "project": {"id": "1", "name": "test_project"},
        "metadata": {"type": "ConnectionError"},
        "tags": [{"key": "environment", "value": "production"}],
    }


class TestSentryIntegration:
    def test_init(self, mock_sentry_config):
        """Test SentryIntegration initialization"""
        integration = SentryIntegration(mock_sentry_config)

        assert integration.config == mock_sentry_config
        assert integration.base_url == "https://sentry.io/api/0"
        assert integration.headers["Authorization"] == "Bearer test_auth_token"

    def test_parse_duration_24h(self, mock_sentry_config):
        """Test duration parsing for 24h"""
        integration = SentryIntegration(mock_sentry_config)
        start_time, api_period = integration._parse_duration("24h")

        assert api_period == "24h"
        # start_time should be approximately 24 hours ago

    def test_parse_duration_7d(self, mock_sentry_config):
        """Test duration parsing for 7d"""
        integration = SentryIntegration(mock_sentry_config)
        start_time, api_period = integration._parse_duration("7d")

        assert api_period == "14d"  # Maps to 14d API period

    def test_parse_duration_invalid_hours(self, mock_sentry_config):
        """Test duration parsing with invalid hours"""
        integration = SentryIntegration(mock_sentry_config)

        with pytest.raises(
            ValueError, match="Invalid period '12h'. Only '24h' and '7d' are supported."
        ):
            integration._parse_duration("12h")

    def test_parse_duration_invalid_minutes(self, mock_sentry_config):
        """Test duration parsing with invalid minutes"""
        integration = SentryIntegration(mock_sentry_config)

        with pytest.raises(
            ValueError, match="Invalid period '30m'. Only '24h' and '7d' are supported."
        ):
            integration._parse_duration("30m")

    def test_parse_duration_invalid_string(self, mock_sentry_config):
        """Test duration parsing with invalid input"""
        integration = SentryIntegration(mock_sentry_config)

        with pytest.raises(
            ValueError,
            match="Invalid period 'invalid'. Only '24h' and '7d' are supported.",
        ):
            integration._parse_duration("invalid")

    # Note: The _make_request method is tested indirectly through integration tests

    def test_not_configured(self):
        """Test with unconfigured Sentry"""
        config = SentryConfig()  # Empty config
        integration = SentryIntegration(config)

        # Just test that is_configured returns False
        assert not integration.config.is_configured()

    @pytest.mark.asyncio
    async def test_get_top_issues_success(
        self, mock_sentry_config, mock_sentry_issue_data
    ):
        """Test successful top issues retrieval"""
        mock_response_data = [mock_sentry_issue_data]

        with patch.object(
            SentryIntegration, "_make_request", return_value=mock_response_data
        ) as mock_request:
            integration = SentryIntegration(mock_sentry_config)
            issues = await integration.get_top_issues("24h", 10)

            assert len(issues) == 1
            issue = issues[0]
            assert issue.id == "12345"
            assert issue.title == "DatabaseConnectionError"
            assert issue.short_id == "TEST-1"
            assert issue.count == 150
            assert issue.user_count == 25

            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_top_issues_not_configured(self):
        """Test top issues with unconfigured Sentry"""
        config = SentryConfig()  # Empty config
        integration = SentryIntegration(config)

        with pytest.raises(ValueError, match="Sentry is not properly configured"):
            await integration.get_top_issues()

    @pytest.mark.asyncio
    async def test_search_issues_success(
        self, mock_sentry_config, mock_sentry_issue_data
    ):
        """Test successful issue search"""
        mock_response_data = [mock_sentry_issue_data]
        filters = SentrySearchFilter(query="database", period="7d", limit=5)

        with patch.object(
            SentryIntegration, "_make_request", return_value=mock_response_data
        ) as mock_request:
            integration = SentryIntegration(mock_sentry_config)
            issues = await integration.search_issues(filters)

            assert len(issues) == 1
            assert issues[0].title == "DatabaseConnectionError"

            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_issue_details_success(
        self, mock_sentry_config, mock_sentry_issue_data
    ):
        """Test successful issue details retrieval"""
        with patch.object(
            SentryIntegration, "_make_request", return_value=mock_sentry_issue_data
        ) as mock_request:
            integration = SentryIntegration(mock_sentry_config)
            issue = await integration.get_issue_details("12345")

            assert issue is not None
            assert issue.id == "12345"
            assert issue.title == "DatabaseConnectionError"

            mock_request.assert_called_once_with("issues/12345/")

    @pytest.mark.asyncio
    async def test_get_issue_details_not_found(self, mock_sentry_config):
        """Test issue details when issue not found"""
        with patch.object(
            SentryIntegration, "_make_request", side_effect=Exception("Not found")
        ):
            integration = SentryIntegration(mock_sentry_config)
            issue = await integration.get_issue_details("nonexistent")

            assert issue is None

    @pytest.mark.asyncio
    async def test_get_project_stats_success(
        self, mock_sentry_config, mock_sentry_issue_data
    ):
        """Test successful project stats retrieval"""
        mock_issues_data = [mock_sentry_issue_data]

        with patch.object(SentryIntegration, "get_top_issues", return_value=[]):
            with patch.object(
                SentryIntegration, "_make_request", return_value=mock_issues_data
            ):
                integration = SentryIntegration(mock_sentry_config)
                stats = await integration.get_project_stats("24h")

                assert stats.period == "24h"
                assert stats.total_issues == 1
                assert stats.resolved_issues == 1

    def test_format_issue_summary(self, mock_sentry_config, mock_sentry_issue_data):
        """Test issue summary formatting"""
        integration = SentryIntegration(mock_sentry_config)

        # Create a SentryIssue from the mock data
        from deputy.models.sentry import SentryIssue

        issue = SentryIssue(
            id=mock_sentry_issue_data["id"],
            title=mock_sentry_issue_data["title"],
            culprit=mock_sentry_issue_data["culprit"],
            permalink=mock_sentry_issue_data["permalink"],
            short_id=mock_sentry_issue_data["shortId"],
            status=mock_sentry_issue_data["status"],
            level=mock_sentry_issue_data["level"],
            type=mock_sentry_issue_data["type"],
            count=mock_sentry_issue_data["count"],
            user_count=mock_sentry_issue_data["userCount"],
            first_seen=datetime.fromisoformat(
                mock_sentry_issue_data["firstSeen"].replace("Z", "+00:00")
            ),
            last_seen=datetime.fromisoformat(
                mock_sentry_issue_data["lastSeen"].replace("Z", "+00:00")
            ),
            project=mock_sentry_issue_data["project"],
            metadata=mock_sentry_issue_data["metadata"],
            tags=mock_sentry_issue_data["tags"],
        )

        summary = integration.format_issue_summary(issue)

        assert "🔴" in summary  # Error level emoji
        assert "TEST-1" in summary
        assert "DatabaseConnectionError" in summary
        assert "150 events" in summary
        assert "25 users" in summary
        assert "sentry.io" in summary

    def test_format_time_ago(self, mock_sentry_config):
        """Test time formatting"""
        integration = SentryIntegration(mock_sentry_config)

        # Test different time deltas
        now = datetime.now(UTC)

        # Test days ago
        days_ago = now.replace(day=now.day - 2)
        result = integration._format_time_ago(days_ago)
        assert "d ago" in result

        # Test hours ago
        hours_ago = now.replace(hour=now.hour - 2)
        result = integration._format_time_ago(hours_ago)
        assert "h ago" in result or "just now" in result

        # Test minutes ago
        minutes_ago = now.replace(minute=max(0, now.minute - 30))
        result = integration._format_time_ago(minutes_ago)
        assert "m ago" in result or "just now" in result
