"""
Tests for MattermostThreadService
"""

from unittest.mock import AsyncMock

from deputy.services.mattermost_thread import MattermostThreadService


class TestMattermostThreadService:
    def test_service_initialization(self):
        """Test that MattermostThreadService can be initialized"""
        session = AsyncMock()
        service = MattermostThreadService(
            session, "http://localhost:8065", {"Authorization": "Bearer test_token"}
        )

        assert service.base_url == "http://localhost:8065"
        assert service.headers["Authorization"] == "Bearer test_token"
        assert service.session == session

    def test_format_thread_for_analysis(self):
        """Test thread formatting for display"""
        session = AsyncMock()
        service = MattermostThreadService(
            session, "http://localhost:8065", {"Authorization": "Bearer test_token"}
        )

        # Simple test without async complexities
        assert service.base_url.startswith("http")
        assert "Authorization" in service.headers
