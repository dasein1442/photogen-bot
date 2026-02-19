import logging

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery, URLInputFile
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.states.photo import GenerationStates
from app.keyboards.common import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(lambda cb: cb.data and cb.data.startswith("preset_"))
async def handle_preset_choice(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал пресет из галереи."""
    preset_id = int(callback.data.split("_")[1])
    await state.update_data(preset_id=preset_id)
    await state.set_state(GenerationStates.waiting_for_photo)

    await callback.message.answer(
        "Отлично! Теперь отправь фото для генерации 📸\n\n"
        "💡 Лучше обычное селфи с хорошим светом — без фильтров и других людей."
    )
    await callback.answer()


@router.message(F.photo, GenerationStates.waiting_for_photo)
async def handle_generation_photo(message: Message, state: FSMContext):
    """Фото получено в состоянии генерации (после выбора пресета)."""
    data = await state.get_data()
    preset_id = data.get("preset_id")

    if not preset_id:
        await message.answer("Сначала выбери стиль в Галерее образов.")
        await state.clear()
        return

    await _do_generation(message, preset_id)
    await state.clear()


@router.message(F.photo)
async def handle_photo(message: Message):
    """Фото без состояния — быстрая генерация с пресетом по умолчанию (id=1)."""
    await _do_generation(message, preset_id=1)


async def _do_generation(message: Message, preset_id: int):
    """Общая логика: загрузка фото → генерация → поллинг → отправка результата."""
    telegram_id = message.from_user.id
    photo = message.photo[-1]

    await message.answer("🔄 Загружаю фото на сервер...")

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

    # Загружаем на бэкенд
    try:
        upload_result = await backend.upload_photo(
            telegram_id=telegram_id,
            photo_bytes=photo_data,
            filename=f"{telegram_id}_{photo.file_id}.jpg",
        )
        photo_id = upload_result["photo_id"]
    except Exception as e:
        logger.error(f"Ошибка загрузки фото на бэкенд: {e}")
        await message.answer("⚠️ Не удалось загрузить фото на сервер. Попробуй позже.")
        return

    # Запускаем генерацию
    await message.answer("⏳ Начинаю генерацию, подожди немного...")

    try:
        gen_result = await backend.generate_photo(
            telegram_id=telegram_id,
            photo_id=photo_id,
            preset_id=preset_id,
        )
    except Exception as e:
        logger.error(f"Ошибка запуска генерации: {e}")
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        await message.answer(
            "❌ У тебя закончились генерации!\n\n"
            "Пополни баланс, чтобы продолжить создавать фото.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    task_id = gen_result.get("task_id")
    if not task_id:
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    # Поллинг результата
    try:
        task_result = await backend.poll_task(task_id)
    except Exception as e:
        logger.error(f"Ошибка поллинга задачи {task_id}: {e}")
        await message.answer("⚠️ Ошибка при ожидании результата. Попробуй позже.")
        return

    status = task_result.get("status")

    if status == "completed":
        result_url = task_result.get("result_url")
        if result_url:
            try:
                await message.answer_photo(photo=URLInputFile(result_url))
            except Exception:
                await message.answer(f"Фото готово! Скачай по ссылке:\n{result_url}")

            await message.answer(
                "😍 Смотри, какая красота!\n\n"
                "Хочешь ещё? Выбери стиль в Галерее образов или отправь новое фото 📸",
                reply_markup=get_main_menu_keyboard(),
            )
        else:
            await message.answer("⚠️ Генерация завершена, но результат недоступен.")
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
