from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from storage import get_user_settings, set_user_setting

router = Router()


def settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    s = get_user_settings(user_id)
    blur = s.get("blur", 0)
    blur_nsfw = s.get("blur_nsfw", False)
    source = s.get("source", "gelbooru")

    blur_label = f"🌫 Размытие: {'выкл' if blur == 0 else f'радиус {blur}'}"
    nsfw_label = f"🔞 Авто-размытие NSFW: {'✅' if blur_nsfw else '❌'}"
    source_label = f"🔍 Источник: {source.capitalize()}"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=blur_label, callback_data="settings:blur_menu")],
        [InlineKeyboardButton(text=nsfw_label, callback_data=f"settings:toggle_nsfw")],
        [InlineKeyboardButton(text=source_label, callback_data="settings:source_menu")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="settings:close")],
    ])


def blur_keyboard() -> InlineKeyboardMarkup:
    options = [0, 2, 5, 10, 20]
    buttons = [
        InlineKeyboardButton(text=f"{'Выкл' if v == 0 else str(v)}", callback_data=f"settings:blur:{v}")
        for v in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons,
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:main")],
    ])


def source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Gelbooru", callback_data="settings:source:gelbooru"),
            InlineKeyboardButton(text="Rule34", callback_data="settings:source:rule34"),
            InlineKeyboardButton(text="Оба", callback_data="settings:source:both"),
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings:main")],
    ])


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await message.answer(
        "⚙️ <b>Настройки</b>",
        reply_markup=settings_keyboard(message.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:main")
async def cb_settings_main(call: CallbackQuery):
    await call.message.edit_text(
        "⚙️ <b>Настройки</b>",
        reply_markup=settings_keyboard(call.from_user.id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "settings:blur_menu")
async def cb_blur_menu(call: CallbackQuery):
    await call.message.edit_text(
        "🌫 <b>Выбери радиус размытия</b>\n\n"
        "0 = без размытия\n"
        "Чем больше число — тем сильнее размытие.",
        reply_markup=blur_keyboard(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("settings:blur:"))
async def cb_set_blur(call: CallbackQuery):
    radius = int(call.data.split(":")[2])
    set_user_setting(call.from_user.id, "blur", radius)
    await call.answer(f"✅ Размытие: {'выкл' if radius == 0 else radius}")
    await call.message.edit_text(
        "⚙️ <b>Настройки</b>",
        reply_markup=settings_keyboard(call.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:toggle_nsfw")
async def cb_toggle_nsfw(call: CallbackQuery):
    s = get_user_settings(call.from_user.id)
    new_val = not s.get("blur_nsfw", False)
    set_user_setting(call.from_user.id, "blur_nsfw", new_val)
    await call.answer(f"{'✅ Авто-размытие включено' if new_val else '❌ Авто-размытие выключено'}")
    await call.message.edit_text(
        "⚙️ <b>Настройки</b>",
        reply_markup=settings_keyboard(call.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:source_menu")
async def cb_source_menu(call: CallbackQuery):
    await call.message.edit_text(
        "🔍 <b>Источник поиска артов</b>",
        reply_markup=source_keyboard(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("settings:source:"))
async def cb_set_source(call: CallbackQuery):
    source = call.data.split(":")[2]
    set_user_setting(call.from_user.id, "source", source)
    labels = {"gelbooru": "Gelbooru", "rule34": "Rule34", "both": "Оба"}
    await call.answer(f"✅ Источник: {labels.get(source, source)}")
    await call.message.edit_text(
        "⚙️ <b>Настройки</b>",
        reply_markup=settings_keyboard(call.from_user.id),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "settings:close")
async def cb_close(call: CallbackQuery):
    await call.message.delete()
    await call.answer()
