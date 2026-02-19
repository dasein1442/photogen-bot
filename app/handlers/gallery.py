from aiogram import F, Router
from aiogram.types import Message, WebAppInfo
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

router = Router()


@router.message(F.text == "Галерея образов")
async def handle_gallery(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Открыть галерею 🎨",
                web_app=WebAppInfo(url="https://your-domain.com/gallery")
            )]
        ]
    )
    
    await message.answer(
        "Выбери образ из галереи для генерации фото 👇",
        reply_markup=keyboard
    )
