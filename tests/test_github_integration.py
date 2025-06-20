"""
Tests for GitHubIntegration
"""

from unittest.mock import MagicMock, patch

import pytest

from deputy.services.github_integration import GitHubIntegration


class TestGitHubIntegration:
    def test_init(self, mock_config):
        """Test GitHubIntegration initialization"""

        with patch("deputy.services.github_integration.Github") as mock_github:
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            mock_github.assert_called_once_with("test_token")
            assert integration.org == "test_org"
            assert integration.repo_name == "test_repo"

    def test_validate_labels_success(self, mock_config, mock_github_repo):
        """Test successful label validation"""

        with patch("deputy.services.github_integration.Github") as mock_github:
            mock_github.return_value.get_repo.return_value = mock_github_repo

            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            # Test with both valid and invalid labels
            test_labels = ["bug", "invalid-label", "nonexistent"]
            result = integration.validate_labels(test_labels)

            # Only "bug" should be valid (from our mock)
            assert result == ["bug"]

    def test_validate_labels_error(self, mock_config):
        """Test label validation when GitHub API fails"""

        with patch("deputy.services.github_integration.Github") as mock_github:
            mock_repo = MagicMock()
            mock_repo.get_labels.side_effect = Exception("API Error")
            mock_github.return_value.get_repo.return_value = mock_repo

            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            result = integration.validate_labels(["bug", "feature"])

            # Should return empty list on error
            assert result == []

    @pytest.mark.asyncio
    async def test_get_repository_info(self, mock_config, mock_github_repo):
        """Test repository info retrieval"""

        with patch("deputy.services.github_integration.Github") as mock_github:
            mock_github.return_value.get_repo.return_value = mock_github_repo

            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            result = await integration.get_repository_info()

            assert result["name"] == "test_repo"
            assert result["full_name"] == "test_org/test_repo"
            assert result["has_issues"] is True
            assert result["open_issues"] == 5

    def test_analysis_to_github_issue(self, mock_config, mock_thread_analysis):
        """Test conversion of analysis to GitHub issue format"""

        with patch("deputy.services.github_integration.Github"):
            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            result = integration._analysis_to_github_issue(
                mock_thread_analysis, "http://mattermost.link"
            )

            assert result.title == "403 Forbidden Error on API Connection"
            assert "## Description" in result.body
            assert "## Steps to Reproduce" in result.body
            assert "## Expected vs Actual Behavior" in result.body
            assert "mattermost.link" in result.body
            assert "Deputy Bot" in result.body

            # Check labels include both suggested and auto labels
            assert "bug" in result.labels
            assert "auto-generated" in result.labels

            # Check assignee
            assert "test_user" in result.assignees

    @pytest.mark.asyncio
    async def test_create_issue_repository_access_error(
        self, mock_config, mock_thread_analysis
    ):
        """Test issue creation when repository access fails"""

        with patch("deputy.services.github_integration.Github") as mock_github:
            mock_github.return_value.get_repo.side_effect = Exception(
                "Repository not found"
            )

            integration = GitHubIntegration(
                "test_token", "test_org", "test_repo", mock_config.issue_creation
            )

            with pytest.raises(Exception, match="Repository access failed"):
                await integration.create_issue_from_analysis(mock_thread_analysis)
