import logging

from github import Github
from github.Repository import Repository

from deputy.models.issue import (
    GitHubIssue,
    IssueCreationConfig,
    ThreadAnalysis,
    ThreadMessage,
)

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
    ) -> str:
        """Create a GitHub issue from thread analysis"""
        try:
            logger.info(f"Creating issue for repo: {self.org}/{self.repo_name}")

            # Create GitHub issue object
            github_issue = self._analysis_to_github_issue(
                analysis, mattermost_link, thread_messages
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
                body_parts.append("*The following images were attached to the discussion:*")
                body_parts.append("")
                for i, img in enumerate(images, 1):
                    file_info = f"{i}. 📸 **{img.filename}**"
                    if img.mime_type:
                        file_info += f" ({img.mime_type})"
                    if img.size:
                        size_mb = img.size / (1024 * 1024)
                        file_info += f" - {size_mb:.1f} MB"
                    body_parts.append(file_info)
                    body_parts.append(f"   > [View in Mattermost thread]({img.url}) *(requires authentication)*")
                body_parts.append("")
                body_parts.append("💡 **To view images**: Please check the Mattermost thread link below or ask the reporter to attach them directly to this GitHub issue.")
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
