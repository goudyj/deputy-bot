#!/usr/bin/env python3
"""
Test script to debug issue creation independently
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from deputy.models.config import AppConfig

# Load environment variables
load_dotenv()
from deputy.models.issue import ThreadMessage, IssueType, IssuePriority
from deputy.services.thread_analyzer import ThreadAnalyzer
from deputy.services.github_integration import GitHubIntegration

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_issue_creation():
    """Test the complete issue creation flow"""
    
    # Load config
    config = AppConfig.from_env()
    
    # Check configuration
    logger.info(f"OpenAI API Key: {'***' if config.llm.openai_api_key else 'NOT SET'}")
    logger.info(f"GitHub Token: {'***' if config.github_token else 'NOT SET'}")
    logger.info(f"GitHub Repo: {config.github_org}/{config.github_repo}")
    
    if not config.llm.openai_api_key:
        logger.error("OpenAI API key not set")
        return
    
    if not config.github_token:
        logger.error("GitHub token not set")
        return
    
    # Create test thread messages
    test_messages = [
        ThreadMessage(
            user="alice",
            content="I'm getting a 403 Forbidden error when trying to connect to the platform API. This started happening after the latest deployment.",
            timestamp="2024-06-18T10:00:00Z"
        ),
        ThreadMessage(
            user="bob", 
            content="Can you check the logs? I see this error: 'Authentication failed: Invalid token'",
            timestamp="2024-06-18T10:05:00Z"
        ),
        ThreadMessage(
            user="alice",
            content="Yes, here's the full error: POST /api/v1/connect returned 403. Expected 200 but got permission denied.",
            timestamp="2024-06-18T10:10:00Z"
        )
    ]
    
    logger.info(f"Testing with {len(test_messages)} sample messages")
    
    try:
        # Test thread analysis
        logger.info("=== Testing Thread Analysis ===")
        thread_analyzer = ThreadAnalyzer(config.llm)
        analysis = await thread_analyzer.analyze_thread(test_messages)
        
        logger.info(f"Analysis completed:")
        logger.info(f"  Title: {analysis.suggested_title}")
        logger.info(f"  Type: {analysis.issue_type}")
        logger.info(f"  Priority: {analysis.priority}")
        logger.info(f"  Confidence: {analysis.confidence_score}")
        logger.info(f"  Labels: {analysis.suggested_labels}")
        
        if analysis.confidence_score < 0.3:
            logger.warning("Low confidence analysis")
            return
            
        # Test GitHub integration
        logger.info("=== Testing GitHub Integration ===")
        github_integration = GitHubIntegration(
            config.github_token,
            config.github_org, 
            config.github_repo,
            config.issue_creation
        )
        
        # Test repository access
        try:
            repo_info = await github_integration.get_repository_info()
            logger.info(f"Repository info: {repo_info}")
        except Exception as e:
            logger.error(f"Cannot access repository: {e}")
            return
        
        # Test label validation
        test_labels = ["bug", "high-priority", "api", "authentication"]
        valid_labels = github_integration.validate_labels(test_labels)
        logger.info(f"Label validation: {test_labels} -> {valid_labels}")
        
        # Create the GitHub issue
        logger.info("=== Creating GitHub Issue ===")
        test_permalink = "http://localhost:8065/japau/channels/dev-bugs/test123"
        issue_url = await github_integration.create_issue_from_analysis(analysis, test_permalink)
        
        logger.info(f"✅ SUCCESS! Issue created: {issue_url}")
        
    except Exception as e:
        logger.error(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_issue_creation())