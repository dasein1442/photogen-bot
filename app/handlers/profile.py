import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.api.backend import backend
from app.keyboards.common import get_profile_keyboard, get_photo_type_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("balance"))
async def handle_balance_command(message: Message):
    """Команда /balance — показать баланс генераций."""
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
        generations = user_data.get("generations_remaining", 0)
    except Exception as e:
        logger.error(f"Ошибка получения баланса: {e}")
        generations = "?"

    await message.answer(f"💎 Доступно генераций: {generations}")


@router.message(F.text == "Профиль")
async def handle_profile(message: Message):
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
        generations = user_data.get("generations_remaining", 0)
    except Exception as e:
        logger.error(f"Ошибка получения данных профиля: {e}")
        generations = "?"

    profile_text = (
        "**Профиль**\n\n"
        f"**Оставшееся количество генераций:** {generations}.\n\n"
        "Чтобы обучить нейросеть на новые фото — загрузи свои другие снимки или фотографии другого человека, "
        "чтобы создать образы с другим лицом."
    )

    await message.answer(
        profile_text,
        reply_markup=get_profile_keyboard(),
        parse_mode="Markdown"
    )


@router.message(F.text == "Установить новое фото")
async def handle_set_new_photo(message: Message):
    photo_selection_text = (
        "**Информация о возможности генерации с двумя людьми на одном изображении.**\n\n"
        "**Основное** - используется для одиночной генерации, является необходимым изображением "
        "для доступа к большинству функций в боте.\n\n"
        "**Дополнительное** - используется в качестве дополнительного изображения человека "
        "для генерации двух людей на одном изображении.\n\n"
        "Какое фото хотите обновить? 👇"
    )

    await message.answer(
        photo_selection_text,
        reply_markup=get_photo_type_keyboard(),
        parse_mode="Markdown"
    )


@router.message(F.text == "Приобрести генерации")
async def handle_buy_generations(message: Message):
    await message.answer(
        "Функция покупки генераций будет доступна в ближайшее время! 🚀"
    )
