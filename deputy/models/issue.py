from enum import Enum

from pydantic import BaseModel


class IssuePriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    ENHANCEMENT = "enhancement"
    DOCUMENTATION = "documentation"
    QUESTION = "question"
    TASK = "task"


class AttachmentInfo(BaseModel):
    """Information about a file attachment"""

    url: str
    filename: str
    mime_type: str | None = None
    size: int | None = None
    is_image: bool = False


class ThreadMessage(BaseModel):
    user: str
    content: str
    timestamp: str
    attachments: list[AttachmentInfo] = []  # Detailed attachment info


class ThreadAnalysis(BaseModel):
    summary: str
    issue_type: IssueType
    priority: IssuePriority
    suggested_title: str
    detailed_description: str
    steps_to_reproduce: list[str] = []
    expected_behavior: str | None = None
    actual_behavior: str | None = None
    additional_context: str | None = None
    suggested_labels: list[str] = []
    confidence_score: float  # 0-1 confidence in analysis


class GitHubIssue(BaseModel):
    title: str
    body: str
    labels: list[str] = []
    assignees: list[str] = []
    milestone: str | None = None


class IssueCreationConfig(BaseModel):
    auto_labels: list[str] = []
    default_assignee: str | None = None
    project_id: str | None = None
    template_mapping: dict[IssueType, str] = {}

    @classmethod
    def from_env(cls):
        import os

        auto_labels_str = os.getenv("ISSUE_AUTO_LABELS", "")
        auto_labels = [
            label.strip() for label in auto_labels_str.split(",") if label.strip()
        ]

        return cls(
            auto_labels=auto_labels,
            default_assignee=os.getenv("ISSUE_ASSIGNEE"),
            project_id=os.getenv("ISSUE_PROJECT_ID"),
            template_mapping={
                IssueType.BUG: "bug_template",
                IssueType.FEATURE: "feature_template",
                IssueType.ENHANCEMENT: "enhancement_template",
            },
        )
