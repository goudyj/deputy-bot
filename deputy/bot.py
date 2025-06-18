import asyncio
import json
import logging
from typing import Any, Dict, Optional
import aiohttp
import websockets
from deputy.models.config import AppConfig

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
            "Content-Type": "application/json"
        }
        
    async def start(self):
        try:
            self.session = aiohttp.ClientSession()
            logger.info(f"Starting bot {self.config.mattermost.bot_name}...")
            
            await self._initialize()
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
            f"{self.config.mattermost.url}/api/v4/users/me",
            headers=self.headers
        ) as resp:
            if resp.status != 200:
                raise Exception(f"Error retrieving bot info: {resp.status}")
            me = await resp.json()
            self.bot_user_id = me["id"]
            logger.info(f"Bot user ID: {self.bot_user_id}")

        # Get team information
        async with self.session.get(
            f"{self.config.mattermost.url}/api/v4/teams/name/{self.config.mattermost.team_name}",
            headers=self.headers
        ) as resp:
            if resp.status == 200:
                team = await resp.json()
                self.team_id = team["id"]
                logger.info(f"Team ID: {self.team_id}")
            else:
                # Fallback: use the first available team
                logger.warning(f"Team '{self.config.mattermost.team_name}' not found, using first available team")
                async with self.session.get(
                    f"{self.config.mattermost.url}/api/v4/users/me/teams",
                    headers=self.headers
                ) as teams_resp:
                    if teams_resp.status == 200:
                        teams = await teams_resp.json()
                        if teams:
                            self.team_id = teams[0]["id"]
                            logger.info(f"Using team: {teams[0]['name']} (ID: {self.team_id})")
                        else:
                            raise Exception("No team available for the bot")
                    else:
                        raise Exception("Unable to retrieve teams")

    async def _start_websocket(self):
        ws_url = self.config.mattermost.url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url += f"/api/v4/websocket"
        
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
                    "data": {
                        "token": self.config.mattermost.token
                    }
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

    async def _handle_websocket_message(self, data: Dict[str, Any]):
        event = data.get("event")
        
        if event == "posted":
            post_data = data.get("data", {})
            post = post_data.get("post")
            
            if post:
                # Parse JSON from post if it's a string
                if isinstance(post, str):
                    post = json.loads(post)
                
                await self._handle_message(post)

    async def _handle_message(self, post: Dict[str, Any]):
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
                headers=self.headers
            ) as resp:
                if resp.status != 200:
                    return
                channel_info = await resp.json()
                channel_name = channel_info.get("name", "")
            
            if not self.config.mattermost.should_listen_to_channel(channel_name):
                return
            
            command = message_text.replace(f"@{self.config.mattermost.bot_name}", "").strip()
            logger.info(f"Command received in #{channel_name}: {command}")
            
            response = await self._process_command(command, channel_name)
            
            if response:
                await self._send_message(channel_id, response)
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def _process_command(self, command: str, channel_name: str) -> Optional[str]:
        command = command.lower().strip()
        
        if command == "help":
            return self._get_help_message()
        elif command == "status":
            return "🤖 Deputy Bot is operational!"
        elif command.startswith("bug"):
            return "🐛 Bug management feature under development..."
        elif command.startswith("issue"):
            return "📝 Issue creation feature under development..."
        else:
            return f"❓ Unknown command: `{command}`. Type `@{self.config.mattermost.bot_name} help` to see available commands."

    async def _send_message(self, channel_id: str, message: str):
        post_data = {
            "channel_id": channel_id,
            "message": message
        }
        
        async with self.session.post(
            f"{self.config.mattermost.url}/api/v4/posts",
            headers=self.headers,
            json=post_data
        ) as resp:
            if resp.status != 201:
                logger.error(f"Error sending message: {resp.status}")

    def _get_help_message(self) -> str:
        return """🤖 **Deputy Bot - Available Commands:**

• `help` - Display this help
• `status` - Check bot status
• `bug <description>` - Analyze and prioritize a bug (coming soon)
• `issue <description>` - Create a GitHub issue (coming soon)

**Listening on channels:** {channels}
""".format(channels=", ".join(self.config.mattermost.channels))