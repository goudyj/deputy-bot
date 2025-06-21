"""
Tests for GitHub advanced features (similar issues search, Sentry integration)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deputy.models.issue import IssuePriority, IssueType, ThreadAnalysis
from deputy.models.sentry import SentryIssue
from deputy.services.github_integration import GitHubIntegration


class TestGitHubAdvancedFeatures:
    def test_extract_keywords(self, mock_config, mock_thread_analysis):
        """Test keyword extraction from thread analysis"""
        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            keywords = integration._extract_keywords(mock_thread_analysis)

            # Should extract meaningful keywords, not common words
            assert len(keywords) > 0
            assert "forbidden" in keywords  # From title "403 Forbidden Error"
            assert "connection" in keywords  # From title "API Connection"
            # Should not include common words
            assert "error" not in keywords
            assert "issue" not in keywords

    def test_extract_keywords_with_technical_terms(self, mock_config):
        """Test keyword extraction with technical terms"""
        analysis = ThreadAnalysis(
            summary="API authentication error",
            issue_type=IssueType.BUG,
            priority=IssuePriority.HIGH,
            suggested_title="ConnectionTimeout in UserService",
            detailed_description='Error in "user_authentication" method: ConnectionTimeout occurred in UserService.authenticate()',
            steps_to_reproduce=[],
            expected_behavior="",
            actual_behavior="",
            additional_context="",
            suggested_labels=["timeout", "authentication"],
            confidence_score=0.95,
        )

        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            keywords = integration._extract_keywords(analysis)

            # Should extract technical terms
            assert "ConnectionTimeout" in keywords  # CamelCase
            assert "UserService" in keywords  # CamelCase
            assert "user_authentication" in keywords  # snake_case
            # Note: timeout/authentication from labels are filtered by label whitelist
            assert len(keywords) >= 3

    @pytest.mark.asyncio
    async def test_search_similar_issues_success(
        self, mock_config, mock_thread_analysis
    ):
        """Test successful similar issues search"""
        mock_search_result = [
            MagicMock(
                number=123,
                title="API Connection Timeout",
                html_url="https://github.com/test_org/test_repo/issues/123",
                state="open",
                updated_at=datetime.now(UTC),
                labels=[MagicMock(name="bug"), MagicMock(name="api")],
            ),
            MagicMock(
                number=124,
                title="Database Connection Error",
                html_url="https://github.com/test_org/test_repo/issues/124",
                state="closed",
                updated_at=datetime.now(UTC),
                labels=[MagicMock(name="bug")],
            ),
        ]

        with patch("deputy.services.github_integration.Github") as mock_github:
            mock_github.return_value.search_issues.return_value = mock_search_result

            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            similar_issues = await integration.search_similar_issues_basic(
                mock_thread_analysis
            )

            assert len(similar_issues) == 2
            assert similar_issues[0]["number"] == 123
            assert similar_issues[0]["title"] == "API Connection Timeout"
            assert similar_issues[0]["state"] == "open"
            assert similar_issues[1]["number"] == 124
            assert similar_issues[1]["state"] == "closed"

    @pytest.mark.asyncio
    async def test_search_similar_issues_no_keywords(self, mock_config):
        """Test similar issues search with no extractable keywords"""
        analysis = ThreadAnalysis(
            summary="Issue",
            issue_type=IssueType.BUG,
            priority=IssuePriority.LOW,
            suggested_title="Error",  # Only common words
            detailed_description="Problem occurred",  # Only common words
            steps_to_reproduce=[],
            expected_behavior="",
            actual_behavior="",
            additional_context="",
            suggested_labels=[],  # No relevant labels
            confidence_score=0.5,
        )

        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            similar_issues = await integration.search_similar_issues_basic(analysis)

            assert similar_issues == []  # Should return empty list

    @pytest.mark.asyncio
    async def test_search_similar_issues_api_error(
        self, mock_config, mock_thread_analysis
    ):
        """Test similar issues search when GitHub API fails"""
        with patch("deputy.services.github_integration.Github") as mock_github:
            mock_github.return_value.search_issues.side_effect = Exception("API Error")

            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            similar_issues = await integration.search_similar_issues_basic(
                mock_thread_analysis
            )

            assert similar_issues == []  # Should return empty list on error

    def test_format_similar_issues_warning(self, mock_config):
        """Test formatting of similar issues warning message"""
        similar_issues = [
            {
                "number": 123,
                "title": "API Connection Timeout",
                "url": "https://github.com/test_org/test_repo/issues/123",
                "state": "open",
                "updated_at": "2024-06-20T10:00:00Z",
                "labels": ["bug", "api"],
            },
            {
                "number": 124,
                "title": "Database Error",
                "url": "https://github.com/test_org/test_repo/issues/124",
                "state": "closed",
                "updated_at": "2024-06-19T15:30:00Z",
                "labels": [],
            },
        ]

        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            warning = integration.format_similar_issues_warning(similar_issues)

            assert "⚠️ **Similar Issues Found:**" in warning
            assert "🟢 **#123**: API Connection Timeout" in warning  # Open issue
            assert "🔴 **#124**: Database Error" in warning  # Closed issue
            assert "🏷️ Labels: bug, api" in warning
            assert "@deputy yes" in warning
            assert "@deputy no" in warning

    @pytest.mark.asyncio
    async def test_search_related_sentry_errors_success(
        self, mock_config, mock_thread_analysis
    ):
        """Test successful Sentry errors search"""
        mock_sentry_integration = AsyncMock()
        mock_sentry_integration.config.is_configured.return_value = True

        # Mock Sentry issue
        mock_sentry_issue = SentryIssue(
            id="12345",
            title="ConnectionTimeout in API",
            culprit="api/connection.py",
            permalink="https://sentry.io/issues/12345/",
            short_id="TEST-123",
            status="unresolved",
            level="error",
            type="error",
            count=150,
            user_count=25,
            first_seen=datetime.now(UTC),
            last_seen=datetime.now(UTC),
            project={"id": "1", "name": "test"},
            metadata={},
            tags=[],
        )

        mock_sentry_integration.search_issues.return_value = [mock_sentry_issue]

        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            sentry_errors = await integration.search_related_sentry_errors(
                mock_thread_analysis, mock_sentry_integration
            )

            assert len(sentry_errors) >= 1
            error = sentry_errors[0]
            assert error["id"] == "12345"
            assert error["title"] == "ConnectionTimeout in API"
            assert error["short_id"] == "TEST-123"
            assert error["level"] == "error"
            assert error["count"] == 150

    @pytest.mark.asyncio
    async def test_search_related_sentry_errors_not_configured(
        self, mock_config, mock_thread_analysis
    ):
        """Test Sentry errors search when Sentry is not configured"""
        mock_sentry_integration = AsyncMock()
        mock_sentry_integration.config.is_configured.return_value = False

        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            sentry_errors = await integration.search_related_sentry_errors(
                mock_thread_analysis, mock_sentry_integration
            )

            assert sentry_errors == []

    @pytest.mark.asyncio
    async def test_search_related_sentry_errors_no_integration(
        self, mock_config, mock_thread_analysis
    ):
        """Test Sentry errors search when no integration provided"""
        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            sentry_errors = await integration.search_related_sentry_errors(
                mock_thread_analysis, None
            )

            assert sentry_errors == []

    def test_format_sentry_errors_section(self, mock_config):
        """Test formatting of Sentry errors section"""
        sentry_errors = [
            {
                "keyword": "connection",
                "id": "12345",
                "short_id": "TEST-123",
                "title": "ConnectionTimeout in API",
                "permalink": "https://sentry.io/issues/12345/",
                "level": "error",
                "count": 150,
                "last_seen": "2024-06-20T10:30:00Z",
            }
        ]

        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            section = integration.format_sentry_errors_section(sentry_errors)

            assert "## 🔴 Related Sentry Errors" in section
            assert "🔴 **TEST-123**: ConnectionTimeout in API" in section
            assert "💥 150 events" in section
            assert "⏰ Last seen: 2024-06-20" in section
            assert "🔗 [View in Sentry](https://sentry.io/issues/12345/)" in section
            assert "🔍 Found via keyword: `connection`" in section

    def test_format_sentry_errors_section_empty(self, mock_config):
        """Test formatting of empty Sentry errors section"""
        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            section = integration.format_sentry_errors_section([])

            assert section == ""

    @pytest.mark.asyncio
    async def test_create_issue_with_similar_issues_found(
        self, mock_config, mock_thread_analysis
    ):
        """Test issue creation when similar issues are found"""
        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            # Mock search to return similar issues
            similar_issues = [
                {
                    "number": 123,
                    "title": "Similar Issue",
                    "state": "open",
                    "url": "http://github.com/issues/123",
                    "labels": [],
                }
            ]
            with patch.object(
                integration, "search_similar_issues_basic", return_value=similar_issues
            ):
                with patch.object(
                    integration, "search_related_sentry_errors", return_value=[]
                ):
                    result = await integration.create_issue_from_analysis(
                        mock_thread_analysis, "http://mattermost.link"
                    )

                    # Should return warning instead of creating issue
                    assert isinstance(result, dict)
                    assert result["type"] == "similar_issues_found"
                    assert len(result["similar_issues"]) == 1
                    assert "warning_message" in result

    @pytest.mark.asyncio
    async def test_create_issue_force_create_skips_checks(
        self, mock_config, mock_thread_analysis, mock_github_repo
    ):
        """Test issue creation with force_create=True skips similarity checks"""
        with patch("deputy.services.github_integration.Github") as mock_github:
            mock_github.return_value.get_repo.return_value = mock_github_repo

            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            # Mock search to return similar issues (should be ignored with force_create=True)
            similar_issues = [{"number": 123, "title": "Similar Issue"}]
            with patch.object(
                integration, "search_similar_issues_basic", return_value=similar_issues
            ) as mock_search:
                with patch.object(
                    integration, "search_related_sentry_errors", return_value=[]
                ):
                    result = await integration.create_issue_from_analysis(
                        mock_thread_analysis,
                        "http://mattermost.link",
                        force_create=True,
                    )

                    # Should not call search_similar_issues_basic when force_create=True
                    mock_search.assert_not_called()
                    # Should return issue URL (string) instead of warning dict
                    assert isinstance(result, str)
                    assert "github.com" in result
