import logging

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery, URLInputFile, InputMediaPhoto
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.states.photo import GenerationStates
from app.keyboards.common import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


def _format_validation_errors(errors: list[str]) -> str:
    """Форматировать список ошибок валидации в читаемое сообщение."""
    if not errors:
        return "❌ Неизвестная ошибка. Попробуй другое фото."

    lines = ["❌ Фото не прошло проверку:\n"]
    for err in errors:
        lines.append(f"• {err}")
    lines.append("\nИсправь замечания и отправь другое фото.")
    return "\n".join(lines)


@router.callback_query(lambda cb: cb.data and cb.data.startswith("photosession_"))
async def handle_photosession_choice(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал фотосессию."""
    photosession_id = int(callback.data.split("_")[1])
    await state.update_data(photosession_id=photosession_id)
    await state.set_state(GenerationStates.waiting_for_photo)

    await callback.message.answer(
        "Отлично! Теперь отправь фото для генерации 📸\n\n"
        "💡 Лучше обычное селфи с хорошим светом — без фильтров и других людей."
    )
    await callback.answer()


@router.message(F.photo, GenerationStates.waiting_for_photo)
async def handle_generation_photo(message: Message, state: FSMContext):
    """Фото получено в состоянии генерации (после выбора фотосессии)."""
    data = await state.get_data()
    photosession_id = data.get("photosession_id")

    if not photosession_id:
        await message.answer("Сначала выбери фотосессию в меню.")
        await state.clear()
        return

    await _do_generation(message, photosession_id)
    await state.clear()


async def _do_generation(message: Message, photosession_id: int):
    """Общая логика: загрузка фото → генерация → поллинг → отправка результатов."""
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

    # Загружаем на бэкенд (с валидацией)
    try:
        upload_result = await backend.upload_photo(
            telegram_id=telegram_id,
            photo_bytes=photo_data,
            filename=f"{telegram_id}_{photo.file_id}.jpg",
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото на бэкенд: {e}")
        await message.answer("⚠️ Не удалось загрузить фото на сервер. Попробуй позже.")
        return

    # Проверяем результат валидации
    if not upload_result.get("ok"):
        errors = upload_result.get("errors", [])
        await message.answer(_format_validation_errors(errors))
        return

    photo_id = upload_result["photo_id"]

    # Запускаем генерацию
    await message.answer("⏳ Начинаю генерацию, подожди немного...")

    try:
        gen_result = await backend.generate_photo(
            telegram_id=telegram_id,
            photo_id=photo_id,
            photosession_id=photosession_id,
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
        results = task_result.get("results", [])
        successful = [r for r in results if r.get("status") == "completed" and r.get("result_url")]
        failed = [r for r in results if r.get("status") == "failed"]
        total = len(results)

        if not successful:
            await message.answer("❌ Все генерации не удались. Попробуй ещё раз.")
            return

        # Отправляем результаты
        try:
            if len(successful) == 1:
                await message.answer_photo(photo=URLInputFile(successful[0]["result_url"]))
            else:
                media = [InputMediaPhoto(media=URLInputFile(r["result_url"])) for r in successful]
                await message.answer_media_group(media=media)
        except Exception as e:
            logger.error(f"Ошибка отправки результатов: {e}")
            urls = "\n".join(r["result_url"] for r in successful)
            await message.answer(f"Фото готовы! Скачай по ссылкам:\n{urls}")

        # Сообщаем о неудачных
        if failed:
            await message.answer(
                f"⚠️ {len(failed)} из {total} фото не удалось сгенерировать. "
                "Кредиты за них возвращены."
            )

        await message.answer(
            "😍 Смотри, какая красота!\n\n"
            "Хочешь ещё? Выбери фотосессию в меню или отправь новое фото 📸",
            reply_markup=get_main_menu_keyboard(),
        )
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
