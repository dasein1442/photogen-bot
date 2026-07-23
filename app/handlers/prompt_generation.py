"""Unified flow for creating a new image or editing a source photo."""
import logging
import time

from aiogram import F, Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient
from app.services.generation_errors import CONTENT_MODERATION_MESSAGE, has_content_moderation_error
from app.services.tg_sender import download_photo, send_photos
from app.states.photo import PhotoUploadStates
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_buy_keyboard
from app.services.generation_access import require_generations

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "✨ Создать или изменить фото")
async def handle_prompt_gen_button(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Start the unified image creation and editing flow."""
    await analytics.track("prompt_generation_opened", user_id=str(message.from_user.id))
    if not await require_generations(
        message,
        message.from_user.id,
        required=2,
        action="создать или изменить фото",
        analytics=analytics,
    ):
        return
    await state.clear()
    await state.set_state(PhotoUploadStates.waiting_for_prompt_gen_photo)
    await state.set_data({"prompt_gen_photo_ids": []})

    await message.answer(
        "✨ <b>Создать или изменить фото</b>\n\n"
        "Измени фон, одежду или детали на фото, либо создай новый образ и сцену с людьми из референса. "
        "Можно отправить два фото, чтобы объединить людей или взять детали из каждого.\n\n"
        "📎 Отправь одну или две фотографии, а затем опиши результат.\n\n"
        "<i>Стоимость: 2 генерации.</i>",
        parse_mode="HTML",
    )


@router.message(F.photo, PhotoUploadStates.waiting_for_prompt_gen_photo)
async def handle_prompt_gen_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """User sent photo for prompt generation."""
    data = await state.get_data()
    photo_ids = data.get("prompt_gen_photo_ids", [])

    if len(photo_ids) >= 2:
        await message.answer("⚠️ Максимум 2 фото. Напиши свой запрос 👇")
        return

    await message.answer("🔄 Загружаю фото...")

    photo = message.photo[-1]

    try:
        bot = message.bot
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        photo_data = file_bytes.read()
    except Exception as e:
        logger.error(f"Ошибка скачивания фото из Telegram: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось скачать фото. Попробуй ещё раз.")
        return

    try:
        result = await backend.upload_photo_raw(
            telegram_id=message.from_user.id,
            photo_bytes=photo_data,
            filename=f"{message.from_user.id}_{photo.file_id}.jpg",
        )
    except Exception as e:
        logger.error(f"Ошибка загрузки фото на бэкенд: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось загрузить фото. Попробуй позже.")
        return

    if not result.get("ok"):
        error = result.get("error", "Неизвестная ошибка")
        await message.answer(f"⚠️ {error}")
        return

    photo_ids.append(result["photo_id"])
    await state.set_data({"prompt_gen_photo_ids": photo_ids})

    if len(photo_ids) == 1:
        await state.set_state(PhotoUploadStates.waiting_for_prompt_gen_text)
        await message.answer(
            "✅ Фото загружено!\n\n"
            "Опиши, что изменить или какой образ создать — или отправь ещё одно фото.\n\n"
            "Чем понятнее опишешь результат, свет, одежду и фон, тем точнее получится фото.\n\n"
            "<blockquote expandable><b>Примеры запросов:</b>\n\n"
            "• Замени фон на парижское кафе с утренним светом\n"
            "• Переодень в чёрное вечернее платье, мягкий свет студии\n"
            "• Сделай кадр на крыше небоскрёба в Нью-Йорке ночью, ветер и огни города\n"
            "• Объедини людей с двух фото на пляже на закате</blockquote>",
            parse_mode="HTML",
        )
    else:
        await state.set_state(PhotoUploadStates.waiting_for_prompt_gen_text)
        await message.answer(
            "Оба фото загружены! Напиши, что создать или изменить 👇",
        )


@router.message(F.text, PhotoUploadStates.waiting_for_prompt_gen_photo)
async def handle_text_instead_of_prompt_gen_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь отправил текст вместо фото — напоминаем."""
    menu_buttons = ("📸 Создать фотосессию", "🎬 Оживить фото", "Профиль", "Служба заботы", "Назад", "✨ Создать или изменить фото", "✨ Изменить фото", "💫 Новый образ", "🔍 Улучшить кач-во")
    if message.text.startswith("/") or message.text in menu_buttons:
        await state.clear()
        return
    await message.answer("📎 Сначала отправь фото, а потом опиши, что создать или изменить.")


@router.message(F.photo, PhotoUploadStates.waiting_for_prompt_gen_text)
async def handle_prompt_gen_second_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """User sends second photo while in text-waiting state."""
    data = await state.get_data()
    photo_ids = data.get("prompt_gen_photo_ids", [])
    if len(photo_ids) >= 2:
        await message.answer("⚠️ Максимум 2 фото. Напиши свой запрос 👇")
        return
    # Redirect to photo handler
    await handle_prompt_gen_photo(message, state, analytics)


@router.message(F.text, PhotoUploadStates.waiting_for_prompt_gen_text)
async def handle_prompt_gen_text(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """User sent prompt text for generation."""
    prompt = message.text.strip()

    menu_buttons = ("📸 Создать фотосессию", "🎬 Оживить фото", "Профиль", "Служба заботы", "Назад", "✨ Создать или изменить фото", "✨ Изменить фото", "💫 Новый образ", "🔍 Улучшить кач-во")
    if prompt.startswith("/") or prompt in menu_buttons:
        await state.clear()
        return

    if len(prompt) < 3:
        await message.answer("Запрос слишком короткий. Напиши хотя бы несколько слов.")
        return

    if len(prompt) > 1000:
        await message.answer("Запрос слишком длинный (максимум 1000 символов). Сократи и отправь снова.")
        return

    data = await state.get_data()
    photo_ids = data.get("prompt_gen_photo_ids", [])
    if not photo_ids:
        await state.clear()
        await message.answer("⚠️ Фото не найдено. Начни сначала — нажми «✨ Создать или изменить фото».", reply_markup=get_main_menu_keyboard())
        return
    if len(photo_ids) > 2:
        await state.clear()
        logger.warning(
            "[tg=%s] prompt_gen: invalid local photo count before submit: %s",
            message.from_user.id,
            len(photo_ids),
        )
        await message.answer(
            "⚠️ Можно использовать только 1 или 2 фото. Начни заново: нажми «✨ Создать или изменить фото».",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    await state.clear()
    await analytics.track("prompt_generation_submitted", user_id=str(message.from_user.id), properties={"prompt_length": len(prompt), "photo_count": len(photo_ids)})

    await _do_prompt_generation(message, prompt, photo_ids=photo_ids, analytics=analytics)


async def _do_prompt_generation(
    message: Message, prompt: str, photo_ids: list[int],
    telegram_id: int | None = None, analytics: AnalyticsClient | None = None,
):
    """Start prompt generation → poll → send result."""
    t_total = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id
    assert telegram_id is not None

    await message.answer("✨ Обрабатываю запрос и генерирую фото, подожди немного...")

    try:
        gen_result = await backend.generate_prompt(telegram_id=telegram_id, prompt=prompt, photo_ids=photo_ids)
    except Exception as e:
        logger.error(f"Ошибка запуска генерации по промту: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось запустить генерацию. Попробуй позже.")
        return

    if gen_result.get("error") == "no_balance":
        if analytics:
            await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "no_balance_prompt_gen"})
        await message.answer(
            "❌ У тебя закончились генерации!\n\n"
            "Пополни баланс, чтобы продолжить создавать фото.",
            reply_markup=get_buy_keyboard(),
        )
        return

    if gen_result.get("error") == "already_generating":
        await message.answer("⏳ Подожди — предыдущая генерация ещё в процессе.")
        return

    if gen_result.get("error") == "invalid_photo_count":
        await message.answer(
            "⚠️ Нужно отправить 1 или 2 фото. Нажми «✨ Создать или изменить фото» и попробуй снова.",
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
        logger.error(f"Ошибка поллинга задачи {task_id}: {e}", exc_info=True)
        await message.answer("⚠️ Ошибка при ожидании результата. Попробуй позже.")
        return

    status = task_result.get("status")

    if status == "completed":
        results = task_result.get("results", [])
        successful = [r for r in results if r.get("status") == "completed" and r.get("result_url")]

        if not successful:
            failure_message = (
                CONTENT_MODERATION_MESSAGE
                if has_content_moderation_error(task_result)
                else "❌ Генерация не удалась. Попробуй ещё раз."
            )
            await message.answer(failure_message, reply_markup=get_main_menu_keyboard())
            return

        url = successful[0]["result_url"]
        logger.info(f"[tg={telegram_id}] prompt_gen: скачиваю фото, url={url[:120]}")
        try:
            photo_data = await download_photo(url)
        except Exception as e:
            logger.error(f"[tg={telegram_id}] prompt_gen: download failed: {e}", exc_info=True)
            await message.answer("Не удалось скачать фото. Попробуй позже.")
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] prompt_gen: refund failed: {re}", exc_info=True)
            return

        logger.info(f"[tg={telegram_id}] prompt_gen: скачано {len(photo_data)} байт, отправляю в Telegram")
        send_result = await send_photos(message, [photo_data], telegram_id)

        if analytics:
            await analytics.track("prompt_generation_delivered", user_id=str(telegram_id), properties={"task_id": task_id, "success": send_result.failed == 0})

        if send_result.failed > 0:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
            except Exception as re:
                logger.error(f"[tg={telegram_id}] prompt_gen: refund failed: {re}", exc_info=True)

        total_time = time.monotonic() - t_total
        logger.info(f"[tg={telegram_id}] Prompt generation total={total_time:.2f}s")

        await message.answer(
            "✨ Готово! Хочешь ещё — нажми «✨ Создать или изменить фото» снова.",
            reply_markup=get_main_menu_keyboard(),
        )
    elif status == "failed":
        if has_content_moderation_error(task_result):
            await message.answer(CONTENT_MODERATION_MESSAGE, reply_markup=get_main_menu_keyboard())
        else:
            error_msg = task_result.get("error_message", "Неизвестная ошибка")
            await message.answer(f"❌ Генерация не удалась: {error_msg}")
    else:
        await message.answer("⏰ Генерация заняла слишком много времени. Попробуй позже.")
        if task_id:
            try:
                await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=2)
                logger.info(f"[tg={telegram_id}] prompt_gen: refunded 2 generations for poll timeout")
            except Exception as refund_err:
                logger.error(f"[tg={telegram_id}] prompt_gen: timeout refund failed: {refund_err}", exc_info=True)
