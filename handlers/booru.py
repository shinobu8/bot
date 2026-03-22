import logging
import random
import asyncio
from typing import List, Tuple, Optional

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile, InputMediaPhoto

from image_utils import process_image_bytes
from storage import get_user_settings

router = Router()
logger = logging.getLogger(__name__)

MAX_ARTS = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TelegramBot/1.0)"}


async def fetch_safebooru(tags: str, limit: int) -> List[dict]:
    url = (
        f"https://safebooru.org/index.php?page=dapi&s=post&q=index&json=1"
        f"&limit={limit * 3}&tags={tags}&pid={random.randint(0, 5)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            logger.info("Safebooru returned %d posts", len(data) if isinstance(data, list) else 0)
            if isinstance(data, list):
                result = []
                for p in data:
                    if not isinstance(p, dict):
                        continue
                    pid = p.get("id", "")
                    directory = p.get("directory", "")
                    image = p.get("image", "")
                    if directory and image:
                        file_url = f"https://safebooru.org/images/{directory}/{image}"
                        result.append({"file_url": file_url, "id": pid, "source": "safebooru"})
                return result
            return []
    except Exception as e:
        logger.warning("Safebooru fetch error: %s", e)
        return []


async def fetch_rule34(tags: str, limit: int) -> List[dict]:
    url = (
        f"https://api.rule34.xxx/index.php?page=dapi&s=post&q=index&json=1"
        f"&limit={limit * 3}&tags={tags}&pid={random.randint(0, 5)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                data = data.get("post", []) or []
            if isinstance(data, list):
                return [p for p in data if isinstance(p, dict) and p.get("file_url")]
            return []
    except Exception as e:
        logger.warning("Rule34 fetch error: %s", e)
        return []


async def fetch_danbooru(tags: str, limit: int) -> List[dict]:
    url = (
        f"https://danbooru.donmai.us/posts.json"
        f"?tags={tags}&limit={limit * 2}&page={random.randint(1, 3)}"
    )
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            result = []
            for p in data:
                if not isinstance(p, dict):
                    continue
                file_url = p.get("file_url") or p.get("large_file_url")
                if not file_url:
                    md5 = p.get("md5", "")
                    ext = p.get("file_ext", "jpg")
                    if md5 and ext in {"jpg", "jpeg", "png", "gif", "webp"}:
                        file_url = f"https://cdn.donmai.us/original/{md5[:2]}/{md5[2:4]}/{md5}.{ext}"
                if file_url and is_image_url(file_url):
                    result.append({"file_url": file_url, "id": p.get("id", ""), "source": "danbooru"})
            logger.info("Danbooru found %d posts", len(result))
            return result
    except Exception as e:
        logger.warning("Danbooru fetch error: %s", e)
        return []


async def download_image(url: str) -> Optional[bytes]:
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
    tags_encoded = tags.strip().replace(" ", "+")

    safe, r34, dan = await asyncio.gather(
        fetch_safebooru(tags_encoded, count),
        fetch_rule34(tags_encoded, count),
        fetch_danbooru(tags_encoded, count),
    )
    posts = safe + r34 + dan
    random.shuffle(posts)

    seen = set()
    results = []
    for p in posts:
        url = p.get("file_url", "")
        if url in seen or not is_image_url(url):
            continue
        seen.add(url)

        pid = p.get("id", "")
        src = p.get("source", "")
        if "danbooru" in src:
            post_url = f"https://danbooru.donmai.us/posts/{pid}"
        elif "safebooru" in src:
            post_url = f"https://safebooru.org/index.php?page=post&s=view&id={pid}"
        else:
            post_url = f"https://rule34.xxx/index.php?page=post&s=view&id={pid}"

        results.append((url, post_url))
        if len(results) >= count:
            break

    return results


async def send_arts(message: Message, tags: str, count: int):
    count = min(count, MAX_ARTS)
    user_id = message.from_user.id
    settings = get_user_settings(user_id)
    blur_radius = settings.get("blur", 0)

    status = await message.reply(
        f"🔍 Ищу {count} арт(ов) по тегу <code>{tags}</code>...",
        parse_mode="HTML",
    )

    results = await search_arts(tags, count, "both")

    if not results:
        await status.edit_text(
            f"😔 Ничего не найдено по тегу <code>{tags}</code>.\n"
            "Проверь теги — они должны быть на английском.",
            parse_mode="HTML",
        )
        return

    await status.edit_text(f"📥 Найдено {len(results)}, загружаю...")

    download_tasks = [download_image(url) for url, _ in results]
    images_raw = await asyncio.gather(*download_tasks)

    sent = 0
    media_group = []

    for i, ((file_url, post_url), raw) in enumerate(zip(results, images_raw)):
        if not raw:
            continue
        try:
            processed = process_image_bytes(raw, blur_radius=blur_radius, compress=True) = process_image_bytes(raw, blur_radius=blur_radius)
            caption = f"🎨 {tags} [{i+1}/{len(results)}]\n<a href='{post_url}'>Источник</a>"

            if len(results) == 1:
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
            f"⚙️ /settings — изменить настройки",
        )


@router.message(Command("search"))
async def cmd_search(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "❌ Укажи теги!\n"
            "Пример: <code>/search ushiromiya_battler</code>",
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
            f"❌ <code>{args[1]}</code> не является числом!",
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
