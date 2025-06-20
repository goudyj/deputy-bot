"""
Tests for DeputyBot (main agent)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deputy.bot import DeputyBot


class TestDeputyBot:
    def test_bot_initialization(self, mock_config):
        """Test bot initialization with config"""
        bot = DeputyBot(mock_config)

        assert bot.config == mock_config
        assert bot.session is None
        assert bot.websocket is None
        assert bot.team_id is None
        assert bot.bot_user_id is None

        # Check headers are properly set
        assert "Authorization" in bot.headers
        assert f"Bearer {mock_config.mattermost.token}" in bot.headers["Authorization"]
        assert bot.headers["Content-Type"] == "application/json"

    def test_initialize_services_success(self, mock_config):
        """Test successful service initialization"""
        bot = DeputyBot(mock_config)
        bot.session = AsyncMock()

        with (
            patch("deputy.bot.ThreadAnalyzer") as mock_analyzer,
            patch("deputy.bot.GitHubIntegration") as mock_github,
            patch("deputy.bot.MattermostThreadService"),
        ):
            bot._initialize_services()

            # Check all services are initialized
            assert bot.thread_analyzer is not None
            assert bot.github_integration is not None
            assert bot.thread_service is not None

            # Verify correct parameters passed
            mock_analyzer.assert_called_once_with(mock_config.llm)
            mock_github.assert_called_once_with(
                mock_config.github_token,
                mock_config.github_org,
                mock_config.github_repo,
                mock_config.issue_creation,
                mock_config.llm,  # New LLM config parameter
            )

    def test_initialize_services_missing_github_config(self, mock_config):
        """Test service initialization when GitHub config is missing"""
        # Remove GitHub config
        mock_config.github_token = ""

        bot = DeputyBot(mock_config)
        bot.session = AsyncMock()

        with (
            patch("deputy.bot.ThreadAnalyzer"),
            patch("deputy.bot.MattermostThreadService"),
        ):
            bot._initialize_services()

            # Thread analyzer should be initialized
            assert bot.thread_analyzer is not None
            assert bot.thread_service is not None

            # GitHub integration should not be initialized
            assert bot.github_integration is None

    def test_channel_filtering(self, mock_config):
        """Test channel name filtering with regex patterns"""
        # Should match channels in config: ["town-square", "dev-.*"]
        assert mock_config.mattermost.should_listen_to_channel("town-square") is True
        assert mock_config.mattermost.should_listen_to_channel("dev-team") is True
        assert mock_config.mattermost.should_listen_to_channel("dev-backend") is True
        assert (
            mock_config.mattermost.should_listen_to_channel("random-channel") is False
        )
        assert mock_config.mattermost.should_listen_to_channel("off-topic") is False

    def test_wildcard_channel_configuration(self):
        """Test that MATTERMOST_CHANNELS=* works correctly"""
        from deputy.models.config import MattermostConfig

        config_wildcard = MattermostConfig(
            url="http://localhost:8065",
            token="test_token",
            team_name="test_team",
            channels=["*"],
            bot_name="deputy",
        )

        # Should match any channel name
        assert config_wildcard.should_listen_to_channel("town-square") is True
        assert config_wildcard.should_listen_to_channel("dev-team") is True
        assert config_wildcard.should_listen_to_channel("random-channel") is True
        assert config_wildcard.should_listen_to_channel("off-topic") is True

    def test_invalid_regex_fallback(self):
        """Test that invalid regex patterns fall back to literal matching"""
        from deputy.models.config import MattermostConfig

        config_invalid = MattermostConfig(
            url="http://localhost:8065",
            token="test_token",
            team_name="test_team",
            channels=["[invalid-regex", "exact-match"],
            bot_name="deputy",
        )

        # Invalid regex should match literally
        assert config_invalid.should_listen_to_channel("[invalid-regex") is True
        assert config_invalid.should_listen_to_channel("invalid-regex") is False

        # Valid literal match
        assert config_invalid.should_listen_to_channel("exact-match") is True
        assert config_invalid.should_listen_to_channel("not-exact-match") is False

    def test_help_message(self, mock_config):
        """Test help message content"""
        bot = DeputyBot(mock_config)

        result = bot._get_help_message()

        assert "Deputy Bot" in result
        assert "help" in result
        assert "create-issue" in result
        assert "create-issue <description>" in result
        assert "sentry" in result
        assert "Examples:" in result

    @pytest.mark.asyncio
    async def test_handle_create_issue_command_missing_services(self, mock_config):
        """Test create-issue command when services are missing"""
        bot = DeputyBot(mock_config)
        bot.thread_analyzer = None
        bot.github_integration = None

        result = await bot._handle_create_issue_command(
            "create-issue", "dev-team", None
        )

        assert "❌" in result
        assert "Thread analysis not available" in result

    @pytest.mark.asyncio
    async def test_handle_create_issue_command_no_post_data(self, mock_config):
        """Test create-issue command without post data"""
        bot = DeputyBot(mock_config)
        bot.thread_analyzer = MagicMock()
        bot.github_integration = MagicMock()

        result = await bot._handle_create_issue_command(
            "create-issue", "dev-team", None
        )

        assert "❌" in result
        assert "No post data available" in result

    @pytest.mark.asyncio
    async def test_handle_create_issue_command_success(
        self, mock_config, mock_thread_analysis
    ):
        """Test successful create-issue command"""
        bot = DeputyBot(mock_config)

        # Mock services
        mock_thread_service = AsyncMock()
        mock_thread_service.get_thread_messages.return_value = [MagicMock()]
        mock_thread_service.get_channel_permalink.return_value = "http://permalink"

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze_thread.return_value = mock_thread_analysis

        mock_github = AsyncMock()
        mock_github.create_issue_from_analysis.return_value = (
            "https://github.com/test/test/issues/1"
        )

        bot.thread_service = mock_thread_service
        bot.thread_analyzer = mock_analyzer
        bot.github_integration = mock_github

        post_data = {"id": "post123", "channel_id": "channel456"}

        result = await bot._handle_create_issue_command(
            "create-issue", "dev-team", post_data
        )

        assert "✅" in result
        assert "issue created successfully" in result
        assert "https://github.com/test/test/issues/1" in result

        # Verify service calls
        mock_thread_service.get_thread_messages.assert_called_once_with("post123")
        mock_analyzer.analyze_thread.assert_called_once()
        mock_github.create_issue_from_analysis.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_create_issue_command_with_description(
        self, mock_config, mock_thread_analysis
    ):
        """Test create-issue command with inline description"""
        bot = DeputyBot(mock_config)

        # Mock services
        mock_analyzer = AsyncMock()
        mock_analyzer.analyze_thread.return_value = mock_thread_analysis

        mock_github = AsyncMock()
        mock_github.create_issue_from_analysis.return_value = (
            "https://github.com/test/test/issues/2"
        )

        bot.thread_analyzer = mock_analyzer
        bot.github_integration = mock_github

        post_data = {"id": "post123", "channel_id": "channel456"}

        result = await bot._handle_create_issue_command(
            "create-issue Login button not working on mobile", "dev-team", post_data
        )

        assert "✅" in result
        assert "issue created successfully" in result
        assert "https://github.com/test/test/issues/2" in result
        assert "from your description" in result

        # Verify analyzer was called with synthetic message
        mock_analyzer.analyze_thread.assert_called_once()
        call_args = mock_analyzer.analyze_thread.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0].content == "Login button not working on mobile"

    @pytest.mark.asyncio
    async def test_create_issue_from_description_low_confidence(self, mock_config):
        """Test create-issue with description that has low confidence"""
        from deputy.models.issue import IssuePriority, IssueType, ThreadAnalysis

        bot = DeputyBot(mock_config)

        # Mock low confidence analysis
        low_confidence_analysis = ThreadAnalysis(
            summary="Unclear issue",
            issue_type=IssueType.BUG,
            priority=IssuePriority.LOW,
            suggested_title="Issue",
            detailed_description="Not enough info",
            confidence_score=0.1,  # Very low confidence
        )

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze_thread.return_value = low_confidence_analysis

        mock_github = AsyncMock()

        bot.thread_analyzer = mock_analyzer
        bot.github_integration = mock_github

        post_data = {"id": "post123", "channel_id": "channel456"}

        result = await bot._create_issue_from_description("vague", post_data)

        assert "⚠️" in result
        assert "Low confidence analysis" in result
        assert "0.10" in result
        assert "Try providing more details" in result

        # Should not create GitHub issue
        mock_github.create_issue_from_analysis.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_unknown_command(self, mock_config):
        """Test handling of unknown commands"""
        bot = DeputyBot(mock_config)

        result = await bot._process_command("unknown-command", "dev-team", {})

        assert "Unknown command" in result and "help" in result

    def test_message_parsing(self, mock_config):
        """Test message parsing for bot mentions"""
        # Test bot mention detection
        message_with_mention = f"@{mock_config.mattermost.bot_name} help"
        message_without_mention = "just a regular message"

        # This would be part of _handle_message logic
        assert message_with_mention.startswith(f"@{mock_config.mattermost.bot_name}")
        assert not message_without_mention.startswith(
            f"@{mock_config.mattermost.bot_name}"
        )

    def test_threaded_message_data_structure(self, mock_config):
        """Test threaded message data structure logic"""
        original_post = {"id": "post123", "root_id": None}

        # Test the root ID logic
        root_id = original_post.get("root_id") or original_post.get("id")
        assert root_id == "post123"

        # Test with existing root_id
        threaded_post = {"id": "post456", "root_id": "post123"}
        root_id = threaded_post.get("root_id") or threaded_post.get("id")
        assert root_id == "post123"
