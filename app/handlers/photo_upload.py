from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard

router = Router()


@router.message(F.photo, PhotoUploadStates.waiting_for_main_photo)
async def handle_main_photo_upload(message: Message, state: FSMContext):
    await message.answer("🔄 Начинаю модерацию изображения на соблюдение всех правил...")

    photo = message.photo[-1]
    moderation_result = await backend.moderate_photo(
        telegram_id=message.from_user.id,
        file_id=photo.file_id,
    )

    if not moderation_result.get("is_valid", False):
        reason = moderation_result.get(
            "reason",
            "лицо наполовину закрыто или нет прямого взгляда",
        )
        await message.answer(
            "❌ Ваша фотография не прошла модерацию по причине: "
            f"{reason}.\n\n"
            "Отправьте другую фотографию."
        )
        return

    await backend.update_user_photo(
        telegram_id=message.from_user.id,
        file_id=photo.file_id,
        photo_type="main"
    )

    await state.clear()

    await message.answer(
        "Готово ✅\n\n"
        "Бот обработал твои фотографии, и теперь ты можешь создавать снимки с собой в любом образе и месте.\n\n"
        "Попробуй свой первый запрос прямо сейчас, выбирай любой доступный инструмент, и генерируй шикарные фотографии 👇",
        reply_markup=get_main_menu_keyboard()
    )


@router.message(F.photo, PhotoUploadStates.waiting_for_additional_photo)
async def handle_additional_photo_upload(message: Message, state: FSMContext):
    await message.answer("🔄 Начинаю модерацию изображения на соблюдение всех правил...")

    photo = message.photo[-1]
    moderation_result = await backend.moderate_photo(
        telegram_id=message.from_user.id,
        file_id=photo.file_id,
    )

    if not moderation_result.get("is_valid", False):
        reason = moderation_result.get(
            "reason",
            "лицо наполовину закрыто или нет прямого взгляда",
        )
        await message.answer(
            "❌ Ваша фотография не прошла модерацию по причине: "
            f"{reason}.\n\n"
            "Отправьте другую фотографию."
        )
        return

    await backend.update_user_photo(
        telegram_id=message.from_user.id,
        file_id=photo.file_id,
        photo_type="additional"
    )

    await state.clear()

    await message.answer(
        "Готово ✅\n\n"
        "Бот обработал твои фотографии, и теперь ты можешь создавать снимки с собой в любом образе и месте.\n\n"
        "Попробуй свой первый запрос прямо сейчас, выбирай любой доступный инструмент, и генерируй шикарные фотографии 👇",
        reply_markup=get_main_menu_keyboard()
    )


@router.callback_query(lambda callback: callback.data == "photo_main")
async def handle_photo_main(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    
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
        "• Хорошее освещение — залог качественного результата."
    )
    
    await callback.message.answer(
        photo_instructions_text,
        parse_mode="Markdown"
    )
    
    await callback.answer()


@router.callback_query(lambda callback: callback.data == "photo_additional")
async def handle_photo_additional(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    
    await state.set_state(PhotoUploadStates.waiting_for_additional_photo)
    
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
        "• Хорошее освещение — залог качественного результата."
    )
    
    await callback.message.answer(
        photo_instructions_text,
        parse_mode="Markdown"
    )
    
    await callback.answer()
