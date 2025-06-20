"""
Pytest configuration and fixtures
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from deputy.models.config import (
    AppConfig,
    IssueCreationConfig,
    LLMConfig,
    MattermostConfig,
)
from deputy.models.issue import (
    AttachmentInfo,
    IssuePriority,
    IssueType,
    ThreadAnalysis,
    ThreadMessage,
)


@pytest.fixture
def mock_config():
    """Mock AppConfig for testing"""
    return AppConfig(
        mattermost=MattermostConfig(
            url="http://localhost:8065",
            token="test_token",
            team_name="test_team",
            channels=["town-square", "dev-.*"],
            bot_name="deputy",
        ),
        llm=LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            openai_api_key="test_openai_key",
            temperature=0.1,
            max_tokens=2000,
        ),
        issue_creation=IssueCreationConfig(
            auto_labels=["auto-generated"], default_assignee="test_user"
        ),
        github_token="test_github_token",
        github_org="test_org",
        github_repo="test_repo",
    )


@pytest.fixture
def mock_thread_messages():
    """Sample thread messages for testing"""
    return [
        ThreadMessage(
            user="alice",
            content="I'm getting a 403 Forbidden error when trying to connect to the API.",
            timestamp="2024-06-18T10:00:00Z",
            attachments=[],
        ),
        ThreadMessage(
            user="bob",
            content="Can you check the logs? I see authentication errors.",
            timestamp="2024-06-18T10:05:00Z",
            attachments=[],
        ),
        ThreadMessage(
            user="alice",
            content="Here's the full error: POST /api/v1/connect returned 403.",
            timestamp="2024-06-18T10:10:00Z",
            attachments=[],
        ),
    ]


@pytest.fixture
def mock_thread_messages_with_images():
    """Sample thread messages with images for testing"""
    return [
        ThreadMessage(
            user="alice",
            content="I'm getting this error screen:",
            timestamp="2024-06-18T10:00:00Z",
            attachments=[
                AttachmentInfo(
                    url="http://mattermost.example.com/api/v4/files/error_screenshot",
                    filename="error_screenshot.png",
                    mime_type="image/png",
                    size=1024*512,  # 512KB
                    is_image=True
                ),
                AttachmentInfo(
                    url="http://mattermost.example.com/api/v4/files/debug_log",
                    filename="debug.log",
                    mime_type="text/plain",
                    size=1024*50,  # 50KB
                    is_image=False
                )
            ],
        ),
        ThreadMessage(
            user="bob",
            content="Thanks for the screenshot! I can see the issue now.",
            timestamp="2024-06-18T10:05:00Z",
            attachments=[],
        ),
    ]


@pytest.fixture
def mock_thread_analysis():
    """Sample thread analysis for testing"""
    return ThreadAnalysis(
        summary="API authentication error after deployment",
        issue_type=IssueType.BUG,
        priority=IssuePriority.HIGH,
        suggested_title="403 Forbidden Error on API Connection",
        detailed_description="Users are experiencing 403 Forbidden errors when connecting to the API after the latest deployment.",
        steps_to_reproduce=["1. Try to connect to API", "2. Observe 403 error"],
        expected_behavior="API connection should succeed",
        actual_behavior="403 Forbidden error returned",
        additional_context="Started after latest deployment",
        suggested_labels=["bug", "api", "authentication"],
        confidence_score=0.95,
    )


@pytest.fixture
def mock_aiohttp_session():
    """Mock aiohttp ClientSession"""
    session = AsyncMock()
    return session


@pytest.fixture
def mock_github_repo():
    """Mock GitHub Repository"""
    repo = MagicMock()
    repo.full_name = "test_org/test_repo"
    repo.name = "test_repo"
    repo.description = "Test repository"
    repo.private = False
    repo.has_issues = True
    repo.open_issues_count = 5

    # Mock create_issue
    mock_issue = MagicMock()
    mock_issue.number = 123
    mock_issue.html_url = "https://github.com/test_org/test_repo/issues/123"
    mock_issue.title = "Test Issue"
    repo.create_issue.return_value = mock_issue

    # Mock get_labels
    mock_label = MagicMock()
    mock_label.name = "bug"
    repo.get_labels.return_value = [mock_label]

    return repo
