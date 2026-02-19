import logging

from aiogram import F, Router
from aiogram.types import Message
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.api.backend import backend

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "Галерея образов")
async def handle_gallery(message: Message):
    """Загружает пресеты с бэкенда и показывает как inline-кнопки."""
    try:
        presets = await backend.get_presets()
    except Exception as e:
        logger.error(f"Ошибка загрузки пресетов: {e}")
        await message.answer("⚠️ Не удалось загрузить галерею. Попробуй позже.")
        return

    if not presets:
        await message.answer("Пока нет доступных стилей. Заходи позже!")
        return

    # Формируем кнопки по 2 в ряд
    buttons = []
    row = []
    for preset in presets:
        row.append(
            InlineKeyboardButton(
                text=preset.get("name", f"Стиль {preset['id']}"),
                callback_data=f"preset_{preset['id']}",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "Выбери образ для генерации фото 🎨👇",
        reply_markup=keyboard,
    )
