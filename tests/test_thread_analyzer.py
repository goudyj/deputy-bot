"""
Tests for ThreadAnalyzer
"""

from unittest.mock import MagicMock, patch

import pytest

from deputy.models.issue import IssuePriority, IssueType
from deputy.services.thread_analyzer import ThreadAnalyzer


class TestThreadAnalyzer:
    def test_create_llm_openai(self, mock_config):
        """Test OpenAI LLM creation"""

        with patch("deputy.services.thread_analyzer.ChatOpenAI") as mock_openai:
            ThreadAnalyzer(mock_config.llm)

            mock_openai.assert_called_once_with(
                model="gpt-4o-mini",
                api_key="test_openai_key",
                temperature=0.1,
                max_tokens=2000,
            )

    def test_create_llm_anthropic(self, mock_config):
        """Test Anthropic LLM creation"""

        mock_config.llm.provider = "anthropic"
        mock_config.llm.anthropic_api_key = "test_anthropic_key"

        with patch("deputy.services.thread_analyzer.ChatAnthropic") as mock_anthropic:
            ThreadAnalyzer(mock_config.llm)

            mock_anthropic.assert_called_once_with(
                model="gpt-4o-mini",
                api_key="test_anthropic_key",
                temperature=0.1,
                max_tokens=2000,
            )

    def test_create_llm_unsupported_provider(self, mock_config):
        """Test unsupported LLM provider"""

        mock_config.llm.provider = "unsupported"

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            ThreadAnalyzer(mock_config.llm)

    def test_format_thread_for_analysis(self, mock_config, mock_thread_messages):
        """Test thread formatting for LLM analysis"""

        with patch("deputy.services.thread_analyzer.ChatOpenAI"):
            analyzer = ThreadAnalyzer(mock_config.llm)
            formatted = analyzer._format_thread_for_analysis(mock_thread_messages)

            assert "**alice** (2024-06-18T10:00:00Z):" in formatted
            assert "403 Forbidden error" in formatted
            assert "**bob**" in formatted
            assert (
                len(formatted.split("\n\n")) >= 3
            )  # Should have empty lines between messages

    @pytest.mark.asyncio
    async def test_analyze_thread_error_fallback(
        self, mock_config, mock_thread_messages
    ):
        """Test that thread analysis returns fallback on error"""

        with patch("deputy.services.thread_analyzer.ChatOpenAI") as mock_openai:
            # Mock the graph to raise an exception
            mock_llm = MagicMock()
            mock_openai.return_value = mock_llm

            analyzer = ThreadAnalyzer(mock_config.llm)

            # Mock graph to raise exception
            analyzer.graph.ainvoke = lambda x: None
            analyzer.graph.ainvoke.side_effect = Exception("Graph error")

            result = await analyzer.analyze_thread(mock_thread_messages)

            # Should return fallback analysis
            assert result.issue_type == IssueType.QUESTION
            assert result.priority == IssuePriority.LOW
            assert result.confidence_score == 0.0
            assert "Issue analysis failed" in result.suggested_title
