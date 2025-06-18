from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum


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


class ThreadMessage(BaseModel):
    user: str
    content: str
    timestamp: str
    attachments: List[str] = []  # URLs to images/files
    
    
class ThreadAnalysis(BaseModel):
    summary: str
    issue_type: IssueType
    priority: IssuePriority
    suggested_title: str
    detailed_description: str
    steps_to_reproduce: List[str] = []
    expected_behavior: Optional[str] = None
    actual_behavior: Optional[str] = None
    additional_context: Optional[str] = None
    suggested_labels: List[str] = []
    confidence_score: float  # 0-1 confidence in analysis


class GitHubIssue(BaseModel):
    title: str
    body: str
    labels: List[str] = []
    assignees: List[str] = []
    milestone: Optional[str] = None
    
    
class IssueCreationConfig(BaseModel):
    auto_labels: List[str] = []
    default_assignee: Optional[str] = None
    project_id: Optional[str] = None
    template_mapping: Dict[IssueType, str] = {}
    
    @classmethod
    def from_env(cls):
        import os
        
        auto_labels_str = os.getenv("ISSUE_AUTO_LABELS", "")
        auto_labels = [label.strip() for label in auto_labels_str.split(",") if label.strip()]
        
        return cls(
            auto_labels=auto_labels,
            default_assignee=os.getenv("ISSUE_ASSIGNEE"),
            project_id=os.getenv("ISSUE_PROJECT_ID"),
            template_mapping={
                IssueType.BUG: "bug_template",
                IssueType.FEATURE: "feature_template",
                IssueType.ENHANCEMENT: "enhancement_template"
            }
        )