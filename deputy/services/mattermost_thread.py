import logging
from typing import List, Optional
import aiohttp
from deputy.models.issue import ThreadMessage

logger = logging.getLogger(__name__)


class MattermostThreadService:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, headers: dict):
        self.session = session
        self.base_url = base_url
        self.headers = headers
    
    async def get_thread_messages(
        self, 
        post_id: str, 
        limit: int = 50
    ) -> List[ThreadMessage]:
        """Get all messages in a thread starting from a root post"""
        try:
            # Get the root post first
            root_post = await self._get_post(post_id)
            if not root_post:
                return []
            
            # Get thread messages
            thread_url = f"{self.base_url}/api/v4/posts/{post_id}/thread"
            async with self.session.get(thread_url, headers=self.headers) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to get thread: {resp.status}")
                    return []
                
                thread_data = await resp.json()
                posts = thread_data.get("posts", {})
                order = thread_data.get("order", [])
                
                messages = []
                for post_id in order:
                    post = posts.get(post_id)
                    if post:
                        # Get user info
                        user_info = await self._get_user_info(post.get("user_id"))
                        username = user_info.get("username", "Unknown") if user_info else "Unknown"
                        
                        # Get file attachments
                        attachments = await self._get_post_attachments(post.get("id"))
                        
                        message = ThreadMessage(
                            user=username,
                            content=post.get("message", ""),
                            timestamp=str(post.get("create_at", "")),
                            attachments=attachments
                        )
                        messages.append(message)
                
                return messages
                
        except Exception as e:
            logger.error(f"Error getting thread messages: {e}")
            return []
    
    async def _get_post(self, post_id: str) -> Optional[dict]:
        """Get a single post by ID"""
        try:
            async with self.session.get(
                f"{self.base_url}/api/v4/posts/{post_id}",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception as e:
            logger.error(f"Error getting post {post_id}: {e}")
            return None
    
    async def _get_user_info(self, user_id: str) -> Optional[dict]:
        """Get user information by ID"""
        try:
            async with self.session.get(
                f"{self.base_url}/api/v4/users/{user_id}",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def _get_post_attachments(self, post_id: str) -> List[str]:
        """Get file attachments for a post"""
        try:
            # Get post file attachments
            async with self.session.get(
                f"{self.base_url}/api/v4/posts/{post_id}/files/info",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    files = await resp.json()
                    attachment_urls = []
                    
                    for file_info in files:
                        file_id = file_info.get("id")
                        if file_id:
                            # Create public file URL
                            file_url = f"{self.base_url}/api/v4/files/{file_id}"
                            attachment_urls.append(file_url)
                    
                    return attachment_urls
                return []
        except Exception as e:
            logger.error(f"Error getting attachments for post {post_id}: {e}")
            return []
    
    async def get_channel_permalink(self, channel_id: str, post_id: str) -> Optional[str]:
        """Get a permalink to a specific post in a channel"""
        try:
            # Get channel info to build the permalink
            async with self.session.get(
                f"{self.base_url}/api/v4/channels/{channel_id}",
                headers=self.headers
            ) as resp:
                if resp.status == 200:
                    channel_info = await resp.json()
                    team_id = channel_info.get("team_id")
                    channel_name = channel_info.get("name")
                    
                    if team_id and channel_name:
                        # Get team info
                        async with self.session.get(
                            f"{self.base_url}/api/v4/teams/{team_id}",
                            headers=self.headers
                        ) as team_resp:
                            if team_resp.status == 200:
                                team_info = await team_resp.json()
                                team_name = team_info.get("name")
                                
                                if team_name:
                                    return f"{self.base_url}/{team_name}/channels/{channel_name}/{post_id}"
                
                return None
        except Exception as e:
            logger.error(f"Error creating permalink: {e}")
            return None