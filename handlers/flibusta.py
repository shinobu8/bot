"""
Flibusta book search and download handler.
Uses Flibusta web scraping (no official API).
"""
import logging
import re
from typing import List, Tuple, Optional

import httpx
from bs4 import BeautifulSoup
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile,
)

router = Router()
logger = logging.getLogger(__name__)

# Try mirrors in order
FLIBUSTA_MIRRORS = [
    "https://flibusta.is",
    "https://flibusta.site",
    "http://flibusta.app",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

FORMAT_LABELS = {
    "epub": "📖 EPUB",
    "fb2": "📄 FB2",
    "mobi": "📱 MOBI",
    "pdf": "📑 PDF",
}


async def get_working_mirror() -> Optional[str]:
    for mirror in FLIBUSTA_MIRRORS:
        try:
            async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
                r = await client.get(mirror)
                if r.status_code < 400:
                    return mirror
        except Exception:
            continue
    return None


async def search_books(query: str, mirror: str) -> List[dict]:
    """Search books on Flibusta. Returns list of book dicts."""
    search_url = f"{mirror}/booksearch?ask={query}&chb=on"
    
    try:
        async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(search_url)
            r.raise_for_status()
    except Exception as e:
        logger.error("Flibusta search error: %s", e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    books = []

    # Find book list items
    for item in soup.select("ul li")[:30]:
        link = item.find("a", href=re.compile(r"/b/\d+$"))
        if not link:
            continue

        book_id = re.search(r"/b/(\d+)$", link["href"])
        if not book_id:
            continue

        title = link.get_text(strip=True)
        authors = []

        # Authors are usually in separate links before or after
        for a in item.find_all("a"):
            if re.match(r"/a/\d+", a.get("href", "")):
                authors.append(a.get_text(strip=True))

        books.append({
            "id": book_id.group(1),
            "title": title,
            "authors": authors,
        })

    return books[:10]


def books_keyboard(books: List[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for book in books:
        author_str = ", ".join(book["authors"][:2]) if book["authors"] else "Автор неизвестен"
        label = f"{book['title'][:30]} — {author_str[:20]}"
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"book:select:{book['id']}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="book:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def formats_keyboard(book_id: str) -> InlineKeyboardMarkup:
    formats = ["epub", "fb2", "mobi"]
    buttons = [[
        InlineKeyboardButton(
            text=FORMAT_LABELS.get(fmt, fmt.upper()),
            callback_data=f"book:dl:{book_id}:{fmt}",
        )
        for fmt in formats
    ]]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="book:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def download_book(book_id: str, fmt: str, mirror: str) -> Tuple[Optional[bytes], Optional[str]]:
    url = f"{mirror}/b/{book_id}/{fmt}"
    try:
        async with httpx.AsyncClient(timeout=60, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 404:
                return None, "Формат недоступен для этой книги."
            r.raise_for_status()
            
            # Check content-type
            ct = r.headers.get("content-type", "")
            if "text/html" in ct:
                return None, "Флибуста вернула HTML вместо файла — попробуй другой формат."
            
            return r.content, None
    except httpx.TimeoutException:
        return None, "Превышено время ожидания. Флибуста может быть недоступна."
    except Exception as e:
        logger.error("Book download error: %s", e)
        return None, str(e)


# Store last search results per user (in-memory, simple)
_user_search_cache = {}


@router.message(Command("book"))
async def cmd_book(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.reply(
            "❌ Укажи название или автора!\n"
            "Пример: <code>/book Достоевский преступление</code>\n"
            "По ID: <code>/book_id 12345</code>",
            parse_mode="HTML",
        )
        return

    query = args[1].strip()
    status = await message.reply(f"🔍 Ищу <b>{query}</b> на Флибусте...", parse_mode="HTML")

    mirror = await get_working_mirror()
    if not mirror:
        await status.edit_text(
            "❌ Флибуста недоступна. Попробуй позже.\n"
            "Сайт может быть заблокирован у твоего провайдера."
        )
        return

    books = await search_books(query, mirror)
    
    if not books:
        await status.edit_text(
            f"😔 По запросу <b>{query}</b> ничего не найдено.\n"
            "Попробуй другие слова.",
            parse_mode="HTML",
        )
        return

    _user_search_cache[message.from_user.id] = {"mirror": mirror, "books": books}

    book_list = "\n".join(
        f"{i+1}. <b>{b['title']}</b> — {', '.join(b['authors']) or '?'} (ID: {b['id']})"
        for i, b in enumerate(books)
    )

    await status.edit_text(
        f"📚 Найдено книг: {len(books)}\n\n{book_list}\n\nВыбери книгу:",
        reply_markup=books_keyboard(books),
        parse_mode="HTML",
    )


@router.message(Command("book_id"))
async def cmd_book_id(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.reply("❌ Укажи числовой ID книги. Пример: <code>/book_id 12345</code>", parse_mode="HTML")
        return

    book_id = args[1].strip()
    await message.reply(
        f"📖 Книга #{book_id} — выбери формат:",
        reply_markup=formats_keyboard(book_id),
    )
    _user_search_cache[message.from_user.id] = {"mirror": await get_working_mirror()}


@router.callback_query(F.data.startswith("book:"))
async def handle_book_callback(call: CallbackQuery):
    parts = call.data.split(":")
    action = parts[1]

    if action == "cancel" or action == "back":
        await call.message.delete()
        await call.answer()
        return

    if action == "select":
        book_id = parts[2]
        await call.message.edit_text(
            f"📖 Книга #{book_id} — выбери формат:",
            reply_markup=formats_keyboard(book_id),
        )
        await call.answer()

    elif action == "dl":
        book_id = parts[2]
        fmt = parts[3]

        cache = _user_search_cache.get(call.from_user.id, {})
        mirror = cache.get("mirror") or await get_working_mirror()

        if not mirror:
            await call.answer("❌ Флибуста недоступна", show_alert=True)
            return

        await call.answer("⏳ Скачиваю книгу...")
        status = await call.message.reply(f"⏳ Скачиваю в формате {fmt.upper()}...")

        data, error = await download_book(book_id, fmt, mirror)

        if error or not data:
            await status.edit_text(f"❌ Ошибка: {error or 'Неизвестная ошибка'}")
            return

        ext = fmt
        filename = f"book_{book_id}.{ext}"

        await status.edit_text("📤 Отправляю файл...")
        await call.message.reply_document(
            BufferedInputFile(data, filename=filename),
            caption=f"📚 Книга #{book_id} в формате {FORMAT_LABELS.get(fmt, fmt.upper())}",
        )
        await status.delete()
