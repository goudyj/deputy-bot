"""
Tests for bot advanced commands (yes/no, pending issues)
"""

from unittest.mock import AsyncMock

import pytest

from deputy.bot import DeputyBot
from deputy.models.issue import IssuePriority, IssueType, ThreadAnalysis


class TestBotAdvancedCommands:
    def setup_method(self):
        """Setup for each test"""
        self.mock_analysis = ThreadAnalysis(
            summary="Test API error",
            issue_type=IssueType.BUG,
            priority=IssuePriority.HIGH,
            suggested_title="API Connection Failed",
            detailed_description="Connection to API failed with timeout",
            steps_to_reproduce=["1. Connect to API", "2. Observe timeout"],
            expected_behavior="Connection should succeed",
            actual_behavior="Connection times out",
            additional_context="Started after deployment",
            suggested_labels=["bug", "api"],
            confidence_score=0.95,
        )

    @pytest.mark.asyncio
    async def test_handle_yes_command_success(self, mock_config):
        """Test successful yes command with pending issue"""
        bot = DeputyBot(mock_config)

        # Mock services
        bot.github_integration = AsyncMock()
        bot.github_integration.create_issue_from_analysis.return_value = (
            "https://github.com/org/repo/issues/123"
        )
        bot.sentry_integration = AsyncMock()

        # Add pending issue
        thread_id = "thread_123"
        bot.pending_issues[thread_id] = {
            "analysis": self.mock_analysis,
            "mattermost_link": "http://mattermost.link",
            "thread_messages": [],
            "channel_id": "channel_123",
        }

        post_data = {"id": thread_id, "root_id": None}

        result = await bot._handle_yes_command(post_data)

        # Should create issue and clean up pending data
        assert "✅ **GitHub issue created successfully!**" in result
        assert "API Connection Failed" in result
        assert thread_id not in bot.pending_issues
        bot.github_integration.create_issue_from_analysis.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_yes_command_no_pending_issue(self, mock_config):
        """Test yes command when no pending issue exists"""
        bot = DeputyBot(mock_config)

        post_data = {"id": "thread_123", "root_id": None}

        result = await bot._handle_yes_command(post_data)

        assert "❌ No pending issue found for this thread" in result
        assert "Use `create-issue` first" in result

    @pytest.mark.asyncio
    async def test_handle_yes_command_no_post_data(self, mock_config):
        """Test yes command with no post data"""
        bot = DeputyBot(mock_config)

        result = await bot._handle_yes_command(None)

        assert "❌ No post data available" in result

    @pytest.mark.asyncio
    async def test_handle_yes_command_no_thread_id(self, mock_config):
        """Test yes command when thread ID cannot be determined"""
        bot = DeputyBot(mock_config)

        post_data = {"id": None, "root_id": None}  # None values

        result = await bot._handle_yes_command(post_data)

        assert "❌ Could not identify thread" in result

    @pytest.mark.asyncio
    async def test_handle_yes_command_creation_fails(self, mock_config):
        """Test yes command when issue creation fails"""
        bot = DeputyBot(mock_config)

        # Mock services
        bot.github_integration = AsyncMock()
        bot.github_integration.create_issue_from_analysis.side_effect = Exception(
            "Creation failed"
        )
        bot.sentry_integration = AsyncMock()

        # Add pending issue
        thread_id = "thread_123"
        bot.pending_issues[thread_id] = {
            "analysis": self.mock_analysis,
            "mattermost_link": "http://mattermost.link",
            "thread_messages": [],
            "channel_id": "channel_123",
        }

        post_data = {"id": thread_id, "root_id": None}

        result = await bot._handle_yes_command(post_data)

        # Should clean up pending data on error
        assert "❌ Failed to create issue: Creation failed" in result
        assert thread_id not in bot.pending_issues

    @pytest.mark.asyncio
    async def test_handle_no_command_success(self, mock_config):
        """Test successful no command with pending issue"""
        bot = DeputyBot(mock_config)

        # Add pending issue
        thread_id = "thread_123"
        bot.pending_issues[thread_id] = {
            "analysis": self.mock_analysis,
            "mattermost_link": "http://mattermost.link",
            "thread_messages": [],
            "channel_id": "channel_123",
        }

        post_data = {"id": thread_id, "root_id": None}

        result = await bot._handle_no_command(post_data)

        # Should cancel and clean up pending data
        assert "✅ Issue creation cancelled" in result
        assert "No GitHub issue will be created" in result
        assert thread_id not in bot.pending_issues

    @pytest.mark.asyncio
    async def test_handle_no_command_no_pending_issue(self, mock_config):
        """Test no command when no pending issue exists"""
        bot = DeputyBot(mock_config)

        post_data = {"id": "thread_123", "root_id": None}

        result = await bot._handle_no_command(post_data)

        assert "❌ No pending issue found for this thread" in result

    @pytest.mark.asyncio
    async def test_handle_no_command_no_post_data(self, mock_config):
        """Test no command with no post data"""
        bot = DeputyBot(mock_config)

        result = await bot._handle_no_command(None)

        assert "❌ No post data available" in result

    @pytest.mark.asyncio
    async def test_process_yes_command(self, mock_config):
        """Test processing yes command through main command handler"""
        bot = DeputyBot(mock_config)

        # Add pending issue
        thread_id = "thread_123"
        bot.pending_issues[thread_id] = {
            "analysis": self.mock_analysis,
            "mattermost_link": "http://mattermost.link",
            "thread_messages": [],
            "channel_id": "channel_123",
        }

        # Mock services
        bot.github_integration = AsyncMock()
        bot.github_integration.create_issue_from_analysis.return_value = (
            "https://github.com/org/repo/issues/123"
        )
        bot.sentry_integration = AsyncMock()

        post_data = {"id": thread_id, "root_id": None}

        result = await bot._process_command("yes", "dev-team", post_data)

        assert "✅ **GitHub issue created successfully!**" in result

    @pytest.mark.asyncio
    async def test_process_no_command(self, mock_config):
        """Test processing no command through main command handler"""
        bot = DeputyBot(mock_config)

        # Add pending issue
        thread_id = "thread_123"
        bot.pending_issues[thread_id] = {
            "analysis": self.mock_analysis,
            "mattermost_link": "http://mattermost.link",
            "thread_messages": [],
            "channel_id": "channel_123",
        }

        post_data = {"id": thread_id, "root_id": None}

        result = await bot._process_command("no", "dev-team", post_data)

        assert "✅ Issue creation cancelled" in result

    @pytest.mark.asyncio
    async def test_create_issue_stores_pending_when_similar_found(
        self, mock_config, mock_thread_messages
    ):
        """Test that create-issue stores pending data when similar issues found"""
        bot = DeputyBot(mock_config)

        # Mock services
        bot.thread_analyzer = AsyncMock()
        bot.thread_analyzer.analyze_thread.return_value = self.mock_analysis

        bot.github_integration = AsyncMock()
        bot.github_integration.create_issue_from_analysis.return_value = {
            "type": "similar_issues_found",
            "similar_issues": [{"number": 123, "title": "Similar"}],
            "warning_message": "⚠️ Similar issues found",
            "analysis": self.mock_analysis,
            "mattermost_link": "http://mattermost.link",
            "thread_messages": mock_thread_messages,
        }

        bot.thread_service = AsyncMock()
        bot.thread_service.get_thread_messages.return_value = mock_thread_messages
        bot.thread_service.get_channel_permalink.return_value = "http://mattermost.link"

        bot.sentry_integration = AsyncMock()

        post_data = {
            "id": "post_123",
            "root_id": "thread_123",
            "channel_id": "channel_123",
        }

        result = await bot._handle_create_issue_command(
            "create-issue", "dev-team", post_data
        )

        # Should store pending issue and return warning
        assert "⚠️ Similar issues found" in result
        assert "thread_123" in bot.pending_issues

        pending = bot.pending_issues["thread_123"]
        assert pending["analysis"] == self.mock_analysis
        assert pending["channel_id"] == "channel_123"

    @pytest.mark.asyncio
    async def test_force_create_issue_skips_pending_storage(
        self, mock_config, mock_thread_messages
    ):
        """Test that force-create-issue skips pending storage"""
        bot = DeputyBot(mock_config)

        # Mock services
        bot.thread_analyzer = AsyncMock()
        bot.thread_analyzer.analyze_thread.return_value = self.mock_analysis

        bot.github_integration = AsyncMock()
        bot.github_integration.create_issue_from_analysis.return_value = (
            "https://github.com/org/repo/issues/123"
        )

        bot.thread_service = AsyncMock()
        bot.thread_service.get_thread_messages.return_value = mock_thread_messages
        bot.thread_service.get_channel_permalink.return_value = "http://mattermost.link"

        bot.sentry_integration = AsyncMock()

        post_data = {
            "id": "post_123",
            "root_id": "thread_123",
            "channel_id": "channel_123",
        }

        result = await bot._handle_create_issue_command(
            "force-create-issue", "dev-team", post_data, force=True
        )

        # Should create issue directly without storing pending data
        assert "✅ **GitHub issue created successfully!**" in result
        assert len(bot.pending_issues) == 0

        # Should call with force_create=True
        bot.github_integration.create_issue_from_analysis.assert_called_once()
        call_args = bot.github_integration.create_issue_from_analysis.call_args
        assert call_args.kwargs["force_create"] is True

    def test_pending_issues_initialization(self, mock_config):
        """Test that pending_issues dict is properly initialized"""
        bot = DeputyBot(mock_config)

        assert hasattr(bot, "pending_issues")
        assert isinstance(bot.pending_issues, dict)
        assert len(bot.pending_issues) == 0

    def test_help_message_includes_yes_no_commands(self, mock_config):
        """Test that help message mentions yes/no commands in create-issue description"""
        bot = DeputyBot(mock_config)

        help_message = bot._get_help_message()

        assert "respond with `yes` or `no` when prompted" in help_message
        assert "`create-issue`" in help_message
