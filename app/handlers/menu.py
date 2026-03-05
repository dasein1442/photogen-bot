from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.api.backend import backend
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_payment_method_keyboard
from app.services.analytics_sdk import AnalyticsClient

router = Router()


@router.message(Command("menu"))
async def handle_menu_command(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Команда /menu — открыть главное меню (только для купивших пользователей)."""
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
        user_info = user_data.get("user", {})
    except Exception:
        await message.answer("⚠️ Не удалось получить данные. Попробуй позже.")
        return

    if not user_info.get("onboarding_completed"):
        await message.answer("Сначала пройди онбординг — отправь /start")
        return

    if not user_info.get("has_purchased"):
        await message.answer(
            "Открой доступ к 70+ стилям!\n\n"
            "Деловая съёмка, пляж, Pinterest, Vogue и многое другое.\n\n"
            "Выбери способ оплаты 👇",
            reply_markup=get_payment_method_keyboard("onboarding"),
        )
        return

    await state.clear()
    await analytics.track("menu_opened", user_id=str(message.from_user.id), properties={"source": "command"})
    await message.answer(
        "Главное меню 👇",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(F.text == "Назад")
async def handle_back_to_menu(message: Message, analytics: AnalyticsClient):
    await analytics.track("menu_opened", user_id=str(message.from_user.id))
    await message.answer(
        "Возвращаемся в главное меню",
        reply_markup=get_main_menu_keyboard()
    )


@router.message(F.text == "Служба заботы")
async def handle_support(message: Message):
    await message.answer(
        "В случае возникновения проблем обращайтесь в чат поддержки (https://t.me/IIUSNO)."
    )
