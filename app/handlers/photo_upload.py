import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery, URLInputFile, FSInputFile
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_payment_offer_keyboard
from app.keyboards.onboarding import get_next_step_keyboard
from app.handlers.generation import _format_validation_errors, _do_generation
from app.handlers.random_photo import _do_random_generation

logger = logging.getLogger(__name__)
router = Router()

_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
_WELCOME_PRICE_IMAGE_PATH = _ASSETS_DIR / "welcome_price.jpg"


async def _handle_upload(message: Message, state: FSMContext):
    """Загрузка фото, установка как profile photo, авто-генерация если пришли из flow."""
    await message.answer("🔄 Проверяю фотографию...")

    photo = message.photo[-1]

    # Скачиваем фото из Telegram
    try:
        bot = message.bot
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        photo_data = file_bytes.read()
    except Exception as e:
        logger.error(f"Ошибка скачивания фото из Telegram: {e}")
        await message.answer("⚠️ Не удалось скачать фото. Попробуй ещё раз.")
        return

    # Загружаем на бэкенд (с валидацией)
    try:
        result = await backend.upload_photo(
            telegram_id=message.from_user.id,
            photo_bytes=photo_data,
            filename=f"{message.from_user.id}_{photo.file_id}.jpg",
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото на бэкенд: {e}")
        await message.answer("⚠️ Не удалось связаться с сервером. Попробуй позже.")
        return

    if not result.get("ok"):
        errors = result.get("errors", [])
        await message.answer(_format_validation_errors(errors))
        return  # пользователь остаётся в том же состоянии, может отправить ещё

    # Устанавливаем как profile photo
    photo_id = result.get("photo_id")
    try:
        await backend.set_profile_photo(
            telegram_id=message.from_user.id,
            photo_id=photo_id,
        )
    except Exception as e:
        logger.error(f"Ошибка установки profile photo: {e}")
        await message.answer("⚠️ Не удалось сохранить фото профиля. Попробуй позже.")
        return

    # Проверяем, пришли ли из flow генерации
    data = await state.get_data()
    photosession_id = data.get("photosession_id")
    random_mode = data.get("random_mode", False)
    onboarding_mode = data.get("onboarding_mode", False)
    await state.clear()

    if onboarding_mode:
        # Пришли из онбординга — запускаем генерацию по онбординговому пресету
        await _do_onboarding_generation(message)
    elif random_mode:
        # Пришли из flow случайной генерации
        await _do_random_generation(message)
    elif photosession_id:
        # Пришли из flow генерации — запускаем генерацию автоматически
        await _do_generation(message, photosession_id)
    else:
        # Пришли из профиля — просто сообщаем об успехе
        await message.answer(
            "Готово ✅\n\n"
            "Бот обработал твои фотографии, и теперь ты можешь создавать "
            "снимки с собой в любом образе и месте.\n\n"
            "Попробуй свой первый запрос прямо сейчас, выбирай любой доступный "
            "инструмент, и генерируй шикарные фотографии 👇",
            reply_markup=get_main_menu_keyboard(),
        )


async def _do_onboarding_generation(message: Message, telegram_id: int | None = None):
    """Онбординговая генерация по фиксированному пресету → поллинг → отправка результата."""
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("⏳ Создаю твоё первое фото, подожди немного...")

    try:
        gen_result = await backend.generate_onboarding_photo(telegram_id=telegram_id)
    except Exception as e:
        logger.error(f"Ошибка запуска онбординговой генерации: {e}")
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        await message.answer(
            "❌ Не удалось списать кредит. Попробуй позже.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    if gen_result.get("error") == "no_presets":
        await message.answer(
            "😔 Пока нет доступных образов. Попробуй позже.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    task_id = gen_result.get("task_id")
    if not task_id:
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    try:
        task_result = await backend.poll_task(task_id)
    except Exception as e:
        logger.error(f"Ошибка поллинга задачи {task_id}: {e}")
        await message.answer("⚠️ Ошибка при ожидании результата. Попробуй позже.")
        return

    status = task_result.get("status")

    if status == "completed":
        results = task_result.get("results", [])
        successful = [r for r in results if r.get("status") == "completed" and r.get("result_url")]

        if not successful:
            await message.answer("❌ Генерация не удалась. Попробуй ещё раз.")
            return

        try:
            await message.answer_photo(photo=URLInputFile(successful[0]["result_url"]))
        except Exception as e:
            logger.error(f"Ошибка отправки результата: {e}")
            await message.answer(f"Фото готово! Скачай по ссылке:\n{successful[0]['result_url']}")

        await message.answer(
            "😍 Смотри, какая ты получилась!\n\n"
            "Это только проба — дальше можешь создавать реалистичные фото в любых образах:\n"
            "👔 деловая съёмка\n"
            "🏖 фотосессия на пляже\n"
            "📸 стиль Pinterest или журнал Vogue\n\n"
            "Хочешь увидеть полную серию? 👇",
            reply_markup=get_next_step_keyboard(),
        )
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")


@router.message(F.photo, PhotoUploadStates.waiting_for_main_photo)
async def handle_main_photo_upload(message: Message, state: FSMContext):
    await _handle_upload(message, state)


@router.callback_query(lambda callback: callback.data == "upload_profile_photo")
async def handle_upload_profile_photo(callback: CallbackQuery, state: FSMContext):
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
        "• Без очков и аксессуаров на лице.\n"
        "• Хорошее освещение — залог качественного результата."
    )

    await callback.message.answer(
        photo_instructions_text,
        parse_mode="Markdown",
    )

    await callback.answer()
