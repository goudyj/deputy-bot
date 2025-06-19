import os
import re

from pydantic import BaseModel

from .issue import IssueCreationConfig
from .llm_config import LLMConfig


class MattermostConfig(BaseModel):
    url: str
    token: str
    team_name: str
    channels: list[str]
    bot_name: str

    @classmethod
    def from_env(cls):
        channels_str = os.getenv("MATTERMOST_CHANNELS", "")
        channels = [ch.strip() for ch in channels_str.split(",") if ch.strip()]

        return cls(
            url=os.getenv("MATTERMOST_URL", ""),
            token=os.getenv("MATTERMOST_TOKEN", ""),
            team_name=os.getenv("MATTERMOST_TEAM_NAME", ""),
            channels=channels,
            bot_name=os.getenv("MATTERMOST_BOT_NAME", "deputy"),
        )

    def should_listen_to_channel(self, channel_name: str) -> bool:
        for pattern in self.channels:
            if re.match(pattern, channel_name):
                return True
        return False


class AppConfig(BaseModel):
    mattermost: MattermostConfig
    llm: LLMConfig
    issue_creation: IssueCreationConfig
    debug: bool = False

    github_token: str = ""
    github_org: str = ""
    github_repo: str = ""

    sentry_dsn: str = ""
    sentry_org: str = ""
    sentry_project: str = ""
    sentry_auth_token: str = ""

    @classmethod
    def from_env(cls):
        return cls(
            mattermost=MattermostConfig.from_env(),
            llm=LLMConfig.from_env(),
            issue_creation=IssueCreationConfig.from_env(),
            debug=os.getenv("DEBUG", "false").lower() == "true",
            github_token=os.getenv("GITHUB_TOKEN", ""),
            github_org=os.getenv("GITHUB_ORG", ""),
            github_repo=os.getenv("GITHUB_REPO", ""),
            sentry_dsn=os.getenv("SENTRY_DSN", ""),
            sentry_org=os.getenv("SENTRY_ORG", ""),
            sentry_project=os.getenv("SENTRY_PROJECT", ""),
            sentry_auth_token=os.getenv("SENTRY_AUTH_TOKEN", ""),
        )
