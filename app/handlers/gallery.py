import logging

from aiogram import F, Router
from aiogram.types import Message

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "Галерея образов")
async def handle_gallery(message: Message):
    """Заглушка — галерея образов будет доступна в TMA."""
    await message.answer(
        "🖼 Скоро здесь появится галерея образов!\n\n"
        "А пока выбери фотосессию — нажми «📸 Создать фотосессию» в меню."
    )
