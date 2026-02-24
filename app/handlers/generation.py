import logging
import time

import aiohttp
from aiogram import Router
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InputMediaPhoto
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


async def _download_photo(url: str) -> bytes:
    """Скачать фото по URL. Возвращает байты. Райзит при ошибке."""
    logger.info(f"[download] Начинаю скачивание: {url[:120]}...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            logger.info(f"[download] HTTP {resp.status}, content-type={resp.content_type}, content-length={resp.content_length}")
            resp.raise_for_status()
            data = await resp.read()
            logger.info(f"[download] Скачано {len(data)} байт")
            return data


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

    # Проверяем, установлено ли фото профиля
    try:
        user_data = await backend.get_user(telegram_id=callback.from_user.id)
    except Exception as e:
        logger.error(f"Ошибка получения данных пользователя: {e}")
        await callback.message.answer("⚠️ Не удалось получить данные. Попробуй позже.")
        await callback.answer()
        return

    profile_photo_id = user_data.get("user", {}).get("profile_photo_id")

    if profile_photo_id:
        # Фото профиля есть — сразу генерируем
        await callback.answer()
        await _do_generation(callback.message, photosession_id, callback.from_user.id)
    else:
        # Фото профиля нет — просим загрузить
        await state.update_data(photosession_id=photosession_id)
        await state.set_state(PhotoUploadStates.waiting_for_main_photo)

        await callback.message.answer(
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
        await callback.answer()


async def _do_generation(message: Message, photosession_id: int, telegram_id: int | None = None):
    """Запуск генерации → поллинг → отправка результатов."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("⏳ Начинаю генерацию, подожди немного...")

    # 1. Запуск генерации на бэкенде
    t0 = time.monotonic()
    try:
        gen_result = await backend.generate_photo(
            telegram_id=telegram_id,
            photosession_id=photosession_id,
        )
    except Exception as e:
        logger.error(
            f"Ошибка запуска генерации: {type(e).__name__}: {e} "
            f"(telegram_id={telegram_id}, photosession_id={photosession_id})",
            exc_info=True,
        )
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return
    api_time = time.monotonic() - t0
    logger.info(f"[tg={telegram_id}] Backend /generate responded in {api_time:.2f}s")

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

    # 2. Поллинг результата
    t0 = time.monotonic()
    try:
        task_result = await backend.poll_task(task_id)
    except Exception as e:
        logger.error(f"Ошибка поллинга задачи {task_id}: {e}")
        await message.answer("⚠️ Ошибка при ожидании результата. Попробуй позже.")
        return
    poll_time = time.monotonic() - t0
    logger.info(f"[tg={telegram_id}] Polling task_id={task_id} took {poll_time:.2f}s, status={task_result.get('status')}")

    status = task_result.get("status")

    if status == "completed":
        results = task_result.get("results", [])
        successful = [r for r in results if r.get("status") == "completed" and r.get("result_url")]
        failed = [r for r in results if r.get("status") == "failed"]
        total = len(results)

        if not successful:
            await message.answer("❌ Все генерации не удались. Попробуй ещё раз.")
            return

        # 3. Скачиваем фото и отправляем в Telegram
        t0 = time.monotonic()
        logger.info(f"[tg={telegram_id}] Скачиваю {len(successful)} фото с S3...")
        for i, r in enumerate(successful):
            logger.info(f"[tg={telegram_id}] result[{i}]: status={r.get('status')}, url={r.get('result_url', 'NO_URL')[:120]}")

        photos_data = []
        for r in successful:
            data = await _download_photo(r["result_url"])
            photos_data.append(data)

        logger.info(f"[tg={telegram_id}] Скачано {len(photos_data)} фото, размеры: {[len(d) for d in photos_data]}")

        if len(photos_data) == 1:
            logger.info(f"[tg={telegram_id}] Отправляю 1 фото через answer_photo ({len(photos_data[0])} байт)")
            await message.answer_photo(
                photo=BufferedInputFile(photos_data[0], filename="photo.jpg"),
            )
        else:
            logger.info(f"[tg={telegram_id}] Отправляю {len(photos_data)} фото через answer_media_group")
            media = [
                InputMediaPhoto(
                    media=BufferedInputFile(data, filename=f"photo_{i}.jpg"),
                )
                for i, data in enumerate(photos_data)
            ]
            await message.answer_media_group(media=media)

        send_time = time.monotonic() - t0
        logger.info(f"[tg={telegram_id}] Фото отправлены за {send_time:.2f}s")

        total_time = time.monotonic() - t_total
        logger.info(
            f"[tg={telegram_id}] Generation complete: "
            f"api={api_time:.2f}s, poll={poll_time:.2f}s, send={send_time:.2f}s, "
            f"total={total_time:.2f}s, ok={len(successful)}/{total}"
        )

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
