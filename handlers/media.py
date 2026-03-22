"""
Media download handler.
Triggers on URLs from supported platforms.
"""
import os
import logging
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, BufferedInputFile,
)
import httpx

from downloader import download_media, detect_platform, cleanup_file
from image_utils import process_image_bytes
from storage import get_user_settings

router = Router()
logger = logging.getLogger(__name__)

# URL regex filter
import re
URL_RE = re.compile(
    r"https?://([a-z0-9\-]+\.)?"
    r"(youtube\.com|youtu\.be|tiktok\.com|vm\.tiktok\.com"
    r"|vt\.tiktok\.com|instagram\.com|twitter\.com|x\.com"
    r"|reddit\.com|redd\.it|pixiv\.net)"
    r"\S*",
    re.IGNORECASE,

)

PLATFORM_EMOJIS = {
    "youtube": "▶️ YouTube",
    "tiktok": "🎵 TikTok",
    "instagram": "📸 Instagram",
    "twitter": "🐦 Twitter/X",
    "reddit": "🤖 Reddit",
    "pixiv": "🎨 Pixiv",
}





@router.message(F.text.regexp(URL_RE))
async def handle_url(message: Message):
    url = URL_RE.search(message.text).group(0)
    platform = detect_platform(url)
    if not platform:
        return

    emoji = PLATFORM_EMOJIS.get(platform, "🌐")
    user_id = message.from_user.id
    settings = get_user_settings(user_id)
    blur_radius = settings.get("blur", 0)

    status_msg = await message.reply(f"{emoji} Скачиваю...")

    # Скачиваем видео
    filepath, error = await download_media(url, audio_only=False)
    if error or not filepath:
        await status_msg.edit_text(f"❌ Ошибка: {error or 'Неизвестная ошибка'}")
        return

    file_path = Path(filepath)
    ext = file_path.suffix.lower()
    is_image = ext in {".jpg", ".jpeg", ".png", ".webp"}

    await status_msg.edit_text("📤 Отправляю...")

    try:
        if is_image:
            raw = file_path.read_bytes()
            processed = process_image_bytes(raw, blur_radius=blur_radius)
            await message.reply_photo(
                BufferedInputFile(processed, filename="photo.jpg"),
                caption="🖼 Фото",
            )
        else:
            f = FSInputFile(filepath)
            try:
                await message.reply_video(f, caption="🎬 Видео")
            except Exception:
                await message.reply_document(f, caption="📁 Файл")

            # Скачиваем аудио отдельно
            audio_path, audio_error = await download_media(url, audio_only=True)
            if audio_path and not audio_error:
                af = FSInputFile(audio_path)
                await message.reply_audio(af, caption="🎵 Аудио")
                await cleanup_file(audio_path)

    except Exception as e:
        logger.exception("Media send error")
        await status_msg.edit_text(f"❌ Ошибка при отправке: {e}")
    finally:
        await cleanup_file(filepath)

    await status_msg.delete()

@router.callback_query(F.data.startswith("dl:"))
async def handle_download_callback(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":", 2)
    mode = parts[1]  # "file", "photo", "cancel"

    if mode == "cancel":
        await call.message.delete()
        await call.answer()
        return

    url = parts[2]
    user_id = call.from_user.id
    settings = get_user_settings(user_id)
    blur_radius = settings.get("blur", 0)

    await call.answer("⏳ Загружаю...")
    status_msg = await call.message.reply("⏳ Скачиваю медиа, подожди...")

    try:
        filepath, error = await download_media(url)
        
        if error or not filepath:
            await status_msg.edit_text(f"❌ Ошибка: {error or 'Неизвестная ошибка'}")
            return

        file_path = Path(filepath)
        ext = file_path.suffix.lower()
        is_image = ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
        is_video = ext in {".mp4", ".mkv", ".webm", ".mov", ".avi"}

        await status_msg.edit_text("📤 Отправляю...")

        if mode == "photo" and is_image:
            # Send as compressed photo with optional blur
            raw = file_path.read_bytes()
            processed = process_image_bytes(raw, blur_radius=blur_radius, compress=True)
            await call.message.reply_photo(
                BufferedInputFile(processed, filename="photo.jpg"),
                caption=f"🖼 Сжатое фото\n{'🌫 Размытие применено' if blur_radius else ''}",
            )

        elif mode == "photo" and is_video:
            # For videos "photo mode" = send as document but smaller
            f = FSInputFile(filepath)
            await call.message.reply_document(
                f,
                caption="📁 Видео (оригинал, сжатие недоступно для видео)",
            )

        elif mode == "file":
            # Send as file/document — full quality
            f = FSInputFile(filepath)
            if is_video:
                try:
                    await call.message.reply_video(f, caption="📁 Видео")
                except Exception:
                    await call.message.reply_document(f, caption="📁 Файл")
            elif is_image:
                raw = file_path.read_bytes()
                processed = process_image_bytes(raw, blur_radius=blur_radius)
                await call.message.reply_document(
                    BufferedInputFile(processed, filename=file_path.name),
                    caption=f"📁 Файл{'  🌫 Размытие применено' if blur_radius else ''}",
                )
            else:
                await call.message.reply_document(f, caption="📁 Файл")

        await status_msg.delete()

    except Exception as e:
        logger.exception("Media send error")
        await status_msg.edit_text(f"❌ Ошибка при отправке: {e}")
    finally:
        if filepath:
            await cleanup_file(filepath)
