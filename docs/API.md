# pymsg API Reference

## Authentication
### `BrowserAuth`
Handles login via Playwright.

#### `login(headless: bool = False) -> dict`
- **headless**: Run browser in background?
- **Returns**: Dictionary with `access_token` and `cookies`.

## Client
### `HinatazakaClient`
Main API wrapper.

#### `__init__(access_token: str, refresh_token: str = None, cookies: dict = None)`
Initialize connection.

#### `get_groups(session: aiohttp.ClientSession, include_inactive: bool = False) -> List[dict]`
- **session**: Active aiohttp session.
- **include_inactive**: If True, returns `expired` and `suspended` subscriptions too.
- **Returns**: List of group objects.

#### `get_members(session, group_id: int) -> List[dict]`
- **group_id**: Target group ID.
- **Returns**: List of member objects.

#### `get_messages(session, group_id: int, since_id: int = None) -> List[dict]`
- **group_id**: Target group ID.
- **since_id**: (Optional) Only fetch messages newer than this ID.
- **Returns**: List of message objects (sorted).

#### `download_file(session, url: str, filepath: Path, timestamp: str) -> bool`
- **url**: Signed media URL.
- **filepath**: Local destination path.
- **timestamp**: ISO timestamp to set file modification time.
- **Returns**: True if success/exists.
