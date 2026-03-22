"""
Simple JSON-based persistent storage for user settings.
For production, swap with SQLite or Redis.
"""
import json
import os
from typing import Any, Dict

SETTINGS_FILE = "user_settings.json"


def _load() -> Dict[str, Any]:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}


def _save(data: Dict[str, Any]):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user_settings(user_id: int) -> Dict[str, Any]:
    data = _load()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "blur": 0,           # 0 = no blur, 1-10 = blur radius
            "blur_nsfw": False,  # Auto-blur NSFW content
            "source": "gelbooru",  # Default booru source
        }
    return data[uid]


def set_user_setting(user_id: int, key: str, value: Any):
    data = _load()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"blur": 0, "blur_nsfw": False, "source": "gelbooru"}
    data[uid][key] = value
    _save(data)
