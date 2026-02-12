from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.api.backend import backend

router = Router()


@router.message(CommandStart())
async def handle_start(message: Message):
    """Обработчик команды /start."""
    user = message.from_user

    # Регистрируем пользователя в бэкенде (пока заглушка)
    await backend.create_user(
        telegram_id=user.id,
        username=user.username,
    )

    await message.answer(
        f"Привет, {user.first_name}!\n\n"
        "Добро пожаловать в Photogen — нейрофотосессии прямо в Telegram.\n\n"
        "Загрузи своё фото, выбери пресет — и получи профессиональную фотосессию за минуты."
    )
