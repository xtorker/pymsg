from urllib.parse import urlparse

MEDIA_EXTENSIONS = {
    'image': 'jpg', 'picture': 'jpg', 
    'voice': 'm4a', 
    'movie': 'mp4', 'video': 'mp4'
}

def sanitize_name(name: str) -> str:
    """Sanitize directory names."""
    return name.replace(' ', '_').replace('/', '_').strip()

def get_media_extension(url: str, msg_type: str) -> str:
    """Determine file extension from URL or fallback to type default."""
    if url:
        parsed = urlparse(url)
        path = parsed.path
        if '.' in path:
            ext = path.split('.')[-1].lower()
            if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'm4a', 'mp3', 'wav', 'mp4', 'mov', 'webm']:
                return ext
    return MEDIA_EXTENSIONS.get(msg_type, 'bin')

def normalize_message(msg: dict) -> dict:
    """
    Normalizes a raw API message into the standard export format.
    Handles type mapping (image->picture, movie->video) and field selection.
    """
    # Map type to spec: text, video, picture, voice
    raw_type = msg.get('type')
    msg_type = 'text'
    if raw_type in ['image', 'picture']: msg_type = 'picture'
    elif raw_type in ['video', 'movie']: msg_type = 'video'
    elif raw_type in ['voice']: msg_type = 'voice'
    
    return {
        "id": msg['id'],
        "timestamp": msg.get('published_at'), # ISO string from API
        "type": msg_type,
        "is_favorite": msg.get('is_favorite', False),
        "content": msg.get('text'),
        # raw type useful for extension determination later
        "_raw_type": raw_type
    }
