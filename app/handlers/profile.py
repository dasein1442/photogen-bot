import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.keyboards.common import get_profile_keyboard
from app.services.analytics_sdk import AnalyticsClient
from app.states.photo import PhotoUploadStates

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
async def handle_profile(message: Message, analytics: AnalyticsClient):
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
        generations = user_data.get("generations_remaining", 0)
        profile_photo_id = user_data.get("user", {}).get("profile_photo_id")
        additional_photo_id = user_data.get("user", {}).get("additional_photo_id")
    except Exception as e:
        logger.error(f"Ошибка получения данных профиля: {e}")
        generations = "?"
        profile_photo_id = None
        additional_photo_id = None
        user_data = {}

    await analytics.track("profile_viewed", user_id=str(message.from_user.id), properties={"generations_remaining": user_data.get("generations_remaining", 0)})

    first_name = message.from_user.first_name or "—"
    photo_status = "установлено ✅" if profile_photo_id else "не установлено"
    additional_photo_status = "установлено ✅" if additional_photo_id else "не установлено"

    profile_text = (
        f"👤  *{first_name}*\n"
        "━━━━━━━━━━━━━━━\n"
        f"📷  Фото:  {photo_status}\n"
        f"📷  Фото партнёра:  {additional_photo_status}\n"
        f"💎  Генерации:  *{generations}*\n"
    )

    await message.answer(
        profile_text,
        reply_markup=get_profile_keyboard(),
        parse_mode="Markdown"
    )


@router.message(F.text == "Установить новое фото")
async def handle_set_new_photo(message: Message, state: FSMContext):
    await state.set_state(PhotoUploadStates.waiting_for_main_photo)

    photo_instructions_text = (
        "Отправьте фотографию в чат!\n\n"
        "После этого нейросеть проведет модерацию фотографии. Это займет 5 секунд. "
        "Это нужно, чтобы убедиться, что ты соблюдаешь все условия ниже, "
        "ведь плохая фотография = плохие генерации!\n\n"
        "**Несколько важных моментов к фото:**\n"
        "• Используй крупный план (лучше селфи).\n"
        "• Без других людей и животных.\n"
        "• Лицо нейтральное или с лёгкой улыбкой.\n"
        "• Голова прямо, без наклонов.\n"
        "• Без очков и аксессуаров на лице.\n"
        "• Хорошее освещение — залог качественного результата."
    )

    await message.answer(
        photo_instructions_text,
        parse_mode="Markdown",
    )


@router.message(F.text == "Установить фото партнёра")
async def handle_set_partner_photo(message: Message, state: FSMContext):
    await state.set_state(PhotoUploadStates.waiting_for_additional_photo)

    photo_instructions_text = (
        "📸 Загрузите фото вашего партнёра (мужчины)\n\n"
        "Это фото будет использоваться для мужских и парных фотосессий.\n\n"
        "**Несколько важных моментов к фото:**\n"
        "• Используй крупный план (лучше селфи).\n"
        "• Без других людей и животных.\n"
        "• Лицо нейтральное или с лёгкой улыбкой.\n"
        "• Голова прямо, без наклонов.\n"
        "• Без очков и аксессуаров на лице.\n"
        "• Хорошее освещение — залог качественного результата."
    )

    await message.answer(
        photo_instructions_text,
        parse_mode="Markdown",
    )


@router.message(F.text == "Приобрести генерации")
async def handle_buy_generations(message: Message, analytics: AnalyticsClient):
    from app.handlers.payment import start_payment_flow
    await start_payment_flow(message, message.from_user.id, analytics=analytics)
