import os

from pydantic import BaseModel


class LLMConfig(BaseModel):
    provider: str = "openai"  # openai or anthropic
    model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    temperature: float = 0.1
    max_tokens: int = 2000

    @classmethod
    def from_env(cls):
        return cls(
            provider=os.getenv("LLM_PROVIDER", "openai"),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "2000")),
        )

    def get_api_key(self) -> str | None:
        if self.provider == "openai":
            return self.openai_api_key
        elif self.provider == "anthropic":
            return self.anthropic_api_key
        return None
