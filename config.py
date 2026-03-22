import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    BOT_TOKEN: str = ""
    # Optional: proxy for yt-dlp if needed
    PROXY: Optional[str] = None
    # Blur strength default (0 = no blur)
    DEFAULT_BLUR: int = 0
    # Max arts per /search command
    MAX_ARTS: int = 5
    # Gelbooru API (free, no key needed for basic use)
    GELBOORU_API_URL: str = "https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1"
    RULE34_API_URL: str = "https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&json=1"
    # Flibusta mirror
    FLIBUSTA_URL: str = "https://flibusta.is"
    FLIBUSTA_TOR_URL: str = "http://flibustahezeous3.onion"

    @classmethod
    def load(cls) -> "Config":
        return cls(
            BOT_TOKEN=os.environ["BOT_TOKEN"],
            PROXY=os.getenv("PROXY"),
            DEFAULT_BLUR=int(os.getenv("DEFAULT_BLUR", "0")),
        )
