"""
Media downloader using yt-dlp for YouTube, TikTok, Instagram, Twitter/X, Reddit, Pixiv.
"""
import asyncio
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
import re

logger = logging.getLogger(__name__)

# Supported URL patterns
YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be)")
TIKTOK_RE = re.compile(r"tiktok\.com")
INSTAGRAM_RE = re.compile(r"instagram\.com")
TWITTER_RE = re.compile(r"(twitter\.com|x\.com)")
REDDIT_RE = re.compile(r"reddit\.com")
PIXIV_RE = re.compile(r"pixiv\.net")


def detect_platform(url: str) -> Optional[str]:
    if YOUTUBE_RE.search(url):
        return "youtube"
    if TIKTOK_RE.search(url):
        return "tiktok"
    if INSTAGRAM_RE.search(url):
        return "instagram"
    if TWITTER_RE.search(url):
        return "twitter"
    if REDDIT_RE.search(url):
        return "reddit"
    if PIXIV_RE.search(url):
        return "pixiv"
    return None


async def download_media(
    url: str,
    quality: str = "best",
    audio_only: bool = False,
    proxy: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Download media from URL using yt-dlp.
    Returns (filepath, error_message).
    """
    tmpdir = tempfile.mkdtemp(prefix="tgbot_")
    output_template = os.path.join(tmpdir, "%(title).50s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--max-filesize", "50m",   # Telegram bot limit
        "-o", output_template,
    ]

    if proxy:
        cmd += ["--proxy", proxy]

    if audio_only:
        cmd += ["-x", "--audio-format", "mp3"]
    else:
        # Prefer mp4 for compatibility
        cmd += [
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
        ]

    # Instagram: cookies sometimes needed; try without first
    platform = detect_platform(url)
    if platform == "instagram":
        cmd += ["--add-header", "User-Agent:Mozilla/5.0"]
    if platform == "pixiv":
        cmd += ["--add-header", "Referer:https://www.pixiv.net/"]

    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")
            logger.error("yt-dlp error: %s", err)
            return None, _friendly_error(err)

        # Find downloaded file
        files = list(Path(tmpdir).iterdir())
        if not files:
            return None, "Файл не найден после загрузки."
        
        # Return the largest file (in case of multiple)
        target = max(files, key=lambda f: f.stat().st_size)
        return str(target), None

    except asyncio.TimeoutError:
        return None, "Превышено время ожидания (5 минут). Попробуй другую ссылку."
    except Exception as e:
        logger.exception("Download error")
        return None, str(e)


def _friendly_error(stderr: str) -> str:
    if "This video is private" in stderr:
        return "Видео приватное — не могу скачать."
    if "This video is age-restricted" in stderr or "Sign in to confirm your age" in stderr:
        return "Видео с возрастным ограничением. Нужны куки (cookies)."
    if "Unable to extract" in stderr or "Unsupported URL" in stderr:
        return "Не удалось распознать ссылку. Проверь URL."
    if "File is larger than max-filesize" in stderr:
        return "Файл больше 50 МБ — Telegram не пропустит такой файл."
    if "HTTP Error 429" in stderr:
        return "Слишком много запросов. Подожди немного."
    if "HTTP Error 404" in stderr:
        return "Контент не найден (404)."
    return "Ошибка загрузки. Возможно, контент удалён или закрыт."


async def cleanup_file(filepath: str):
    """Remove temp file and its directory."""
    try:
        path = Path(filepath)
        if path.exists():
            path.unlink()
        parent = path.parent
        if parent.exists() and str(parent).startswith(tempfile.gettempdir()):
            import shutil
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:
        pass
