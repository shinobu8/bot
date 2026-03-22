import asyncio
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
import re

logger = logging.getLogger(__name__)

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
    tmpdir = tempfile.mkdtemp(prefix="tgbot_")
    output_template = os.path.join(tmpdir, "%(title).50s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--max-filesize", "50m",
        "-o", output_template,
    ]

    if proxy:
        cmd += ["--proxy", proxy]

    if audio_only:
        cmd += ["-x", "--audio-format", "mp3"]
    else:
        cmd += [
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
        ]

    platform = detect_platform(url)

    if platform == "instagram":
        cmd += ["--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"]

    if platform == "pixiv":
        cmd += ["--add-header", "Referer:https://www.pixiv.net/"]

    if platform == "twitter":
        cmd += ["--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"]
        cmd += ["--extractor-args", "twitter:api=graphql"]

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

        files = list(Path(tmpdir).iterdir())
        if not files:
            return None, "Файл не найден после загрузки."

        target = max(files, key=lambda f: f.stat().st_size)
        return str(target), None

    except asyncio.TimeoutError:
        return None, "Превышено время ожидания (5 минут)."
    except Exception as e:
        logger.exception("Download error")
        return None, str(e)


def _friendly_error(stderr: str) -> str:
    if "This video is private" in stderr:
        return "Видео приватное — не могу скачать."
    if "age-restricted" in stderr or "Sign in to confirm your age" in stderr:
        return "Видео с возрастным ограничением."
    if "Unable to extract" in stderr or "Unsupported URL" in stderr:
        return "Не удалось распознать ссылку."
    if "File is larger than max-filesize" in stderr:
        return "Файл больше 50 МБ."
    if "HTTP Error 429" in stderr:
        return "Слишком много запросов. Подожди немного."
    if "HTTP Error 404" in stderr:
        return "Контент не найден (404)."
    return "Ошибка загрузки. Возможно, контент удалён или закрыт."


async def cleanup_file(filepath: str):
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
