"""
Tests for SmartSimilaritySearcher
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deputy.models.issue import IssuePriority, IssueType, ThreadAnalysis
from deputy.models.llm_config import LLMConfig
from deputy.services.smart_similarity_searcher import (
    KeywordExtraction,
    SimilarityAnalysis,
    SmartSimilaritySearcher,
)


class TestSmartSimilaritySearcher:
    @pytest.fixture
    def mock_llm_config(self):
        """Mock LLM configuration"""
        return LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            openai_api_key="test_key",
            temperature=0.1,
            max_tokens=2000,
        )

    @pytest.fixture
    def mock_github_integration(self):
        """Mock GitHub integration"""
        github_mock = MagicMock()
        github_mock.org = "test_org"
        github_mock.repo_name = "test_repo"

        # Mock repository
        repo_mock = MagicMock()
        github_mock.repo = repo_mock

        # Mock GitHub search
        github_api_mock = MagicMock()
        github_mock.github = github_api_mock

        return github_mock

    @pytest.fixture
    def mock_analysis(self):
        """Mock thread analysis"""
        return ThreadAnalysis(
            summary="Login button not working on mobile",
            issue_type=IssueType.BUG,
            priority=IssuePriority.HIGH,
            suggested_title="Login button not working on mobile Safari",
            detailed_description="Users are unable to click the login button on mobile Safari. The button appears but does not respond to touch events.",
            steps_to_reproduce=[
                "1. Open app on mobile Safari",
                "2. Try to click login button",
            ],
            expected_behavior="Button should respond to touch",
            actual_behavior="Button does not respond",
            additional_context="Issue started after iOS update",
            suggested_labels=["bug", "mobile", "safari"],
            confidence_score=0.9,
        )

    @pytest.fixture
    def smart_searcher(self, mock_llm_config, mock_github_integration):
        """Create SmartSimilaritySearcher instance"""
        with (
            patch.object(SmartSimilaritySearcher, "_initialize_llm"),
            patch.object(SmartSimilaritySearcher, "_create_similarity_graph"),
        ):
            searcher = SmartSimilaritySearcher(mock_llm_config, mock_github_integration)
            # Mock the LLM and graph
            searcher.llm = MagicMock()
            searcher.graph = MagicMock()
            return searcher

    @pytest.mark.asyncio
    async def test_extract_smart_keywords_success(self, smart_searcher, mock_analysis):
        """Test successful keyword extraction"""
        # Mock structured LLM response
        mock_response = KeywordExtraction(
            keywords=["login", "button", "mobile", "safari", "touch"],
            reasoning="Extracted specific technical terms related to login functionality on mobile Safari",
        )

        # Mock the structured LLM properly
        structured_llm_mock = MagicMock()
        structured_llm_mock.ainvoke = AsyncMock(return_value=mock_response)
        smart_searcher.llm.with_structured_output.return_value = structured_llm_mock

        # Test state
        state = {
            "original_analysis": mock_analysis,
            "smart_keywords": [],
            "error_count": 0,
        }

        result = await smart_searcher._extract_smart_keywords(state)

        assert result["smart_keywords"] == [
            "login",
            "button",
            "mobile",
            "safari",
            "touch",
        ]
        assert result["error_count"] == 0
        structured_llm_mock.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_smart_keywords_failure_retry(
        self, smart_searcher, mock_analysis
    ):
        """Test keyword extraction failure triggers retry logic"""
        # Mock LLM failure
        structured_llm_mock = MagicMock()
        structured_llm_mock.ainvoke = AsyncMock(side_effect=Exception("LLM API error"))
        smart_searcher.llm.with_structured_output.return_value = structured_llm_mock

        state = {
            "original_analysis": mock_analysis,
            "smart_keywords": [],
            "error_count": 0,
        }

        result = await smart_searcher._extract_smart_keywords(state)

        assert result["error_count"] == 1
        assert result["smart_keywords"] == []

    @pytest.mark.asyncio
    async def test_search_github_issues_success(self, smart_searcher):
        """Test successful GitHub issue search"""
        # Mock search results
        mock_issue = MagicMock()
        mock_issue.number = 123
        mock_issue.title = "Login button issues on mobile"
        mock_issue.html_url = "https://github.com/test/test/issues/123"
        mock_issue.state = "open"
        mock_issue.created_at = datetime.now(UTC) - timedelta(days=10)
        mock_issue.updated_at = datetime.now(UTC) - timedelta(days=5)
        mock_issue.labels = [MagicMock(name="bug"), MagicMock(name="mobile")]

        smart_searcher.github.github.search_issues.return_value = [mock_issue]

        state = {
            "smart_keywords": ["login", "button", "mobile"],
            "raw_search_results": [],
        }

        result = await smart_searcher._search_github_issues(state)

        assert len(result["raw_search_results"]) == 1
        assert result["raw_search_results"][0]["number"] == 123
        assert (
            result["raw_search_results"][0]["title"] == "Login button issues on mobile"
        )

    @pytest.mark.asyncio
    async def test_fetch_issue_details_success(self, smart_searcher):
        """Test successful issue details fetching"""
        # Mock issue details
        mock_issue = MagicMock()
        mock_issue.body = "Detailed description of the login issue..."
        mock_issue.comments = 5

        smart_searcher.github.repo.get_issue.return_value = mock_issue

        state = {
            "raw_search_results": [
                {
                    "number": 123,
                    "title": "Login button issues",
                    "url": "https://github.com/test/test/issues/123",
                    "state": "open",
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "labels": ["bug"],
                }
            ],
            "detailed_issues": [],
        }

        result = await smart_searcher._fetch_issue_details(state)

        assert len(result["detailed_issues"]) == 1
        assert (
            result["detailed_issues"][0]["body"]
            == "Detailed description of the login issue..."
        )
        assert result["detailed_issues"][0]["comments_count"] == 5

    @pytest.mark.asyncio
    async def test_analyze_similarity_success(self, smart_searcher, mock_analysis):
        """Test successful similarity analysis"""
        # Mock similarity analysis response
        mock_response = SimilarityAnalysis(
            similarity_score=0.85,
            is_duplicate=True,
            reasoning="Both issues describe login button problems on mobile Safari with touch event failures",
        )

        # Mock the structured LLM properly
        structured_llm_mock = MagicMock()
        structured_llm_mock.ainvoke = AsyncMock(return_value=mock_response)
        smart_searcher.llm.with_structured_output.return_value = structured_llm_mock

        state = {
            "original_analysis": mock_analysis,
            "detailed_issues": [
                {
                    "number": 123,
                    "title": "Login button not responding on mobile",
                    "body": "Similar issue description...",
                    "state": "open",
                    "labels": ["bug", "mobile"],
                    "created_at": datetime.now(UTC),
                }
            ],
            "similarity_scores": [],
        }

        result = await smart_searcher._analyze_similarity(state)

        assert len(result["similarity_scores"]) == 1
        assert result["similarity_scores"][0]["similarity_score"] == 0.85
        assert result["similarity_scores"][0]["is_duplicate"] is True

    @pytest.mark.asyncio
    async def test_score_and_rank_filters_low_similarity(self, smart_searcher):
        """Test that score and rank filters out low similarity issues with adaptive thresholds"""
        state = {
            "similarity_scores": [
                {
                    "issue": {
                        "number": 123,
                        "title": "High similarity open issue",
                        "url": "https://github.com/test/test/issues/123",
                        "state": "open",
                        "created_at": datetime.now(UTC) - timedelta(days=10),
                        "updated_at": datetime.now(UTC),
                        "labels": ["bug"],
                    },
                    "similarity_score": 0.8,  # High similarity - should pass
                    "is_duplicate": True,
                    "reasoning": "High similarity",
                },
                {
                    "issue": {
                        "number": 124,
                        "title": "Low similarity open issue",
                        "url": "https://github.com/test/test/issues/124",
                        "state": "open",
                        "created_at": datetime.now(UTC) - timedelta(days=5),
                        "updated_at": datetime.now(UTC),
                        "labels": ["enhancement"],
                    },
                    "similarity_score": 0.2,  # Low similarity - should be filtered (below 0.4 threshold for open)
                    "is_duplicate": False,
                    "reasoning": "Low similarity",
                },
                {
                    "issue": {
                        "number": 125,
                        "title": "Medium similarity old closed issue",
                        "url": "https://github.com/test/test/issues/125",
                        "state": "closed",
                        "created_at": datetime.now(UTC)
                        - timedelta(days=100),  # Old issue
                        "updated_at": datetime.now(UTC) - timedelta(days=90),
                        "labels": ["bug"],
                    },
                    "similarity_score": 0.6,  # Medium similarity - should be filtered (below 0.7 threshold for old closed)
                    "is_duplicate": False,
                    "reasoning": "Medium similarity but old and closed",
                },
            ],
            "final_recommendations": [],
        }

        result = await smart_searcher._score_and_rank(state)

        # Only high similarity open issue should remain
        assert len(result["final_recommendations"]) == 1
        assert result["final_recommendations"][0]["number"] == 123
        assert result["final_recommendations"][0]["similarity_score"] == 0.8

    @pytest.mark.asyncio
    async def test_adaptive_thresholds_recently_closed(self, smart_searcher):
        """Test adaptive thresholds for recently closed issues"""
        state = {
            "similarity_scores": [
                {
                    "issue": {
                        "number": 126,
                        "title": "Recently closed issue with decent similarity",
                        "url": "https://github.com/test/test/issues/126",
                        "state": "closed",
                        "created_at": datetime.now(UTC) - timedelta(days=10),  # Recent
                        "updated_at": datetime.now(UTC) - timedelta(days=5),
                        "labels": ["bug"],
                    },
                    "similarity_score": 0.65,  # Above 0.6 threshold for recently closed
                    "is_duplicate": True,
                    "reasoning": "Good similarity, recently closed",
                },
                {
                    "issue": {
                        "number": 127,
                        "title": "Recently closed issue with low similarity",
                        "url": "https://github.com/test/test/issues/127",
                        "state": "closed",
                        "created_at": datetime.now(UTC) - timedelta(days=15),  # Recent
                        "updated_at": datetime.now(UTC) - timedelta(days=10),
                        "labels": ["enhancement"],
                    },
                    "similarity_score": 0.55,  # Below 0.6 threshold for recently closed
                    "is_duplicate": False,
                    "reasoning": "Medium similarity, recently closed",
                },
            ],
            "final_recommendations": [],
        }

        result = await smart_searcher._score_and_rank(state)

        # Only the issue above 0.6 threshold should remain
        assert len(result["final_recommendations"]) == 1
        assert result["final_recommendations"][0]["number"] == 126
        assert result["final_recommendations"][0]["similarity_score"] == 0.65

    @pytest.mark.asyncio
    async def test_adaptive_thresholds_old_closed(self, smart_searcher):
        """Test adaptive thresholds for old closed issues"""
        state = {
            "similarity_scores": [
                {
                    "issue": {
                        "number": 128,
                        "title": "Old closed issue with high similarity",
                        "url": "https://github.com/test/test/issues/128",
                        "state": "closed",
                        "created_at": datetime.now(UTC) - timedelta(days=200),  # Old
                        "updated_at": datetime.now(UTC) - timedelta(days=180),
                        "labels": ["bug"],
                    },
                    "similarity_score": 0.75,  # Above 0.7 threshold for old closed
                    "is_duplicate": True,
                    "reasoning": "High similarity, old and closed",
                },
                {
                    "issue": {
                        "number": 129,
                        "title": "Old closed issue with medium similarity",
                        "url": "https://github.com/test/test/issues/129",
                        "state": "closed",
                        "created_at": datetime.now(UTC) - timedelta(days=150),  # Old
                        "updated_at": datetime.now(UTC) - timedelta(days=140),
                        "labels": ["enhancement"],
                    },
                    "similarity_score": 0.65,  # Below 0.7 threshold for old closed
                    "is_duplicate": False,
                    "reasoning": "Medium similarity, old and closed",
                },
            ],
            "final_recommendations": [],
        }

        result = await smart_searcher._score_and_rank(state)

        # Only the issue above 0.7 threshold should remain
        assert len(result["final_recommendations"]) == 1
        assert result["final_recommendations"][0]["number"] == 128
        assert result["final_recommendations"][0]["similarity_score"] == 0.75

    def test_calculate_composite_score_open_issue(self, smart_searcher):
        """Test composite score calculation for open issue"""
        issue = {
            "state": "open",
            "created_at": datetime.now(UTC) - timedelta(days=30),  # 1 month old
        }

        score = smart_searcher._calculate_composite_score(0.8, issue)

        # Open issue should have status_factor = 1.0
        # Time factor should be ~0.92 for 1 month old
        expected = (
            0.8 * (1 - 30 / 365) * 1.0
        )  # similarity * time_factor * status_factor
        assert abs(score - expected) < 0.01

    def test_calculate_composite_score_closed_old_issue(self, smart_searcher):
        """Test composite score calculation for old closed issue"""
        issue = {
            "state": "closed",
            "created_at": datetime.now(UTC) - timedelta(days=180),  # 6 months old
        }

        score = smart_searcher._calculate_composite_score(0.8, issue)

        # Old closed issue should have reduced status_factor = 0.5
        expected = 0.8 * (1 - 180 / 365) * 0.5
        assert abs(score - expected) < 0.01

    def test_cache_functionality(self, smart_searcher, mock_analysis):
        """Test caching functionality"""
        # Test cache key generation
        cache_key = smart_searcher._get_cache_key(mock_analysis)
        assert isinstance(cache_key, str)
        assert len(cache_key) > 0

        # Test cache storage and retrieval
        test_result = [{"test": "data"}]
        smart_searcher.cache[cache_key] = (test_result, datetime.now(UTC))

        # Should return cached result
        cached_result, timestamp = smart_searcher.cache[cache_key]
        assert cached_result == test_result
        assert isinstance(timestamp, datetime)

    def test_should_retry_or_fail_logic(self, smart_searcher):
        """Test retry logic conditions"""
        # No errors - continue
        state = {"error_count": 0}
        assert smart_searcher._should_retry_or_fail(state) == "continue"

        # First error - retry
        state = {"error_count": 1}
        assert smart_searcher._should_retry_or_fail(state) == "retry"

        # Second error - retry
        state = {"error_count": 2}
        assert smart_searcher._should_retry_or_fail(state) == "retry"

        # Third error - fail
        state = {"error_count": 3}
        assert smart_searcher._should_retry_or_fail(state) == "fail"
