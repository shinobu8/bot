from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

router = Router()

HELP_TEXT = """
🤖 <b>Media Bot</b> — скачай всё что нужно!

<b>📥 Скачать медиа</b>
Просто отправь ссылку на:
• YouTube — видео/аудио
• TikTok — видео
• Instagram — фото, Reels, Stories
• Twitter/X — фото/видео
• Reddit — фото/видео/гиф
• Pixiv — арты (иллюстрации)

При отправке появятся кнопки:
  📁 <i>Файл</i> — оригинальное качество
  🖼 <i>Сжатое фото</i> — быстрая отправка

<b>📚 Флибуста</b>
• /book &lt;название или автор&gt; — найти книгу
• /book_id &lt;ID&gt; — скачать книгу по ID

<b>🎨 Поиск артов</b>
• /search &lt;тег&gt; — до 5 артов (Gelbooru + Rule34)
• /searchn &lt;N&gt; &lt;тег&gt; — N артов по тегу
  Пример: <code>/searchn 3 ushiromiya_battler</code>

<b>⚙️ Настройки</b>
• /settings — открыть меню настроек
  - Размытие изображений (по умолчанию / авто)
  - Источник поиска (Gelbooru / Rule34 / Оба)

<b>ℹ️ Лимиты</b>
• Макс. размер файла: 50 МБ
"""


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n" + HELP_TEXT,
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")
