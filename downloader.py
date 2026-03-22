import asyncio
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
import re
import httpx
from bs4 import BeautifulSoup

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


async def download_twitter_via_sss(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Скачиваем Twitter медиа через fxtwitter API"""
    try:
        # Извлекаем ID твита
        tweet_id = re.search(r"status/(\d+)", url)
        if not tweet_id:
            return None, "Не удалось определить ID твита."
        tid = tweet_id.group(1)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            # fxtwitter отдаёт JSON с медиа
            r = await client.get(f"https://api.fxtwitter.com/status/{tid}")
            r.raise_for_status()
            data = r.json()

            tweet = data.get("tweet", {})
            media_list = tweet.get("media", {})

            # Ищем видео
            videos = media_list.get("videos", [])
            photos = media_list.get("photos", [])
            gifs = media_list.get("gifs", [])

            media_url = None
            ext = "mp4"

            if videos:
                # Берём наилучшее качество
                best = max(videos, key=lambda v: v.get("width", 0))
                media_url = best.get("url")
                ext = "mp4"
            elif gifs:
                media_url = gifs[0].get("url")
                ext = "mp4"
            elif photos:
                media_url = photos[0].get("url")
                ext = "jpg"

            if not media_url:
                return None, "В твите нет медиа (фото/видео/гифки)."

            # Скачиваем файл
            tmpdir = tempfile.mkdtemp(prefix="tgbot_")
            filepath = os.path.join(tmpdir, f"twitter_media.{ext}")

            async with client.stream("GET", media_url) as resp:
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

            return filepath, None

    except Exception as e:
        logger.error("fxtwitter error: %s", e)
        return None, f"Ошибка: {e}"


async def download_media(
    url: str,
    quality: str = "best",
    audio_only: bool = False,
    proxy: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    tmpdir = tempfile.mkdtemp(prefix="tgbot_")
    output_template = os.path.join(tmpdir, "%(title).50s.%(ext)s")

    platform = detect_platform(url)

    # Twitter — используем ssstwitter
    if platform == "twitter" and not audio_only:
        return await download_twitter_via_sss(url)

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

    if platform == "instagram":
        cmd += ["--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"]

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
