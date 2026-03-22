"""
/search and /searchn handlers for Gelbooru and Rule34.
"""
import logging
import random
import asyncio
from typing import List, Optional, Tuple

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile, InputMediaPhoto

from config import Config
from image_utils import process_image_bytes
from storage import get_user_settings

router = Router()
logger = logging.getLogger(__name__)
config = Config.load()

MAX_ARTS = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TelegramBot/1.0)"}


async def fetch_gelbooru(tags: str, limit: int) -> List[dict]:
    """Fetch posts from Gelbooru API."""
    url = (
        f"https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1"
        f"&limit={limit * 3}&tags={tags}&pid={random.randint(0, 5)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            posts = data.get("post", []) if isinstance(data, dict) else data
            return [p for p in posts if p.get("file_url")]
    except Exception as e:
        logger.warning("Gelbooru fetch error: %s", e)
        return []


async def fetch_rule34(tags: str, limit: int) -> List[dict]:
    """Fetch posts from Rule34 API."""
    url = (
        f"https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&json=1"
        f"&limit={limit * 3}&tags={tags}&pid={random.randint(0, 5)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            return [p for p in (data or []) if p.get("file_url")]
    except Exception as e:
        logger.warning("Rule34 fetch error: %s", e)
        return []


async def download_image(url: str) -> Optional[bytes]:
    """Download image bytes from URL."""
    try:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.content
    except Exception as e:
        logger.warning("Image download error %s: %s", url, e)
        return None


def is_image_url(url: str) -> bool:
    return any(url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"])


async def search_arts(tags: str, count: int, source: str) -> List[Tuple[str, str]]:
    """
    Search for arts. Returns list of (file_url, post_url) tuples.
    """
    tags_encoded = tags.strip().replace(" ", "+")
    
    if source == "gelbooru":
        posts = await fetch_gelbooru(tags_encoded, count)
    elif source == "rule34":
        posts = await fetch_rule34(tags_encoded, count)
    else:  # both
        gb, r34 = await asyncio.gather(
            fetch_gelbooru(tags_encoded, count),
            fetch_rule34(tags_encoded, count),
        )
        posts = gb + r34
        random.shuffle(posts)

    # Filter to image-only and deduplicate
    seen = set()
    results = []
    for p in posts:
        url = p.get("file_url", "")
        if url in seen or not is_image_url(url):
            continue
        seen.add(url)
        
        # Build post URL
        if "gelbooru" in url or p.get("source", "").startswith("https://gelbooru"):
            post_url = f"https://gelbooru.com/index.php?page=post&s=view&id={p.get('id', '')}"
        else:
            post_url = f"https://rule34.xxx/index.php?page=post&s=view&id={p.get('id', '')}"
        
        results.append((url, post_url))
        if len(results) >= count:
            break

    return results


async def send_arts(message: Message, tags: str, count: int):
    count = min(count, MAX_ARTS)
    user_id = message.from_user.id
    settings = get_user_settings(user_id)
    blur_radius = settings.get("blur", 0)
    source = settings.get("source", "gelbooru")

    status = await message.reply(f"🔍 Ищу {count} арт(ов) по тегу <code>{tags}</code>...", parse_mode="HTML")

    results = await search_arts(tags, count, source)

    if not results:
        await status.edit_text(
            f"😔 Ничего не найдено по тегу <code>{tags}</code>.\n"
            "Проверь теги — они должны быть на английском, через пробел или +.",
            parse_mode="HTML",
        )
        return

    await status.edit_text(f"📥 Найдено {len(results)}, загружаю...")

    # Download all images concurrently
    download_tasks = [download_image(url) for url, _ in results]
    images_raw = await asyncio.gather(*download_tasks)

    sent = 0
    media_group = []

    for i, ((file_url, post_url), raw) in enumerate(zip(results, images_raw)):
        if not raw:
            continue
        
        try:
            processed = process_image_bytes(raw, blur_radius=blur_radius)
            caption = f"🎨 {tags} [{i+1}/{len(results)}]\n<a href='{post_url}'>Источник</a>"
            
            if len(results) == 1:
                # Single image — send directly
                await message.reply_photo(
                    BufferedInputFile(processed, filename=f"art_{i}.jpg"),
                    caption=caption,
                    parse_mode="HTML",
                )
            else:
                media_group.append(
                    InputMediaPhoto(
                        media=BufferedInputFile(processed, filename=f"art_{i}.jpg"),
                        caption=caption if i == 0 else None,
                        parse_mode="HTML" if i == 0 else None,
                    )
                )
            sent += 1
        except Exception as e:
            logger.warning("Failed to process art %d: %s", i, e)

    if media_group:
        # Send in chunks of 10 (Telegram limit)
        for chunk_start in range(0, len(media_group), 10):
            chunk = media_group[chunk_start:chunk_start + 10]
            await message.reply_media_group(chunk)

    try:
        await status.delete()
    except Exception:
        pass

    if sent == 0:
        await message.reply("❌ Не удалось загрузить ни одного изображения.")
    else:
        blur_note = f" 🌫 Размытие: {blur_radius}" if blur_radius else ""
        await message.reply(
            f"✅ Отправлено {sent} арт(ов){blur_note}\n"
            f"🔍 Источник: {source.capitalize()}\n"
            f"⚙️ /settings — изменить настройки",
        )


@router.message(Command("search"))
async def cmd_search(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "❌ Укажи теги!\n"
            "Пример: <code>/search ushiromiya_battler</code>\n"
            "Несколько тегов: <code>/search beatrice_(umineko) dress</code>",
            parse_mode="HTML",
        )
        return
    tags = args[1].strip()
    await send_arts(message, tags, count=5)


@router.message(Command("searchn"))
async def cmd_searchn(message: Message):
    args = message.text.split(maxsplit=2)
    
    if len(args) < 3:
        await message.reply(
            "❌ Формат: <code>/searchn [число] [тег]</code>\n"
            "Пример: <code>/searchn 3 ushiromiya_battler</code>",
            parse_mode="HTML",
        )
        return

    try:
        count = int(args[1])
    except ValueError:
        await message.reply(
            f"❌ <code>{args[1]}</code> не является числом!\n"
            "Пример: <code>/searchn 3 ushiromiya_battler</code>",
            parse_mode="HTML",
        )
        return

    if count < 1:
        await message.reply("❌ Число должно быть не менее 1.")
        return
    if count > MAX_ARTS:
        await message.reply(f"⚠️ Максимум {MAX_ARTS} артов за раз.")
        count = MAX_ARTS

    tags = args[2].strip()
    await send_arts(message, tags, count=count)
