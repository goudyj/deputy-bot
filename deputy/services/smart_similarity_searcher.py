"""
Smart similarity searcher using LangGraph for intelligent duplicate issue detection
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from deputy.models.issue import ThreadAnalysis
from deputy.models.llm_config import LLMConfig

logger = logging.getLogger(__name__)


class SimilaritySearchState(TypedDict):
    """State for the similarity search graph"""

    original_analysis: ThreadAnalysis
    smart_keywords: list[str]
    raw_search_results: list[dict[str, Any]]
    detailed_issues: list[dict[str, Any]]
    similarity_scores: list[dict[str, Any]]
    final_recommendations: list[dict[str, Any]]
    error_count: int


class KeywordExtraction(BaseModel):
    """Pydantic model for keyword extraction response"""

    keywords: list[str]
    reasoning: str


class SimilarityAnalysis(BaseModel):
    """Pydantic model for similarity analysis response"""

    similarity_score: float
    is_duplicate: bool
    reasoning: str


class SmartSimilaritySearcher:
    """Smart similarity searcher using LangGraph and LLM analysis"""

    def __init__(self, llm_config: LLMConfig, github_integration):
        self.llm_config = llm_config
        self.github = github_integration
        self.llm = None
        self.cache = {}  # Simple in-memory cache
        self.cache_ttl = timedelta(minutes=10)

        # Initialize LLM
        self._initialize_llm()

        # Create the graph
        self.graph = self._create_similarity_graph()

    def _initialize_llm(self):
        """Initialize the LLM based on configuration"""
        if self.llm_config.provider == "openai":
            from langchain_openai import ChatOpenAI

            self.llm = ChatOpenAI(
                model=self.llm_config.model,
                temperature=self.llm_config.temperature,
                max_tokens=self.llm_config.max_tokens,
                api_key=self.llm_config.openai_api_key,
            )
        elif self.llm_config.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            self.llm = ChatAnthropic(
                model=self.llm_config.model,
                temperature=self.llm_config.temperature,
                max_tokens=self.llm_config.max_tokens,
                api_key=self.llm_config.anthropic_api_key,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.llm_config.provider}")

    def _create_similarity_graph(self) -> StateGraph:
        """Create the LangGraph for similarity search"""
        workflow = StateGraph(SimilaritySearchState)

        # Add nodes
        workflow.add_node("extract_keywords", self._extract_smart_keywords)
        workflow.add_node("search_github", self._search_github_issues)
        workflow.add_node("fetch_details", self._fetch_issue_details)
        workflow.add_node("analyze_similarity", self._analyze_similarity)
        workflow.add_node("score_and_rank", self._score_and_rank)
        workflow.add_node("handle_error", self._handle_error)

        # Define the flow
        workflow.set_entry_point("extract_keywords")

        workflow.add_edge("extract_keywords", "search_github")
        workflow.add_edge("search_github", "fetch_details")
        workflow.add_edge("fetch_details", "analyze_similarity")
        workflow.add_edge("analyze_similarity", "score_and_rank")
        workflow.add_edge("score_and_rank", END)
        workflow.add_edge("handle_error", END)

        # Add conditional edges for error handling
        workflow.add_conditional_edges(
            "extract_keywords",
            self._should_retry_or_fail,
            {
                "retry": "extract_keywords",
                "fail": "handle_error",
                "continue": "search_github",
            },
        )

        return workflow.compile()

    async def search_similar_issues(
        self, analysis: ThreadAnalysis
    ) -> list[dict[str, Any]]:
        """Main entry point for similarity search"""
        try:
            # Check cache first
            cache_key = self._get_cache_key(analysis)
            if cache_key in self.cache:
                cached_result, timestamp = self.cache[cache_key]
                if datetime.now() - timestamp < self.cache_ttl:
                    logger.info("Returning cached similarity search results")
                    return cached_result

            # Initialize state
            initial_state = SimilaritySearchState(
                original_analysis=analysis,
                smart_keywords=[],
                raw_search_results=[],
                detailed_issues=[],
                similarity_scores=[],
                final_recommendations=[],
                error_count=0,
            )

            # Run the graph
            result = await self.graph.ainvoke(initial_state)

            # Cache the result
            self.cache[cache_key] = (result["final_recommendations"], datetime.now())

            return result["final_recommendations"]

        except Exception as e:
            logger.error(f"Smart similarity search failed: {e}")
            return []

    async def _extract_smart_keywords(self, state: SimilaritySearchState) -> dict:
        """Extract smart keywords using LLM"""
        try:
            analysis = state["original_analysis"]

            system_prompt = """You are an expert at extracting the most specific and relevant keywords from software issue descriptions to find duplicate issues.

Your task is to extract 3-5 highly specific technical keywords that would uniquely identify similar issues in a GitHub repository.

Focus on:
- Specific technical terms, API names, component names
- Error types, status codes, method names
- Unique behavioral descriptions
- Avoid generic words like "error", "issue", "problem", "bug"

Extract keywords that a developer would use when searching for the same problem."""

            user_prompt = f"""Issue Title: {analysis.suggested_title}

Issue Description: {analysis.detailed_description}

Issue Type: {analysis.issue_type.value}

Additional Context: {analysis.additional_context or "None"}

Extract the most specific keywords that would help find duplicate issues."""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            # Use structured output
            structured_llm = self.llm.with_structured_output(KeywordExtraction)
            response = await structured_llm.ainvoke(messages)

            logger.info(f"Extracted keywords: {response.keywords}")
            logger.info(f"Reasoning: {response.reasoning}")

            return {
                **state,
                "smart_keywords": response.keywords[:5],  # Limit to 5
                "error_count": 0,
            }

        except Exception as e:
            logger.error(f"Keyword extraction failed: {e}")
            return {**state, "error_count": state["error_count"] + 1}

    async def _search_github_issues(self, state: SimilaritySearchState) -> dict:
        """Search GitHub issues using extracted keywords"""
        try:
            keywords = state["smart_keywords"]
            if not keywords:
                logger.warning("No keywords available for search")
                return {**state, "raw_search_results": []}

            # Build search query with time filter (last 6 months)
            six_months_ago = datetime.now() - timedelta(days=180)
            date_filter = six_months_ago.strftime("%Y-%m-%d")

            search_terms = " OR ".join(f'"{keyword}"' for keyword in keywords)
            query = f"repo:{self.github.org}/{self.github.repo_name} is:issue created:>{date_filter} {search_terms}"

            logger.info(f"GitHub search query: {query}")

            # Search using GitHub API
            search_result = self.github.github.search_issues(
                query=query, sort="updated", order="desc"
            )

            # Get top 10 results for initial filtering
            raw_results = []
            for issue in search_result[:10]:
                raw_results.append(
                    {
                        "number": issue.number,
                        "title": issue.title,
                        "url": issue.html_url,
                        "state": issue.state,
                        "created_at": issue.created_at,
                        "updated_at": issue.updated_at,
                        "labels": [label.name for label in issue.labels],
                    }
                )

            logger.info(f"Found {len(raw_results)} issues in GitHub search")

            return {**state, "raw_search_results": raw_results}

        except Exception as e:
            logger.error(f"GitHub search failed: {e}")
            return {**state, "raw_search_results": []}

    async def _fetch_issue_details(self, state: SimilaritySearchState) -> dict:
        """Fetch detailed content for top issues"""
        try:
            raw_results = state["raw_search_results"]

            # Select top 5 issues for detailed analysis
            top_issues = raw_results[:5]

            detailed_issues = []
            for issue_data in top_issues:
                try:
                    # Fetch full issue details
                    issue = self.github.repo.get_issue(issue_data["number"])

                    detailed_issues.append(
                        {
                            **issue_data,
                            "body": issue.body or "",
                            "comments_count": issue.comments,
                        }
                    )

                except Exception as e:
                    logger.warning(
                        f"Failed to fetch details for issue #{issue_data['number']}: {e}"
                    )
                    # Keep the issue but without body
                    detailed_issues.append(
                        {
                            **issue_data,
                            "body": "",
                            "comments_count": 0,
                        }
                    )

            logger.info(f"Fetched details for {len(detailed_issues)} issues")

            return {**state, "detailed_issues": detailed_issues}

        except Exception as e:
            logger.error(f"Issue details fetching failed: {e}")
            return {
                **state,
                "detailed_issues": state["raw_search_results"][
                    :5
                ],  # Fallback without body
            }

    async def _analyze_similarity(self, state: SimilaritySearchState) -> dict:
        """Analyze similarity using LLM"""
        try:
            original_analysis = state["original_analysis"]
            detailed_issues = state["detailed_issues"]

            similarity_scores = []

            for issue in detailed_issues:
                try:
                    system_prompt = """You are an expert software engineer analyzing whether two GitHub issues describe the same problem.

Compare the original issue with the existing issue and determine:
1. Similarity score (0.0 to 1.0, where 1.0 means identical problems)
2. Whether this is likely a duplicate (true/false)
3. Clear reasoning for your decision

Consider:
- Core problem description
- Technical symptoms and error messages
- Affected components/features
- Context and environment

A score of 0.7+ typically indicates a likely duplicate."""

                    user_prompt = f"""ORIGINAL ISSUE:
Title: {original_analysis.suggested_title}
Description: {original_analysis.detailed_description}
Type: {original_analysis.issue_type.value}
Context: {original_analysis.additional_context or "None"}

EXISTING ISSUE #{issue["number"]}:
Title: {issue["title"]}
Body: {issue["body"][:1500]}...
State: {issue["state"]}
Labels: {", ".join(issue["labels"])}
Created: {issue["created_at"]}

Analyze if these describe the same underlying problem."""

                    messages = [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_prompt),
                    ]

                    structured_llm = self.llm.with_structured_output(SimilarityAnalysis)
                    response = await structured_llm.ainvoke(messages)

                    similarity_scores.append(
                        {
                            "issue": issue,
                            "similarity_score": response.similarity_score,
                            "is_duplicate": response.is_duplicate,
                            "reasoning": response.reasoning,
                        }
                    )

                    logger.info(
                        f"Issue #{issue['number']} similarity: {response.similarity_score:.2f}"
                    )

                except Exception as e:
                    logger.warning(
                        f"Similarity analysis failed for issue #{issue['number']}: {e}"
                    )
                    # Assign low similarity if analysis fails
                    similarity_scores.append(
                        {
                            "issue": issue,
                            "similarity_score": 0.0,
                            "is_duplicate": False,
                            "reasoning": f"Analysis failed: {str(e)}",
                        }
                    )

            return {**state, "similarity_scores": similarity_scores}

        except Exception as e:
            logger.error(f"Similarity analysis failed: {e}")
            return {**state, "similarity_scores": []}

    async def _score_and_rank(self, state: SimilaritySearchState) -> dict:
        """Calculate composite scores and rank issues"""
        try:
            similarity_scores = state["similarity_scores"]

            final_recommendations = []

            for score_data in similarity_scores:
                issue = score_data["issue"]
                similarity = score_data["similarity_score"]

                # Calculate composite score
                composite_score = self._calculate_composite_score(similarity, issue)

                # Use adaptive threshold based on issue age and status
                # Handle timezone-aware datetime from GitHub API
                now = datetime.now(UTC)
                created_at = issue["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=UTC)
                days_old = (now - created_at).days

                if issue["state"] == "open":
                    threshold = 0.4  # Normal threshold for open issues
                elif days_old < 30:  # Recently closed
                    threshold = 0.6  # Stricter for recently closed
                else:  # Old closed issues
                    threshold = 0.7  # Very strict for old closed issues

                if similarity > threshold:
                    final_recommendations.append(
                        {
                            "number": issue["number"],
                            "title": issue["title"],
                            "url": issue["url"],
                            "state": issue["state"],
                            "similarity_score": similarity,
                            "composite_score": composite_score,
                            "reasoning": score_data["reasoning"],
                            "is_duplicate": score_data["is_duplicate"],
                            "age_days": days_old,
                            "labels": issue["labels"],
                            "updated_at": issue["updated_at"].isoformat(),
                        }
                    )

            # Sort by composite score (highest first)
            final_recommendations.sort(key=lambda x: x["composite_score"], reverse=True)

            # Limit to top 3 recommendations
            final_recommendations = final_recommendations[:3]

            logger.info(f"Final recommendations: {len(final_recommendations)} issues")

            return {**state, "final_recommendations": final_recommendations}

        except Exception as e:
            logger.error(f"Scoring and ranking failed: {e}")
            return {**state, "final_recommendations": []}

    def _calculate_composite_score(
        self, similarity: float, issue: dict[str, Any]
    ) -> float:
        """Calculate composite score based on similarity, age, and status"""
        base_score = similarity

        # Time factor (newer issues are more relevant)
        # Handle timezone-aware datetime from GitHub API
        now = datetime.now(UTC)
        created_at = issue["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        days_old = (now - created_at).days
        time_factor = max(0.3, 1 - (days_old / 365))  # Decays over 1 year

        # Status factor
        if issue["state"] == "open":
            status_factor = 1.0
        elif days_old < 30:  # Recently closed
            status_factor = 0.8
        else:  # Old and closed
            status_factor = 0.5

        return base_score * time_factor * status_factor

    def _should_retry_or_fail(self, state: SimilaritySearchState) -> str:
        """Determine whether to retry, fail, or continue"""
        error_count = state.get("error_count", 0)

        if error_count == 0:
            return "continue"
        elif error_count < 3:
            return "retry"
        else:
            return "fail"

    async def _handle_error(self, state: SimilaritySearchState) -> dict:
        """Handle final error state"""
        logger.error("Smart similarity search failed after 3 retries")
        return {**state, "final_recommendations": []}

    def _get_cache_key(self, analysis: ThreadAnalysis) -> str:
        """Generate cache key for analysis"""
        # Simple cache key based on title and description hash
        content = f"{analysis.suggested_title}:{analysis.detailed_description}"
        return str(hash(content))
