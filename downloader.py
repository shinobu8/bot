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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            # Шаг 1: получаем страницу redvid.io и вытаскиваем токен
            r = await client.get(
                "https://redvid.io/",
                params={"url": url},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://redvid.io/",
                }
            )
            logger.info("Redvid page status: %s", r.status_code)

            soup = BeautifulSoup(r.text, "html.parser")

            # Ищем токен в форме или скриптах
            token = None
            for inp in soup.find_all("input", {"name": ["token", "_token", "download_token", "t"]}):
                token = inp.get("value")
                if token:
                    break

            # Ищем прямые ссылки на видео/фото в HTML
            media_urls = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if any(x in href for x in ["v.redd.it", "i.redd.it", ".mp4", "preview.redd.it"]):
                    media_urls.append(href)

            # Ищем в тегах video/img
            for tag in soup.find_all(["video", "source"]):
                src = tag.get("src") or tag.get("data-src")
                if src and src.startswith("http"):
                    media_urls.append(src)

            logger.info("Token: %s, Direct links: %s", token, media_urls)

            # Шаг 2: если нашли токен — запрашиваем скачку
            if token and not media_urls:
                r2 = await client.get(
                    "https://redvid.io/download",
                    params={"token": token},
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": "https://redvid.io/",
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    }
                )
                logger.info("Redvid download status: %s ct: %s body: %s", r2.status_code, r2.headers.get("content-type"), r2.text[:300])
                if r2.status_code == 200:
                    try:
                        data = r2.json()
                        for key in ["url", "video", "hd", "sd", "link"]:
                            val = data.get(key)
                            if isinstance(val, str) and val.startswith("http"):
                                media_urls.append(val)
                    except Exception:
                        soup2 = BeautifulSoup(r2.text, "html.parser")
                        for a in soup2.find_all("a", href=True):
                            if any(x in a["href"] for x in [".mp4", "v.redd.it", "i.redd.it"]):
                                media_urls.append(a["href"])

            logger.info("Final media urls: %s", media_urls)

            tmpdir = tempfile.mkdtemp(prefix="tgbot_")
            filepaths = []

            for i, media_url in enumerate(media_urls[:10]):
                if not media_url or not media_url.startswith("http"):
                    continue
                ext = media_url.split(".")[-1].split("?")[0]
                if ext not in {"mp4", "jpg", "jpeg", "png", "gif", "webp"}:
                    ext = "mp4" if ("v.redd.it" in media_url or ".mp4" in media_url) else "jpg"
                filepath = os.path.join(tmpdir, f"reddit_{i}.{ext}")
                async with client.stream("GET", media_url) as resp:
                    if resp.status_code == 200:
                        with open(filepath, "wb") as f:
                            async for chunk in resp.aiter_bytes(chunk_size=8192):
                                f.write(chunk)
                        filepaths.append(filepath)

            if not filepaths:
                return None, "Reddit недоступен с этого сервера. Попробуй позже."

            return "|||".join(filepaths), None

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
                    logger.info("Pixiv image %d status: %s", i, resp.status_code)
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
