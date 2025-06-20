import json
import logging
from typing import Any

import aiohttp

from deputy.models.config import AppConfig
from deputy.models.sentry import SentrySearchFilter
from deputy.services.github_integration import GitHubIntegration
from deputy.services.mattermost_thread import MattermostThreadService
from deputy.services.sentry_integration import SentryIntegration
from deputy.services.thread_analyzer import ThreadAnalyzer

logger = logging.getLogger(__name__)


class DeputyBot:
    def __init__(self, config: AppConfig):
        self.config = config
        self.session = None
        self.websocket = None
        self.team_id = None
        self.bot_user_id = None
        self.headers = {
            "Authorization": f"Bearer {config.mattermost.token}",
            "Content-Type": "application/json",
        }

        # Initialize services
        self.thread_analyzer = None
        self.github_integration = None
        self.thread_service = None
        self.sentry_integration = None

        # Store pending issues (thread_id -> issue_data)
        self.pending_issues: dict[str, dict] = {}

    async def start(self):
        try:
            self.session = aiohttp.ClientSession()
            logger.info(f"Starting bot {self.config.mattermost.bot_name}...")

            await self._initialize()
            self._initialize_services()
            await self._start_websocket()

        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise
        finally:
            if self.session:
                await self.session.close()

    async def _initialize(self):
        # Get bot information
        async with self.session.get(
            f"{self.config.mattermost.url}/api/v4/users/me", headers=self.headers
        ) as resp:
            if resp.status != 200:
                raise Exception(f"Error retrieving bot info: {resp.status}")
            me = await resp.json()
            self.bot_user_id = me["id"]
            logger.info(f"Bot user ID: {self.bot_user_id}")

        # Get team information
        async with self.session.get(
            f"{self.config.mattermost.url}/api/v4/teams/name/{self.config.mattermost.team_name}",
            headers=self.headers,
        ) as resp:
            if resp.status == 200:
                team = await resp.json()
                self.team_id = team["id"]
                logger.info(f"Team ID: {self.team_id}")
            else:
                # Fallback: use the first available team
                logger.warning(
                    f"Team '{self.config.mattermost.team_name}' not found, using first available team"
                )
                async with self.session.get(
                    f"{self.config.mattermost.url}/api/v4/users/me/teams",
                    headers=self.headers,
                ) as teams_resp:
                    if teams_resp.status == 200:
                        teams = await teams_resp.json()
                        if teams:
                            self.team_id = teams[0]["id"]
                            logger.info(
                                f"Using team: {teams[0]['name']} (ID: {self.team_id})"
                            )
                        else:
                            raise Exception("No team available for the bot")
                    else:
                        raise Exception("Unable to retrieve teams")

    def _initialize_services(self):
        """Initialize LLM and GitHub services"""
        try:
            # Initialize thread analyzer if LLM is configured
            if self.config.llm.get_api_key():
                self.thread_analyzer = ThreadAnalyzer(self.config.llm)
                logger.info("Thread analyzer initialized")
            else:
                logger.warning("No LLM API key found - thread analysis disabled")

            # Initialize GitHub integration if configured
            if (
                self.config.github_token
                and self.config.github_org
                and self.config.github_repo
            ):
                self.github_integration = GitHubIntegration(
                    self.config.github_token,
                    self.config.github_org,
                    self.config.github_repo,
                    self.config.issue_creation,
                )
                logger.info("GitHub integration initialized")
            else:
                logger.warning("GitHub not configured - issue creation disabled")

            # Initialize thread service
            self.thread_service = MattermostThreadService(
                self.session, self.config.mattermost.url, self.headers
            )

            # Initialize Sentry integration if configured
            if self.config.sentry.is_configured():
                self.sentry_integration = SentryIntegration(self.config.sentry)
                logger.info("Sentry integration initialized")
            else:
                logger.warning("Sentry not configured - error monitoring disabled")

        except Exception as e:
            logger.error(f"Error initializing services: {e}")
            # Continue without services rather than failing

    async def _start_websocket(self):
        ws_url = self.config.mattermost.url.replace("http://", "ws://").replace(
            "https://", "wss://"
        )
        ws_url += "/api/v4/websocket"

        logger.info("Connecting WebSocket...")

        try:
            # Use aiohttp for WebSocket with authentication
            headers = {"Authorization": f"Bearer {self.config.mattermost.token}"}
            async with self.session.ws_connect(ws_url, headers=headers) as websocket:
                self.websocket = websocket
                logger.info("WebSocket connected, listening for messages...")

                # Send authentication
                auth_message = {
                    "seq": 1,
                    "action": "authentication_challenge",
                    "data": {"token": self.config.mattermost.token},
                }
                await websocket.send_str(json.dumps(auth_message))

                async for msg in websocket:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                            await self._handle_websocket_message(data)
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid WebSocket message: {msg.data}")
                        except Exception as e:
                            logger.error(f"Error processing message: {e}")
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"WebSocket error: {websocket.exception()}")
                        break

        except aiohttp.ClientError as e:
            logger.error(f"WebSocket connection error: {e}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")

    async def _handle_websocket_message(self, data: dict[str, Any]):
        event = data.get("event")

        if event == "posted":
            post_data = data.get("data", {})
            post = post_data.get("post")

            if post:
                # Parse JSON from post if it's a string
                if isinstance(post, str):
                    post = json.loads(post)

                await self._handle_message(post)

    async def _handle_message(self, post: dict[str, Any]):
        try:
            user_id = post.get("user_id")
            if user_id == self.bot_user_id:
                return

            channel_id = post.get("channel_id")
            message_text = post.get("message", "")

            # Check if the message mentions the bot
            if not message_text.startswith(f"@{self.config.mattermost.bot_name}"):
                return

            # Get channel information
            async with self.session.get(
                f"{self.config.mattermost.url}/api/v4/channels/{channel_id}",
                headers=self.headers,
            ) as resp:
                if resp.status != 200:
                    return
                channel_info = await resp.json()
                channel_name = channel_info.get("name", "")

            if not self.config.mattermost.should_listen_to_channel(channel_name):
                return

            command = message_text.replace(
                f"@{self.config.mattermost.bot_name}", ""
            ).strip()
            logger.info(f"Command received in #{channel_name}: {command}")

            # Pass the original post data for create-issue command
            response = await self._process_command(command, channel_name, post)

            if response:
                # Send response in thread (reply to the original post)
                await self._send_threaded_message(channel_id, response, post)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def _process_command(
        self,
        command: str,
        channel_name: str,
        post_data: dict[str, Any] | None = None,
    ) -> str | None:
        command = command.lower().strip()

        if command == "help":
            return self._get_help_message()
        elif command == "status":
            return "🤖 Deputy Bot is operational!"
        elif command.startswith("bug"):
            return "🐛 Bug management feature under development..."
        elif command.startswith("create-issue"):
            return await self._handle_create_issue_command(
                command, channel_name, post_data
            )
        elif command.startswith("force-create-issue"):
            return await self._handle_create_issue_command(
                command, channel_name, post_data, force=True
            )
        elif command.startswith("sentry"):
            return await self._handle_sentry_command(command)
        elif command == "yes":
            return await self._handle_yes_command(post_data)
        elif command == "no":
            return await self._handle_no_command(post_data)
        elif command.startswith("issue"):
            return "📝 Issue creation feature under development..."
        else:
            return f"❓ Unknown command: `{command}`. Type `@{self.config.mattermost.bot_name} help` to see available commands."

    async def _send_message(self, channel_id: str, message: str):
        post_data = {"channel_id": channel_id, "message": message}

        async with self.session.post(
            f"{self.config.mattermost.url}/api/v4/posts",
            headers=self.headers,
            json=post_data,
        ) as resp:
            if resp.status != 201:
                logger.error(f"Error sending message: {resp.status}")

    async def _send_threaded_message(
        self, channel_id: str, message: str, original_post: dict[str, Any]
    ):
        """Send a message as a reply in the thread"""
        # Determine the root post ID for threading
        root_id = original_post.get("root_id") or original_post.get("id")

        post_data = {
            "channel_id": channel_id,
            "message": message,
            "root_id": root_id,  # This makes it a threaded reply
        }

        async with self.session.post(
            f"{self.config.mattermost.url}/api/v4/posts",
            headers=self.headers,
            json=post_data,
        ) as resp:
            if resp.status != 201:
                logger.error(f"Error sending threaded message: {resp.status}")
            else:
                logger.info(f"Sent threaded reply in channel {channel_id}")

    async def _handle_create_issue_command(
        self,
        command: str,
        channel_name: str,
        post_data: dict[str, Any] | None,
        force: bool = False,
    ) -> str:
        """Handle create-issue command"""

        # Check if services are available
        if not self.thread_analyzer:
            return "❌ Thread analysis not available - LLM not configured"

        if not self.github_integration:
            return "❌ GitHub integration not available - check configuration"

        if not post_data:
            return "❌ No post data available for analysis"

        try:
            # Extract thread root ID (post that started the thread)
            root_id = post_data.get("root_id") or post_data.get("id")
            channel_id = post_data.get("channel_id")

            logger.info(
                f"Post data: root_id={post_data.get('root_id')}, id={post_data.get('id')}, channel_id={channel_id}"
            )

            if not root_id:
                return "❌ Could not identify thread root"

            # Get thread messages
            logger.info(f"Analyzing thread {root_id} for issue creation")
            thread_messages = await self.thread_service.get_thread_messages(root_id)

            logger.info(f"Found {len(thread_messages)} messages in thread")
            if not thread_messages:
                return "❌ No messages found in thread"

            # Log first few messages for debugging
            for i, msg in enumerate(thread_messages[:3]):
                logger.info(f"Message {i}: {msg.user} - {msg.content[:100]}...")

            # Analyze thread with LLM
            logger.info("Starting LLM analysis...")
            analysis = await self.thread_analyzer.analyze_thread(thread_messages)

            logger.info(
                f"Analysis result: title='{analysis.suggested_title}', confidence={analysis.confidence_score}"
            )

            if analysis.confidence_score < 0.3:
                return f"⚠️ Low confidence analysis ({analysis.confidence_score:.2f}). Thread may not contain enough information for a good issue."

            # Create permalink to thread
            permalink = await self.thread_service.get_channel_permalink(
                channel_id, root_id
            )
            logger.info(f"Created permalink: {permalink}")

            # Create GitHub issue (with checks unless forced)
            if force:
                logger.info(
                    "Force creating GitHub issue (skipping similarity checks)..."
                )
            else:
                logger.info(
                    "Creating GitHub issue with similarity and Sentry checks..."
                )

            result = await self.github_integration.create_issue_from_analysis(
                analysis,
                permalink,
                thread_messages,
                self.sentry_integration,
                force_create=force,
            )

            # Handle similar issues found (only if not forced)
            if (
                not force
                and isinstance(result, dict)
                and result.get("type") == "similar_issues_found"
            ):
                # Store issue data for potential creation
                thread_id = root_id
                self.pending_issues[thread_id] = {
                    "analysis": result["analysis"],
                    "mattermost_link": result["mattermost_link"],
                    "thread_messages": result["thread_messages"],
                    "channel_id": channel_id,
                }

                warning = result["warning_message"]
                return warning

            # If we get here, issue was created successfully
            issue_url = result

            return f"""✅ **GitHub issue created successfully!**

**Issue:** [{analysis.suggested_title}]({issue_url})
**Type:** {analysis.issue_type.value}
**Priority:** {analysis.priority.value}
**Confidence:** {analysis.confidence_score:.2f}

The issue has been created with automatic analysis of the thread content."""

        except Exception as e:
            logger.error(f"Error creating issue: {e}")
            return f"❌ Failed to create issue: {str(e)}"

    async def _handle_sentry_command(self, command: str) -> str:
        """Handle Sentry-related commands"""
        if not self.sentry_integration:
            return "❌ Sentry integration not available - check configuration"

        try:
            # Parse command parts
            parts = command.strip().split()
            if len(parts) < 2:
                return self._get_sentry_help()

            subcommand = parts[1].lower()

            if subcommand == "top":
                # Handle: sentry top [period] [limit]
                period = (
                    parts[2] if len(parts) > 2 else self.config.sentry.default_period
                )
                limit = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 10

                issues = await self.sentry_integration.get_top_issues(period, limit)
                if not issues:
                    return f"📊 No issues found for period `{period}`"

                response = f"🔴 **Top {len(issues)} Sentry Issues ({period})**\n\n"
                for issue in issues:
                    response += (
                        self.sentry_integration.format_issue_summary(issue) + "\n\n"
                    )

                return response.strip()

            elif subcommand == "search":
                # Handle: sentry search [query] [period]
                if len(parts) < 3:
                    return "❌ Usage: `sentry search <query> [period]`"

                query = " ".join(parts[2:-1]) if len(parts) > 3 else parts[2]
                period = (
                    parts[-1]
                    if len(parts) > 3 and parts[-1] in ["24h", "7d"]
                    else "24h"
                )

                filters = SentrySearchFilter(query=query, period=period, limit=5)

                issues = await self.sentry_integration.search_issues(filters)
                if not issues:
                    return (
                        f"🔍 No issues found for query `{query}` in period `{period}`"
                    )

                response = f"🔍 **Sentry Search Results** (`{query}`, {period})\n\n"
                for issue in issues:
                    response += (
                        self.sentry_integration.format_issue_summary(issue) + "\n\n"
                    )

                return response.strip()

            elif subcommand == "stats":
                # Handle: sentry stats [period]
                period = (
                    parts[2] if len(parts) > 2 else self.config.sentry.default_period
                )

                stats = await self.sentry_integration.get_project_stats(period)

                return f"""📊 **Sentry Project Stats ({period})**

💥 **Total Events:** {stats.total_events:,}
🐛 **Total Issues:** {stats.total_issues}
✅ **Resolved Issues:** {stats.resolved_issues}
🆕 **New Issues:** {stats.new_issues}

**Top Issues:**
{chr(10).join(self.sentry_integration.format_issue_summary(issue) for issue in stats.top_issues[:3])}"""

            else:
                return self._get_sentry_help()

        except Exception as e:
            logger.error(f"Error handling Sentry command: {e}")
            return f"❌ Sentry command failed: {str(e)}"

    def _get_sentry_help(self) -> str:
        """Get Sentry command help"""
        return """🔴 **Sentry Commands:**

• `sentry top [period] [limit]` - Show top issues (default: 24h, 10 issues)
• `sentry search <query> [period]` - Search issues (default: 24h)
• `sentry stats [period]` - Show project statistics (default: 24h)

**Supported periods:** `24h`, `7d` only
**Examples:**
- `sentry top 24h 5` - Top 5 issues from last 24 hours
- `sentry top 7d 10` - Top 10 issues from last 7 days
- `sentry search "timeout" 24h` - Search for timeout errors in last 24h"""

    def _get_help_message(self) -> str:
        return """🤖 **Deputy Bot - Available Commands:**

• `help` - Display this help
• `status` - Check bot status
• `create-issue` - Create a GitHub issue from the current thread (checks for duplicates, respond with `yes` or `no` when prompted)
• `force-create-issue` - Force create issue even if similar ones exist
• `sentry top [24h|7d] [limit]` - Show top Sentry issues (periods: 24h, 7d only)
• `sentry search <query> [24h|7d]` - Search Sentry issues (periods: 24h, 7d only)
• `sentry stats [24h|7d]` - Show Sentry project statistics (periods: 24h, 7d only)
• `bug <description>` - Analyze and prioritize a bug (coming soon)
• `issue <description>` - Create a GitHub issue (coming soon)

**Listening on channels:** {channels}
""".format(channels=", ".join(self.config.mattermost.channels))

    async def _handle_yes_command(self, post_data: dict[str, Any] | None) -> str:
        """Handle yes command to confirm issue creation"""
        if not post_data:
            return "❌ No post data available"

        # Get thread ID
        thread_id = post_data.get("root_id") or post_data.get("id")
        if not thread_id:
            return "❌ Could not identify thread"

        # Check if we have pending issue data
        if thread_id not in self.pending_issues:
            return (
                "❌ No pending issue found for this thread. Use `create-issue` first."
            )

        try:
            # Retrieve pending issue data
            issue_data = self.pending_issues[thread_id]
            analysis = issue_data["analysis"]
            mattermost_link = issue_data["mattermost_link"]
            thread_messages = issue_data["thread_messages"]

            # Create the issue (forced)
            logger.info("Creating GitHub issue after user confirmation...")
            issue_url = await self.github_integration.create_issue_from_analysis(
                analysis,
                mattermost_link,
                thread_messages,
                self.sentry_integration,
                force_create=True,
            )

            # Clean up pending data
            del self.pending_issues[thread_id]

            return f"""✅ **GitHub issue created successfully!**

**Issue:** [{analysis.suggested_title}]({issue_url})
**Type:** {analysis.issue_type.value}
**Priority:** {analysis.priority.value}
**Confidence:** {analysis.confidence_score:.2f}

The issue has been created with automatic analysis of the thread content."""

        except Exception as e:
            # Clean up pending data on error
            if thread_id in self.pending_issues:
                del self.pending_issues[thread_id]
            logger.error(f"Error creating confirmed issue: {e}")
            return f"❌ Failed to create issue: {str(e)}"

    async def _handle_no_command(self, post_data: dict[str, Any] | None) -> str:
        """Handle no command to cancel issue creation"""
        if not post_data:
            return "❌ No post data available"

        # Get thread ID
        thread_id = post_data.get("root_id") or post_data.get("id")
        if not thread_id:
            return "❌ Could not identify thread"

        # Check if we have pending issue data
        if thread_id not in self.pending_issues:
            return "❌ No pending issue found for this thread."

        # Clean up pending data
        del self.pending_issues[thread_id]

        return "✅ Issue creation cancelled. No GitHub issue will be created."
