import logging
import re
from typing import Any

from github import Github
from github.Repository import Repository

from deputy.models.issue import (
    GitHubIssue,
    IssueCreationConfig,
    ThreadAnalysis,
    ThreadMessage,
)
from deputy.models.sentry import SentrySearchFilter

logger = logging.getLogger(__name__)


class GitHubIntegration:
    def __init__(self, token: str, org: str, repo: str, config: IssueCreationConfig):
        self.github = Github(token)
        self.org = org
        self.repo_name = repo
        self.config = config
        self._repo: Repository | None = None

    @property
    def repo(self) -> Repository:
        if self._repo is None:
            self._repo = self.github.get_repo(f"{self.org}/{self.repo_name}")
        return self._repo

    async def create_issue_from_analysis(
        self,
        analysis: ThreadAnalysis,
        mattermost_link: str | None = None,
        thread_messages: list[ThreadMessage] | None = None,
        sentry_integration=None,
        force_create: bool = False,
    ) -> str | dict[str, Any]:
        """Create a GitHub issue from thread analysis"""
        try:
            logger.info(f"Creating issue for repo: {self.org}/{self.repo_name}")

            # Step 1: Search for similar issues (unless forced)
            similar_issues = []
            if not force_create:
                logger.info("Searching for similar GitHub issues...")
                similar_issues = await self.search_similar_issues(analysis)

                if similar_issues:
                    logger.info(f"Found {len(similar_issues)} similar issues")
                    # Return warning instead of creating issue
                    return {
                        "type": "similar_issues_found",
                        "similar_issues": similar_issues,
                        "warning_message": self.format_similar_issues_warning(
                            similar_issues
                        ),
                        "analysis": analysis,
                        "mattermost_link": mattermost_link,
                        "thread_messages": thread_messages,
                    }

            # Step 2: Search for related Sentry errors
            logger.info("Searching for related Sentry errors...")
            sentry_errors = await self.search_related_sentry_errors(
                analysis, sentry_integration
            )
            if sentry_errors:
                logger.info(f"Found {len(sentry_errors)} related Sentry errors")

            # Create GitHub issue object with Sentry errors
            github_issue = self._analysis_to_github_issue(
                analysis, mattermost_link, thread_messages, sentry_errors
            )

            logger.info(f"Issue title: {github_issue.title}")
            logger.info(f"Issue labels: {github_issue.labels}")
            logger.info(f"Issue assignees: {github_issue.assignees}")
            logger.info(f"Issue body length: {len(github_issue.body)} chars")

            # Test repository access first
            try:
                repo_info = self.repo
                logger.info(f"Repository accessible: {repo_info.full_name}")
            except Exception as repo_error:
                logger.error(f"Cannot access repository: {repo_error}")
                raise Exception(
                    f"Repository access failed: {repo_error}"
                ) from repo_error

            # Validate labels before creating issue
            valid_labels = self.validate_labels(github_issue.labels)
            logger.info(f"Valid labels after validation: {valid_labels}")

            # Create the issue
            logger.info("Calling GitHub API to create issue...")

            # Prepare create_issue arguments
            issue_args = {
                "title": github_issue.title,
                "body": github_issue.body,
                "labels": valid_labels,
            }

            # Only add assignees if we have some
            if github_issue.assignees:
                issue_args["assignees"] = github_issue.assignees

            issue = self.repo.create_issue(**issue_args)

            logger.info(f"Created GitHub issue #{issue.number}: {issue.title}")
            return issue.html_url

        except Exception as e:
            logger.error(f"Failed to create GitHub issue: {e}")
            logger.error(f"Exception type: {type(e)}")
            logger.error(f"Exception args: {e.args}")
            raise

    def _analysis_to_github_issue(
        self,
        analysis: ThreadAnalysis,
        mattermost_link: str | None = None,
        thread_messages: list[ThreadMessage] | None = None,
        sentry_errors: list[dict[str, Any]] | None = None,
    ) -> GitHubIssue:
        """Convert thread analysis to GitHub issue format"""

        # Build issue body
        body_parts = []

        # Description
        if analysis.detailed_description:
            body_parts.append("## Description")
            body_parts.append(analysis.detailed_description)
            body_parts.append("")

        # Steps to reproduce
        if analysis.steps_to_reproduce:
            body_parts.append("## Steps to Reproduce")
            for i, step in enumerate(analysis.steps_to_reproduce, 1):
                body_parts.append(f"{i}. {step}")
            body_parts.append("")

        # Expected vs Actual behavior
        if analysis.expected_behavior or analysis.actual_behavior:
            body_parts.append("## Expected vs Actual Behavior")
            if analysis.expected_behavior:
                body_parts.append(f"**Expected:** {analysis.expected_behavior}")
            if analysis.actual_behavior:
                body_parts.append(f"**Actual:** {analysis.actual_behavior}")
            body_parts.append("")

        # Additional context
        if analysis.additional_context:
            body_parts.append("## Additional Context")
            body_parts.append(analysis.additional_context)
            body_parts.append("")

        # Images and Attachments from thread
        if thread_messages:
            images = []
            files = []

            for msg in thread_messages:
                for attachment in msg.attachments:
                    if attachment.is_image:
                        images.append(attachment)
                    else:
                        files.append(attachment)

            if images:
                body_parts.append("## Screenshots & Images")
                body_parts.append(
                    "*The following images were attached to the discussion:*"
                )
                body_parts.append("")
                for i, img in enumerate(images, 1):
                    file_info = f"{i}. 📸 **{img.filename}**"
                    if img.mime_type:
                        file_info += f" ({img.mime_type})"
                    if img.size:
                        size_mb = img.size / (1024 * 1024)
                        file_info += f" - {size_mb:.1f} MB"
                    body_parts.append(file_info)
                    body_parts.append(
                        f"   > [View in Mattermost thread]({img.url}) *(requires authentication)*"
                    )
                body_parts.append("")
                body_parts.append(
                    "💡 **To view images**: Please check the Mattermost thread link below or ask the reporter to attach them directly to this GitHub issue."
                )
                body_parts.append("")

            if files:
                body_parts.append("## Related Files")
                for file in files:
                    file_info = f"📎 [{file.filename}]({file.url})"
                    if file.mime_type:
                        file_info += f" ({file.mime_type})"
                    if file.size:
                        size_kb = file.size / 1024
                        file_info += f" [{size_kb:.1f} KB]"
                    body_parts.append(file_info)
                body_parts.append("")

        # Mattermost link
        if mattermost_link:
            body_parts.append("## Related Discussion")
            body_parts.append(
                f"[View original thread in Mattermost]({mattermost_link})"
            )
            body_parts.append("")

        # Sentry errors section
        if sentry_errors:
            sentry_section = self.format_sentry_errors_section(sentry_errors)
            if sentry_section:
                body_parts.append(sentry_section)

        # Metadata
        body_parts.append("---")
        body_parts.append(f"**Issue Type:** {analysis.issue_type.value}")
        body_parts.append(f"**Priority:** {analysis.priority.value}")
        body_parts.append(f"**Analysis Confidence:** {analysis.confidence_score:.2f}")
        body_parts.append("")
        body_parts.append("*This issue was automatically created by Deputy Bot*")

        # Combine labels (only use suggested labels from LLM + configured auto labels)
        labels = list(set(analysis.suggested_labels + self.config.auto_labels))

        # Note: Don't automatically add priority labels as they may not exist in the repo

        # Assignees
        assignees = []
        if self.config.default_assignee:
            assignees.append(self.config.default_assignee)

        return GitHubIssue(
            title=analysis.suggested_title,
            body="\n".join(body_parts),
            labels=labels,
            assignees=assignees,
        )

    async def get_repository_info(self) -> dict:
        """Get repository information for validation"""
        try:
            repo = self.repo
            return {
                "name": repo.name,
                "full_name": repo.full_name,
                "description": repo.description,
                "private": repo.private,
                "has_issues": repo.has_issues,
                "open_issues": repo.open_issues_count,
            }
        except Exception as e:
            logger.error(f"Failed to get repository info: {e}")
            raise

    def validate_labels(self, labels: list[str]) -> list[str]:
        """Validate that labels exist in the repository"""
        try:
            repo_labels = [label.name for label in self.repo.get_labels()]
            valid_labels = [label for label in labels if label in repo_labels]

            invalid_labels = set(labels) - set(valid_labels)
            if invalid_labels:
                logger.warning(f"Invalid labels will be ignored: {invalid_labels}")

            return valid_labels
        except Exception as e:
            logger.error(f"Failed to validate labels: {e}")
            return []  # Return empty list if validation fails

    def _extract_keywords(self, analysis: ThreadAnalysis) -> list[str]:
        """Extract relevant keywords from thread analysis for searching"""
        keywords = []

        # Add words from title (remove common words)
        title_words = re.findall(r"\b\w{3,}\b", analysis.suggested_title.lower())
        keywords.extend(
            [w for w in title_words if w not in {"error", "issue", "problem", "bug"}]
        )

        # Add technical terms from description
        if analysis.detailed_description:
            # Look for technical terms (CamelCase, snake_case, or quoted strings)
            tech_terms = re.findall(
                r'\b[A-Z][a-z]+[A-Z]\w*\b|\b\w+_\w+\b|"[^"]+"|\'[^\']+\'',
                analysis.detailed_description,
            )
            keywords.extend([term.strip("\"'") for term in tech_terms])

        # Add error types from suggested labels
        error_keywords = [
            label
            for label in analysis.suggested_labels
            if label in ["timeout", "connection", "database", "authentication", "api"]
        ]
        keywords.extend(error_keywords)

        # Remove duplicates and return top 5 most relevant
        return list(dict.fromkeys(keywords))[:5]

    async def search_similar_issues(
        self, analysis: ThreadAnalysis
    ) -> list[dict[str, Any]]:
        """Search for similar issues in the GitHub repository"""
        try:
            keywords = self._extract_keywords(analysis)
            if not keywords:
                return []

            # Build search query
            search_terms = " OR ".join(f'"{keyword}"' for keyword in keywords)
            query = f"repo:{self.org}/{self.repo_name} is:issue {search_terms}"

            logger.info(f"Searching for similar issues with query: {query}")

            # Search using GitHub API
            search_result = self.github.search_issues(
                query=query, sort="updated", order="desc"
            )

            similar_issues = []
            for issue in search_result[:3]:  # Limit to top 3 results
                similar_issues.append(
                    {
                        "number": issue.number,
                        "title": issue.title,
                        "url": issue.html_url,
                        "state": issue.state,
                        "updated_at": issue.updated_at.isoformat(),
                        "labels": [label.name for label in issue.labels],
                    }
                )

            logger.info(f"Found {len(similar_issues)} similar issues")
            return similar_issues

        except Exception as e:
            logger.error(f"Failed to search similar issues: {e}")
            return []

    def format_similar_issues_warning(
        self, similar_issues: list[dict[str, Any]]
    ) -> str:
        """Format similar issues warning message"""
        if not similar_issues:
            return ""

        warning = "⚠️ **Similar Issues Found:**\n\n"

        for issue in similar_issues:
            state_emoji = "🟢" if issue["state"] == "open" else "🔴"
            warning += f"{state_emoji} **#{issue['number']}**: {issue['title']}\n"
            warning += f"   🔗 {issue['url']}\n"
            if issue["labels"]:
                warning += f"   🏷️ Labels: {', '.join(issue['labels'])}\n"
            warning += "\n"

        warning += "**Do you want to continue creating a new issue?**\n"
        warning += "Reply with `@deputy yes` to continue or `@deputy no` to cancel."

        return warning

    async def search_related_sentry_errors(
        self, analysis: ThreadAnalysis, sentry_integration=None
    ) -> list[dict[str, Any]]:
        """Search for related Sentry errors"""
        if not sentry_integration or not sentry_integration.config.is_configured():
            return []

        try:
            # Extract search terms from analysis
            keywords = self._extract_keywords(analysis)
            if not keywords:
                return []

            # Search for each keyword in Sentry
            related_errors = []
            for keyword in keywords[:3]:  # Limit to top 3 keywords
                try:
                    filters = SentrySearchFilter(
                        query=keyword,
                        period="7d",  # Look at last 7 days
                        limit=2,  # Max 2 results per keyword
                        status="unresolved",
                    )

                    issues = await sentry_integration.search_issues(filters)
                    for issue in issues:
                        related_errors.append(
                            {
                                "keyword": keyword,
                                "id": issue.id,
                                "short_id": issue.short_id,
                                "title": issue.title,
                                "permalink": issue.permalink,
                                "level": issue.level,
                                "count": issue.count,
                                "last_seen": issue.last_seen.isoformat(),
                            }
                        )

                except Exception as e:
                    logger.warning(
                        f"Failed to search Sentry for keyword '{keyword}': {e}"
                    )
                    continue

            # Remove duplicates by issue ID and limit results
            seen_ids = set()
            unique_errors = []
            for error in related_errors:
                if error["id"] not in seen_ids:
                    seen_ids.add(error["id"])
                    unique_errors.append(error)
                    if len(unique_errors) >= 3:  # Limit to 3 total results
                        break

            logger.info(f"Found {len(unique_errors)} related Sentry errors")
            return unique_errors

        except Exception as e:
            logger.error(f"Failed to search related Sentry errors: {e}")
            return []

    def format_sentry_errors_section(self, sentry_errors: list[dict[str, Any]]) -> str:
        """Format Sentry errors section for GitHub issue"""
        if not sentry_errors:
            return ""

        section = "## 🔴 Related Sentry Errors\n\n"
        section += "The following Sentry errors might be related to this issue:\n\n"

        for error in sentry_errors:
            level_emoji = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(
                error["level"], "❓"
            )
            section += f"{level_emoji} **{error['short_id']}**: {error['title']}\n"
            section += f"   💥 {error['count']} events • ⏰ Last seen: {error['last_seen'][:10]}\n"
            section += f"   🔗 [View in Sentry]({error['permalink']})\n"
            section += f"   🔍 Found via keyword: `{error['keyword']}`\n\n"

        return section
