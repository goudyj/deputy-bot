# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Deputy is an agentic bot that helps development teams handle bugs and prioritize tasks. It operates as a Mattermost bot that integrates with GitHub and Sentry to automatically create issues from team conversations using AI analysis.

## Technology Stack

- **Python 3.13+** with **UV** package manager
- **aiohttp** for async HTTP operations
- **LangChain/LangGraph** for AI conversation analysis (OpenAI/Anthropic)
- **Pydantic** for configuration and data models
- **pytest** for testing, **Ruff** for code quality

## Essential Commands

```bash
# Development
uv sync                    # Install dependencies
uv run python main.py      # Run the bot
uv run pytest             # Run all tests
uv run pytest tests/test_bot.py::test_specific  # Run specific test
uv run ruff check          # Lint code
uv run ruff format         # Format code

# Local Mattermost development
docker-compose up -d       # Start Mattermost server
docker-compose down        # Stop server
```

**Important**: 
- Always run `uv run ruff check` and `uv run ruff format` before committing and after completing any coding task to ensure code quality
- Write unit tests with pytest for any new functionality added to the codebase, following existing test patterns in the `tests/` directory
- Write concise commit messages following the pattern: `type: brief description` (e.g., `feat: add inline issue creation`, `fix: handle wildcard channels`)

## Architecture

### Core Components
- **`deputy/bot.py`**: Main bot with WebSocket connection to Mattermost, event processing
- **`deputy/services/thread_analyzer.py`**: LangGraph-based conversation analysis using LLMs
- **`deputy/services/github_integration.py`**: GitHub issue creation from analyzed conversations
- **`deputy/services/sentry_integration.py`**: Error monitoring integration
- **`deputy/models/`**: Pydantic configuration and data models

### Key Patterns
- **Async-first architecture**: All I/O operations use async/await
- **Event-driven**: WebSocket message processing with regex channel matching
- **Service-oriented**: Clear separation between bot logic, integrations, and AI services
- **Configuration-driven**: Extensive environment-based config via Pydantic models

### Data Flow
1. Bot monitors Mattermost channels via WebSocket
2. Thread analyzer uses LLM to extract structured issue data from conversations
3. GitHub integration creates issues with labels, assignees, and attachments
4. Sentry integration correlates errors with conversation context

## Configuration

The bot requires extensive environment configuration for:
- Mattermost connection (URL, token, team, channel patterns)
- LLM provider (OpenAI/Anthropic with API keys, model selection)
- GitHub integration (token, org/repo, issue settings)
- Optional Sentry integration (DSN, org, project)

See `.env.example` for complete configuration template.

## Testing

- 25+ test files covering all major components
- Use `conftest.py` for shared test fixtures
- Async test patterns throughout
- Mock external integrations (Mattermost, GitHub, Sentry)