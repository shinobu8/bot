import re
import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile, BufferedInputFile,
    InputMediaPhoto, InputMediaVideo,
)

from downloader import download_media, detect_platform, cleanup_file
from image_utils import process_image_bytes
from storage import get_user_settings

router = Router()
logger = logging.getLogger(__name__)

_photo_cache: dict = {}

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

    filepath, error = await download_media(url, audio_only=False)
    if error or not filepath:
        await status_msg.edit_text(f"❌ Ошибка: {error or 'Неизвестная ошибка'}")
        return

    filepaths = filepath.split("|||")

    await status_msg.edit_text("📤 Отправляю...")

    try:
        if len(filepaths) == 1:
            fp = filepaths[0]
            file_path = Path(fp)
            ext = file_path.suffix.lower()
            is_image = ext in {".jpg", ".jpeg", ".png", ".webp"}

            if is_image:
                raw = file_path.read_bytes()
                processed = process_image_bytes(raw, blur_radius=blur_radius)
                cache_key = f"{user_id}_{file_path.name}"
                _photo_cache[cache_key] = {"bytes": raw, "name": file_path.name}
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="📁 Файлом", callback_data=f"sendfile:{cache_key}"),
                ]])
                await message.reply_photo(
                    BufferedInputFile(processed, filename="photo.jpg"),
                    reply_markup=kb,
                )
            else:
                f = FSInputFile(fp)
                try:
                    await message.reply_video(f)
                except Exception:
                    await message.reply_document(f)

                audio_path, audio_error = await download_media(url, audio_only=True)
                if audio_path and not audio_error:
                    af = FSInputFile(audio_path)
                    await message.reply_audio(af, caption="🎵 Аудио")
                    await cleanup_file(audio_path)

        else:
            media_group = []
            photo_buttons = []

            for i, fp in enumerate(filepaths):
                file_path = Path(fp)
                ext = file_path.suffix.lower()
                is_image = ext in {".jpg", ".jpeg", ".png", ".webp"}

                if is_image:
                    raw = file_path.read_bytes()
                    processed = process_image_bytes(raw, blur_radius=blur_radius)
                    cache_key = f"{user_id}_{file_path.name}"
                    _photo_cache[cache_key] = {"bytes": raw, "name": file_path.name}
                    media_group.append(
                        InputMediaPhoto(media=BufferedInputFile(processed, filename="photo.jpg"))
                    )
                    photo_buttons.append([
                        InlineKeyboardButton(text="📁 Фото файлом", callback_data=f"sendfile:{cache_key}"),
                    ])
                else:
                    media_group.append(
                        InputMediaVideo(media=FSInputFile(fp))
                    )

            await message.reply_media_group(media_group)

            has_video = any(
                Path(fp).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}
                for fp in filepaths
            )
            if has_video:
                audio_path, audio_error = await download_media(url, audio_only=True)
                if audio_path and not audio_error:
                    af = FSInputFile(audio_path)
                    await message.reply_audio(af, caption="🎵 Аудио")
                    await cleanup_file(audio_path)

            if photo_buttons:
                kb = InlineKeyboardMarkup(inline_keyboard=photo_buttons)
                await message.reply("📎 Скачать оригиналы:", reply_markup=kb)

    except Exception as e:
        logger.exception("Media send error")
        await status_msg.edit_text(f"❌ Ошибка при отправке: {e}")
    finally:
        for fp in filepaths:
            await cleanup_file(fp)

    try:
        await status_msg.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("sendfile:"))
async def send_as_file(call: CallbackQuery):
    cache_key = call.data.split(":", 1)[1]
    cached = _photo_cache.get(cache_key)

    if not cached:
        await call.answer("❌ Файл устарел, отправь ссылку заново.", show_alert=True)
        return

    await call.answer("📤 Отправляю файлом...")
    try:
        await call.message.reply_document(
            BufferedInputFile(cached["bytes"], filename=cached["name"]),
        )
    except Exception as e:
        await call.message.reply(f"❌ Ошибка: {e}")
