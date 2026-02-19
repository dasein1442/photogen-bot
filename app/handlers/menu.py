from aiogram import F, Router
from aiogram.types import Message

from app.keyboards.common import get_main_menu_keyboard

router = Router()


@router.message(F.text == "Назад")
async def handle_back_to_menu(message: Message):
    await message.answer(
        "Возвращаемся в главное меню",
        reply_markup=get_main_menu_keyboard()
    )


@router.message(F.text == "Служба заботы")
async def handle_support(message: Message):
    await message.answer(
        "В случае возникновения проблем обращайтесь в чат поддержки (https://t.me/fotushkasupport)."
    )
