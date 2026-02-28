from aiogram import F, Router
from aiogram.types import Message

from app.keyboards.common import get_main_menu_keyboard
from app.services.analytics_sdk import AnalyticsClient

router = Router()


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
        "В случае возникновения проблем обращайтесь в чат поддержки (https://t.me/fotushkasupport)."
    )
