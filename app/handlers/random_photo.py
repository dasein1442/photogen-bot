import logging

from aiogram import F, Router
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.handlers.generation import _download_photo
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "Случайное фото")
async def handle_random_photo(message: Message, state: FSMContext):
    """Обработка кнопки 'Случайное фото'."""
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя: {e}")
        await message.answer("⚠️ Не удалось получить данные. Попробуй позже.")
        return

    profile_photo_id = user_data.get("user", {}).get("profile_photo_id")

    if not profile_photo_id:
        await state.update_data(random_mode=True)
        await state.set_state(PhotoUploadStates.waiting_for_main_photo)

        await message.answer(
            "📸 Для генерации нужно фото профиля.\n\n"
            "Отправь своё фото в чат — оно будет сохранено и использовано "
            "для всех будущих генераций.\n\n"
            "**Несколько важных моментов к фото:**\n"
            "• Используй крупный план (лучше селфи).\n"
            "• Без других людей и животных.\n"
            "• Лицо нейтральное или с лёгкой улыбкой.\n"
            "• Голова прямо, без наклонов.\n"
            "• Без очков и аксессуаров на лице.\n"
            "• Хорошее освещение — залог качественного результата.",
            parse_mode="Markdown",
        )
        return

    await _do_random_generation(message)


async def _do_random_generation(message: Message, telegram_id: int | None = None):
    """Запуск случайной генерации → поллинг → отправка результата."""
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("🎲 Подбираю случайный образ, подожди немного...")

    try:
        gen_result = await backend.generate_random_photo(telegram_id=telegram_id)
    except Exception as e:
        logger.error(f"Ошибка запуска случайной генерации: {e}")
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        await message.answer(
            "❌ У тебя закончились генерации!\n\n"
            "Пополни баланс, чтобы продолжить создавать фото.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    if gen_result.get("error") == "no_presets":
        await message.answer(
            "😔 Сейчас нет доступных образов для случайного фото. Попробуй позже.",
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

        photo_data = await _download_photo(successful[0]["result_url"])
        if photo_data:
            try:
                await message.answer_photo(
                    photo=BufferedInputFile(photo_data, filename="photo.jpg"),
                )
            except Exception as e:
                logger.error(f"Ошибка отправки результата: {e}")
                await message.answer(f"Фото готово! Скачай по ссылке:\n{successful[0]['result_url']}")
        else:
            await message.answer(f"Фото готово! Скачай по ссылке:\n{successful[0]['result_url']}")

        await message.answer(
            "🎲 Вот твоё случайное фото!\n\n"
            "Нажми ещё раз «Случайное фото» для нового образа 📸",
            reply_markup=get_main_menu_keyboard(),
        )
    elif status == "failed":
        error_msg = task_result.get("error_message", "Неизвестная ошибка")
        await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
