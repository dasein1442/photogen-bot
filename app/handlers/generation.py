from aiogram import F, Router
from aiogram.types import Message

from app.api.backend import backend
from app.keyboards.onboarding import get_next_step_keyboard

router = Router()


@router.message(F.photo)
async def handle_photo(message: Message):
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

    await message.answer(
        "⏳ Начинаю генерацию, пожалуйста подождите...\n\n"
        "Уважаемые пользователи, изменить и обучить нейросеть на новую фотографию, "
        "чтобы, например, генерировать другого человека, можно — в настройках!"
    )

    generation_result = await backend.generate_photo(
        telegram_id=message.from_user.id,
        source_file_id=photo.file_id,
    )

    generated_file_id = generation_result.get("generated_file_id")

    if not generated_file_id:
        await message.answer("⚠️ Не удалось получить сгенерированное изображение. Попробуйте позже.")
        return

    await message.answer_photo(
        photo=generated_file_id,
    )

    await message.answer(
        "😍 Смотри, какая ты получилась!\n\n"
        "Это только проба — дальше можешь создавать реалистичные фото в любых образах:\n"
        "💼 деловая съёмка\n"
        "🏖 фотосессия на пляже\n"
        "📸 стиль Pinterest или журнал Vogue\n\n"
        "Хочешь увидеть полную серию? 👇",
        reply_markup=get_next_step_keyboard(),
    )
