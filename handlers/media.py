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

from downloader import download_media, detect_platform, cleanup_file, get_video_dimensions
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


@router.message(F.text.regexp(URL_RE))
async def handle_url(message: Message):
    url = URL_RE.search(message.text).group(0)
    platform = detect_platform(url)
    if not platform:
        return

    user_id = message.from_user.id
    settings = get_user_settings(user_id)
    blur_radius = settings.get("blur", 0)
    is_pixiv = (platform == "pixiv")

    filepath, error = await download_media(url, audio_only=False)
    if error or not filepath:
        await message.reply(f"❌ {error or 'Неизвестная ошибка'}", parse_mode="HTML")
        return

    filepaths = filepath.split("|||")

    try:
        if len(filepaths) == 1:
            fp = filepaths[0]
            file_path = Path(fp)
            ext = file_path.suffix.lower()
            is_image = ext in {".jpg", ".jpeg", ".png", ".webp"}
            is_gif = ext == ".gif"

            if is_gif:
                await message.reply_animation(FSInputFile(fp))

            elif is_image:
                raw = file_path.read_bytes()
                processed = process_image_bytes(raw, blur_radius=blur_radius)
                if is_pixiv:
                    await message.reply_photo(
                        BufferedInputFile(processed, filename="photo.jpg"),
                    )
                else:
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
                width, height = await get_video_dimensions(fp)
                f = FSInputFile(fp)
                try:
                    await message.reply_video(
                        f,
                        supports_streaming=True,
                        width=width or None,
                        height=height or None,
                    )
                except Exception:
                    await message.reply_document(FSInputFile(fp))

                audio_path, audio_error = await download_media(url, audio_only=True)
                if audio_path and not audio_error:
                    await message.reply_audio(FSInputFile(audio_path), caption="🎵 Аудио")
                    await cleanup_file(audio_path)

        else:
            media_group = []
            photo_buttons = []

            for i, fp in enumerate(filepaths):
                file_path = Path(fp)
                ext = file_path.suffix.lower()
                is_image = ext in {".jpg", ".jpeg", ".png", ".webp"}
                is_gif = ext == ".gif"

                if is_gif:
                    await message.reply_animation(FSInputFile(fp))

                elif is_image:
                    raw = file_path.read_bytes()
                    processed = process_image_bytes(raw, blur_radius=blur_radius)
                    media_group.append(
                        InputMediaPhoto(media=BufferedInputFile(processed, filename="photo.jpg"))
                    )
                    if not is_pixiv:
                        cache_key = f"{user_id}_{file_path.name}"
                        _photo_cache[cache_key] = {"bytes": raw, "name": file_path.name}
                        photo_buttons.append([
                            InlineKeyboardButton(text="📁 Фото файлом", callback_data=f"sendfile:{cache_key}"),
                        ])
                else:
                    width, height = await get_video_dimensions(fp)
                    media_group.append(
                        InputMediaVideo(
                            media=FSInputFile(fp),
                            supports_streaming=True,
                            width=width or None,
                            height=height or None,
                        )
                    )

            if media_group:
                await message.reply_media_group(media_group)

            has_video = any(
                Path(fp).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                for fp in filepaths
            )
            if has_video and not is_pixiv:
                audio_path, audio_error = await download_media(url, audio_only=True)
                if audio_path and not audio_error:
                    await message.reply_audio(FSInputFile(audio_path), caption="🎵 Аудио")
                    await cleanup_file(audio_path)

            if photo_buttons:
                kb = InlineKeyboardMarkup(inline_keyboard=photo_buttons)
                await message.reply("📎 Скачать оригиналы:", reply_markup=kb)

    except Exception as e:
        logger.exception("Media send error")
        await message.reply(f"❌ Ошибка при отправке: {e}")
    finally:
        for fp in filepaths:
            await cleanup_file(fp)


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
