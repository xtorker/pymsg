import asyncio
import json
import aiofiles
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from .client import HinatazakaClient
from .utils import normalize_message, get_media_extension, sanitize_name

class SyncManager:
    def __init__(self, client: HinatazakaClient, output_dir: Path):
        self.client = client
        self.output_dir = output_dir
        self.state_file = output_dir / "sync_state.json"
        self.sync_state = {}
        self.load_sync_state()

    def load_sync_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self.sync_state = json.load(f)
            except:
                self.sync_state = {}

    def save_sync_state(self):
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.sync_state, f, indent=2)
        except Exception as e:
            print(f"[Core] Failed to save sync state: {e}")

    def update_sync_state(self, group_id: int, member_id: int, last_msg_id: int, count: int):
        key = f"{group_id}_{member_id}"
        self.sync_state[key] = {
            "last_message_id": last_msg_id,
            "total_messages": count,
            "last_sync": datetime.utcnow().isoformat() + "Z"
        }
        self.save_sync_state()

    def get_last_id(self, group_id: int, member_id: int) -> Optional[int]:
        key = f"{group_id}_{member_id}"
        state = self.sync_state.get(key)
        if state:
            return state.get('last_message_id')
        return None

    async def sync_member(self, session, group: Dict[str, Any], member: Dict[str, Any], media_queue: List[Dict[str, Any]], progress_callback=None) -> int:
        """
        Syncs messages for a member.
        - Fetches new messages since last_id.
        - Updates messages.json (upsert).
        - Populates media_queue with new files to download.
        - Updates sync_state.
        
        Returns: Number of new messages processed.
        """
        gid = group['id']
        mid = member['id']
        gname = sanitize_name(group['name'])
        mname = sanitize_name(member['name'])
        
        group_dir = self.output_dir / f"{gid}_{gname}"
        member_dir = group_dir / f"{mid}_{mname}"
        member_dir.mkdir(parents=True, exist_ok=True)
        for t in ['picture', 'video', 'voice']: (member_dir / t).mkdir(exist_ok=True)
        
        last_id = self.get_last_id(gid, mid)
        print(f"[Core] Syncing {mname} ({mid}) Last ID: {last_id}")
        
        try:
            messages = await self.client.get_messages(session, gid, since_id=last_id, progress_callback=progress_callback)
            print(f"[Core] Fetched {len(messages)} raw messages for group {gid}")
            
            # Filter for member
            messages = [x for x in messages if x.get('member_id') == mid]
            print(f"[Core] Filtered to {len(messages)} for {mname}")
            
            if not messages:
                # Even if no new messages, ensure we don't crash and return 0
                return 0
                
            # Process & Prepare
            processed = self.prepare_messages(messages, member_dir, media_queue)
            
            # Load existing
            existing_file = member_dir / "messages.json"
            existing_msgs = []
            if existing_file.exists():
                try:
                    async with aiofiles.open(existing_file, 'r', encoding='utf-8') as f:
                        data = json.loads(await f.read())
                        existing_msgs = data.get('messages', [])
                except: pass
            
            # Dedupe (Upsert: Prefer new data)
            merged_dict = {x['id']: x for x in existing_msgs}
            for pm in processed:
                merged_dict[pm['id']] = pm
            
            merged = list(merged_dict.values())
            # Sort by timestamp (critical fix)
            merged.sort(key=lambda x: x.get('timestamp') or '')
            
            # Stats
            type_counts = {"text": 0, "video": 0, "picture": 0, "voice": 0}
            for msg in merged:
                mtype = msg.get('type', 'text')
                if mtype in type_counts:
                    type_counts[mtype] += 1
            
            # Save
            export_data = {
                "exported_at": datetime.utcnow().isoformat() + "Z",
                "member": {
                    "id": mid,
                    "name": mname,
                    "group_id": gid,
                    # Enrich with any extra fields passed in member dict
                    "portrait": member.get('portrait'),
                    "thumbnail": member.get('thumbnail'),
                    "phone_image": member.get('phone_image'),
                    "group_thumbnail": group.get('thumbnail'),
                    "is_active": group.get('subscription', {}).get('state') == 'active' 
                },
                "total_messages": len(merged),
                "message_type_counts": type_counts,
                "messages": merged
            }
            
            async with aiofiles.open(existing_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(export_data, ensure_ascii=False, indent=2))
                
            # Update State
            max_id = max(x['id'] for x in merged) if merged else (last_id or 0)
            self.update_sync_state(gid, mid, max_id, len(merged))
            
            return len(processed)
            
        except Exception as e:
            print(f"[Core] Error syncing {mname}: {e}")
            import traceback
            traceback.print_exc()
            return 0

    def prepare_messages(self, messages: List[Dict], member_dir: Path, queue: List[Dict]) -> List[Dict]:
        processed = []
        for msg in messages:
            try:
                # Normalize core fields
                p_msg = normalize_message(msg)
                msg_type = p_msg['type']
                raw_type = p_msg.pop('_raw_type', 'text') # Remove internal helper field
                
                # Media
                media_url = msg.get('file') or msg.get('thumbnail')
                if media_url:
                    ext = get_media_extension(media_url, raw_type)
                    
                    subdir = 'other'
                    if msg_type == 'picture': subdir = 'picture'
                    elif msg_type == 'video': subdir = 'video'
                    elif msg_type == 'voice': subdir = 'voice'
                    
                    filepath = member_dir / subdir / f"{msg['id']}.{ext}"
                    
                    # Logic: If file doesn't exist, queue it.
                    if not filepath.exists():
                        queue.append({
                            'url': media_url, 
                            'path': filepath, 
                            'timestamp': msg.get('published_at')
                        })
                    
                    p_msg['media_file'] = str(filepath.relative_to(self.output_dir))
                
                processed.append(p_msg)
            except Exception as e:
                print(f"[Core] Prepare error for msg {msg.get('id')}: {e}")
        return processed

    async def process_media_queue(self, session, queue: List[Dict], concurrency: int = 5, progress_callback=None):
        """
        Downloads files in the queue using a semaphore for concurrency.
        """
        if not queue:
            return

        sem = asyncio.Semaphore(concurrency)
        total = len(queue)
        completed = 0

        async def worker(item):
            nonlocal completed
            async with sem:
                res = await self.client.download_file(
                    session, 
                    item['url'], 
                    item['path'], 
                    item['timestamp']
                )
                if res:
                    completed += 1
                    if progress_callback:
                        await progress_callback(completed, total)

        await asyncio.gather(*[worker(item) for item in queue])
