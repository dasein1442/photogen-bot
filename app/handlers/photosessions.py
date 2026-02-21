import logging

from aiogram import F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from app.api.backend import backend

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "Фотосессии")
async def handle_photosessions(message: Message):
    """Загружает фотосессии с бэкенда и показывает как inline-кнопки."""
    try:
        photosessions = await backend.get_photosessions()
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await message.answer("⚠️ Не удалось загрузить фотосессии. Попробуй позже.")
        return

    if not photosessions:
        await message.answer("Пока нет доступных фотосессий. Заходи позже!")
        return

    buttons = []
    for ps in photosessions:
        name = ps.get("name", f"Фотосессия {ps['id']}")
        count = ps.get("preset_count", 0)
        buttons.append([
            InlineKeyboardButton(
                text=f"{name} ({count} фото)",
                callback_data=f"photosession_{ps['id']}",
            )
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "Выбери фотосессию 📸👇",
        reply_markup=keyboard,
    )
