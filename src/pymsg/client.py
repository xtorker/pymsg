import asyncio
import aiohttp
import aiofiles
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from .utils import get_media_extension, sanitize_name

API_BASE = "https://api.message.hinatazaka46.com/v2"
APP_ID = "jp.co.sonymusic.communication.keyakizaka 2.5"

class HinatazakaClient:
    """
    Async client for the Hinatazaka46 Message API.
    
    Provides methods to authenticate, explore groups/members, and fetch messages.
    Handles token refresh automatically via cookies if available.
    
    Attributes:
        access_token (str): Current OAuth2 access token.
        refresh_token (str): OAuth2 refresh token.
        cookies (dict): Session cookies used for token refreshing.
    """
    
    def __init__(self, access_token: str = None, refresh_token: str = None, cookies: Optional[Dict[str, str]] = None, app_id: str = None, user_agent: str = None):
        """
        Initialize the client.

        Args:
            access_token: The Bearer token for API authentication.
            refresh_token: The Refresh token (if available).
            cookies: Dictionary of browser cookies ("key": "value"), required for refreshing access tokens.
            app_id: The X-Talk-App-ID header value (optional, defaults to hardcoded).
            user_agent: The User-Agent header value (optional, defaults to hardcoded).
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.cookies = cookies
        self.user_agent = user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        self.app_id = app_id or APP_ID
        
        self.headers = {
            "x-talk-app-id": self.app_id,
            "user-agent": self.user_agent,
            "content-type": "application/json"
        }
        if self.access_token:
            self.headers["Authorization"] = f"Bearer {self.access_token}"

    async def update_token(self, new_token: str) -> None:
        """
        Update the instance's access token and headers.
        
        Args:
            new_token: The new Bearer token string.
        """
        self.access_token = new_token
        self.headers["Authorization"] = f"Bearer {new_token}"

    async def fetch_json(self, session: aiohttp.ClientSession, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        Raw JSON fetch helper.
        
        Args:
            session: Active aiohttp ClientSession.
            endpoint: API endpoint path (e.g. "/groups").
            params: Query parameters.

        Returns:
            JSON response as dict or None if failed/unauthorized.
        """
        url = f"{API_BASE}{endpoint}"
        try:
            async with session.get(url, headers=self.headers, params=params, ssl=False) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 401:
                    # Token expired
                    return None
        except Exception:
            pass
        return None

    async def refresh_access_token(self, session: aiohttp.ClientSession) -> bool:
        """
        Attempt to refresh the access token using stored cookies.
        
        Args:
            session: Active aiohttp ClientSession.

        Returns:
            True if refresh was successful, False otherwise.
        """
        if self.cookies:
            try:
                # Cookie based refresh call
                # Note: This mimics the browser behavior where hitting the app
                # with valid cookies yields a new token exchange.
                async with session.post(f"{API_BASE}/update_token", headers=self.headers, json={}, ssl=False) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        new_token = data.get('access_token')
                        if new_token:
                            await self.update_token(new_token)
                            return True
            except:
                pass
        return False

    async def get_groups(self, session: aiohttp.ClientSession, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch all subscribed groups (artists).

        Args:
            session: Active aiohttp ClientSession.
            include_inactive: If True, includes expired/suspended subscriptions.

        Returns:
            List of group objects.
        """
        groups = await self.fetch_json(session, "/groups", {"organization_id": 1})
        if not groups:
            return []
            
        filtered = []
        for g in groups:
            sub = g.get('subscription')
            if sub:
                state = sub.get('state')
                if state == 'active' or (include_inactive and state in ['expired', 'suspended', 'canceled']):
                    filtered.append(g)
        return filtered

    async def get_members(self, session: aiohttp.ClientSession, group_id: int) -> List[Dict[str, Any]]:
        """
        Fetch all members (timelines) within a group.
        
        Args:
            session: Active aiohttp ClientSession.
            group_id: The ID of the group/artist.

        Returns:
            List of member objects.
        """
        result = await self.fetch_json(session, f"/groups/{group_id}/members")
        return result or []

    async def get_messages(self, session: aiohttp.ClientSession, group_id: int, since_id: Optional[int] = None, max_id: Optional[int] = None, progress_callback=None) -> List[Dict[str, Any]]:
        """
        Fetch all new messages from a group's timeline.
        Automatically handles pagination to retrieve all messages newer than `since_id`.

        Args:
            session: Active aiohttp ClientSession.
            group_id: The ID of the group/artist.
            since_id: The message ID to start fetching from (exclusive). 
                      If None, fetches widely recent history (limited by API/loop).
            max_id: Ignored by API, kept for compatibility.
            progress_callback: Optional async function(date_str, count) to call on each page.

        Returns:
            List of message objects sorted by ID ascending.
        """
        all_messages = {}
        page = 0
        current_continuation = None
        
        while True:
            params = {
                "count": 200,
                "order": "desc"
            }
            if current_continuation:
                params["continuation"] = current_continuation
            
            # Pass max_id if provided (for first page usually, or if API supports it natively in params)
            # Reverse engineering assumption: API supports 'max_id' or similar. 
            # Or we filter client side? 
            # If we want *older* messages, we usually page *backwards*.
            # But here `order=desc` gives newest first.
            # If we provide `max_id`, API should return messages with ID < max_id.
            if max_id and page == 0 and not current_continuation:
                params["max_id"] = max_id
            
            data = await self.fetch_json(session, f"/groups/{group_id}/timeline", params)
            if not data:
                # Try refresh on first fail?
                if page == 0 and await self.refresh_access_token(session):
                    continue
                break
            
            messages = data.get('messages', [])
            if not messages:
                break
            
            # Add to collection
            reached_since_id = False
            for m in messages:
                msg_id = m['id']
                if since_id and msg_id <= since_id:
                    # We reached the point we synced up to last time
                    reached_since_id = True
                    break
                
                # Always add if not present (idempotent)
                all_messages[msg_id] = m
            
            if progress_callback and messages:
                oldest_in_batch = messages[-1].get('published_at')
                await progress_callback(oldest_in_batch, len(all_messages))

            if reached_since_id:
                break

            # Pagination
            current_continuation = data.get('continuation')
            if not current_continuation:
                break
            
            # Safety: Infinite loop check (API returning same cursor)
            if current_continuation == params.get("continuation"):
                break
                
            page += 1
            await asyncio.sleep(0.5)
            
        # Return sorted list
        return sorted(list(all_messages.values()), key=lambda x: x['id'])

    async def download_file(self, session: aiohttp.ClientSession, url: str, filepath: Path, timestamp: Optional[str] = None) -> bool:
        """
        Download a file from a URL to the local filesystem.

        Args:
            session: Active aiohttp ClientSession.
            url: The download URL.
            filepath: Destination Path object.
            timestamp: Optional ISO timestamp to set the file's modification time.

        Returns:
            True if successful or already exists, False on failure.
        """
        if not url or filepath.exists():
            return True
            
        try:
            # Create parent dirs if needed
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            async with session.get(url, ssl=False) as resp:
                if resp.status == 200:
                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(await resp.read())
                    # Set timestamp
                    if timestamp:
                        # TODO: Set mtime/atime if critical, skipping for now to keep lightweight
                        pass
                    return True
        except:
            pass
        return False

    async def download_message_media(self, session: aiohttp.ClientSession, message: Dict[str, Any], output_dir: Path) -> Optional[Path]:
        """
        Download media associated with a message to the specified directory.
        Organizes files into subdirectories by type (picture, video, voice).
        
        Args:
            session: Active aiohttp session.
            message: Message dictionary from API.
            output_dir: Root directory for the member (files will be in type subdirs).
            
        Returns:
            Path to the downloaded file, or None if no media/download failed.
        """
        raw_type = message.get('type')
        msg_type = 'text'
        if raw_type in ['image', 'picture']: msg_type = 'picture'
        elif raw_type in ['video', 'movie']: msg_type = 'video'
        elif raw_type == 'voice': msg_type = 'voice'
        
        media_url = message.get('file') or message.get('thumbnail')
        if not media_url or msg_type == 'text':
            return None
            
        try:
            ext = get_media_extension(media_url, raw_type)
            target_dir = output_dir / msg_type
            target_dir.mkdir(parents=True, exist_ok=True)
            
            filename = f"{message['id']}.{ext}"
            filepath = target_dir / filename
            
            if await self.download_file(session, media_url, filepath):
                return filepath
        except Exception as e:
            # print(f"Download error: {e}")
            pass
            
        return None
