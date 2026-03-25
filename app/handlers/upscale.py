from aiogram import Router, F
from aiogram.types import Message

router = Router()


@router.message(F.text == "🔍 Улучшить кач-во")
async def handle_upscale_stub(message: Message):
    await message.answer(
        "🔍 <b>Улучшить качество</b>\n\n"
        "ИИ увеличит разрешение и восстановит детали — размытое или сжатое фото станет чётким и качественным.\n\n"
        "📎 Отправь фотографию, которую нужно улучшить.\n\n"
        "<i>Стоимость: 2 генерации.</i>",
        parse_mode="HTML",
    )
