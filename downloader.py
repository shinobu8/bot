import asyncio
import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple
import re
import httpx

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


async def get_video_dimensions(filepath: str) -> Tuple[int, int]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            filepath,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
        out = stdout.decode().strip()
        if out:
            parts = out.split(",")
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    except Exception as e:
        logger.warning("ffprobe error: %s", e)
    return 0, 0


async def download_tiktok(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Скачиваем TikTok через tikwm API — поддерживает видео и фото-коллажи."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            r = await client.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": 1},
            )
            r.raise_for_status()
            data = r.json()
            logger.info("TikWM code: %s", data.get("code"))

            if data.get("code") != 0:
                return None, None  # фолбэк на yt-dlp

            video_data = data.get("data", {})
            tmpdir = tempfile.mkdtemp(prefix="tgbot_")
            filepaths = []

            # Фото-коллаж
            images = video_data.get("images", [])
            if images:
                for i, img_url in enumerate(images[:10]):
                    if not img_url:
                        continue
                    ext = img_url.split(".")[-1].split("?")[0]
                    if ext not in {"jpg", "jpeg", "png", "webp"}:
                        ext = "jpg"
                    filepath = os.path.join(tmpdir, f"tiktok_photo_{i}.{ext}")
                    async with client.stream("GET", img_url) as resp:
                        if resp.status_code == 200:
                            with open(filepath, "wb") as f:
                                async for chunk in resp.aiter_bytes(chunk_size=8192):
                                    f.write(chunk)
                            filepaths.append(filepath)
                if filepaths:
                    return "|||".join(filepaths), None

            # Видео
            video_url = video_data.get("hdplay") or video_data.get("play")
            if video_url:
                filepath = os.path.join(tmpdir, "tiktok.mp4")
                async with client.stream("GET", video_url) as resp:
                    if resp.status_code == 200:
                        with open(filepath, "wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size=8192):
                                f.write(chunk)
                        return filepath, None

            return None, None  # фолбэк на yt-dlp

    except Exception as e:
        logger.error("TikTok API error: %s", e)
        return None, None  # фолбэк на yt-dlp


async def download_twitter_via_sss(url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        tweet_id = re.search(r"status/(\d+)", url)
        if not tweet_id:
            return None, "Не удалось определить ID твита."
        tid = tweet_id.group(1)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            r = await client.get(f"https://api.fxtwitter.com/status/{tid}")
            r.raise_for_status()
            data = r.json()

            tweet = data.get("tweet", {})
            media_list = tweet.get("media", {})

            videos = media_list.get("videos", [])
            photos = media_list.get("photos", [])
            gifs = media_list.get("gifs", [])

            all_media = []
            for video in videos:
                best = max([video], key=lambda v: v.get("width", 0))
                all_media.append({"url": best.get("url"), "ext": "mp4"})
            for gif in gifs:
                all_media.append({"url": gif.get("url"), "ext": "mp4"})
            for photo in photos:
                all_media.append({"url": photo.get("url"), "ext": "jpg"})

            if not all_media:
                return None, "В твите нет медиа (фото/видео/гифки)."

            tmpdir = tempfile.mkdtemp(prefix="tgbot_")
            filepaths = []

            for i, media in enumerate(all_media):
                filepath = os.path.join(tmpdir, f"twitter_media_{i}.{media['ext']}")
                async with client.stream("GET", media["url"]) as resp:
                    resp.raise_for_status()
                    with open(filepath, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                filepaths.append(filepath)

            return "|||".join(filepaths), None

    except Exception as e:
        logger.error("fxtwitter error: %s", e)
        return None, f"Ошибка: {e}"


async def download_reddit(url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        from RedDownloader import RedDownloader

        if "/s/" in url:
            return None, (
                "⚠️ Короткие ссылки Reddit не поддерживаются.\n\n"
                "Открой пост в браузере и скопируй полную ссылку вида:\n"
                "<code>https://reddit.com/r/название/comments/xxxxx/...</code>"
            )

        resolved = url.split("?")[0].rstrip("/")
        tmpdir = tempfile.mkdtemp(prefix="tgbot_")

        def _download():
            try:
                old_dir = os.getcwd()
                os.chdir(tmpdir)
                data = RedDownloader.Download(resolved, quality=720)
                os.chdir(old_dir)
                return data
            except Exception as e:
                return str(e)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _download)

        if isinstance(result, str):
            return None, f"Ошибка: {result}"

        all_files = []
        for ext in ["*.mp4", "*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp"]:
            all_files.extend(Path(tmpdir).rglob(ext))

        if not all_files:
            return None, "Не удалось скачать медиа."

        return "|||".join(str(f) for f in all_files), None

    except Exception as e:
        logger.error("Reddit download error: %s", e)
        return None, f"Ошибка Reddit: {e}"


async def download_pixiv(url: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        artwork_id = re.search(r"artworks/(\d+)", url)
        if not artwork_id:
            return None, "Не удалось определить ID арта Pixiv."
        aid = artwork_id.group(1)

        pixiv_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.pixiv.net/",
        }

        async with httpx.AsyncClient(timeout=60, headers=pixiv_headers, follow_redirects=True) as client:
            r = await client.get(f"https://phixiv.net/api/info?id={aid}&language=en")
            r.raise_for_status()
            data = r.json()

            image_urls = data.get("image_proxy_urls") or data.get("image_urls") or []

            if not image_urls:
                return None, "Phixiv не вернул изображения для этого арта."

            tmpdir = tempfile.mkdtemp(prefix="tgbot_")
            filepaths = []

            for i, img_url in enumerate(image_urls[:10]):
                ext = img_url.split(".")[-1].split("?")[0]
                if ext not in {"jpg", "jpeg", "png", "gif", "webp", "mp4"}:
                    ext = "jpg"
                filepath = os.path.join(tmpdir, f"pixiv_{i}.{ext}")

                async with client.stream("GET", img_url) as resp:
                    if resp.status_code == 200:
                        with open(filepath, "wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size=8192):
                                f.write(chunk)
                        filepaths.append(filepath)

            if not filepaths:
                return None, "Не удалось скачать изображения с Pixiv."

            return "|||".join(filepaths), None

    except Exception as e:
        logger.error("Pixiv download error: %s", e)
        return None, f"Ошибка Pixiv: {e}"


async def download_media(
    url: str,
    quality: str = "best",
    audio_only: bool = False,
    proxy: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    tmpdir = tempfile.mkdtemp(prefix="tgbot_")
    output_template = os.path.join(tmpdir, "%(title).50s.%(ext)s")

    platform = detect_platform(url)

    if platform == "twitter" and not audio_only:
        return await download_twitter_via_sss(url)

    if platform == "tiktok" and not audio_only:
        result, error = await download_tiktok(url)
        if result:
            return result, None
        # фолбэк на yt-dlp если tikwm не сработал

    if platform == "reddit" and not audio_only:
        return await download_reddit(url)

    if platform == "pixiv" and not audio_only:
        return await download_pixiv(url)

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
            "--embed-metadata",
            "--postprocessor-args", "ffmpeg:-movflags +faststart",
        ]

    if platform == "instagram":
        cmd += ["--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"]

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
