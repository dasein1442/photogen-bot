import logging
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.api.backend import backend
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_buy_keyboard
from app.services.analytics_sdk import AnalyticsClient
from app.services.generation_errors import CONTENT_MODERATION_MESSAGE, has_content_moderation_error
from app.services.tg_sender import download_photo, send_video
from app.states.photo import PhotoUploadStates

logger = logging.getLogger(__name__)
router = Router()

ANIMATION_COST = 20
MENU_BUTTONS = {
    "📸 Создать фотосессию",
    "🎬 Оживить фото",
    "🎲 Случайное фото",
    "💫 Новый образ",
    "✨ Изменить фото",
    "🔍 Улучшить кач-во",
    "Профиль",
    "Служба заботы",
    "Назад",
}


@router.message(F.text == "🎬 Оживить фото")
async def handle_animate_photo_button(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Start the photo-to-video flow."""
    await analytics.track("photo_animation_opened", user_id=str(message.from_user.id))
    await state.clear()
    await state.set_state(PhotoUploadStates.waiting_for_animation_photo)
    await message.answer(
        "🎬 <b>Оживить фото</b>\n\n"
        "Превращу фотографию в короткое видео на 5 секунд. Лучше всего подходят чёткие портреты и кадры, "
        "где главный герой хорошо виден.\n\n"
        "📎 Отправь фотографию. После неё я попрошу описать движение.\n\n"
        f"<i>Стоимость: {ANIMATION_COST} генераций.</i>",
        parse_mode="HTML",
    )


@router.message(F.photo, PhotoUploadStates.waiting_for_animation_photo)
async def handle_animation_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Upload one source image, without profile-photo validation."""
    await message.answer("🔄 Загружаю фото...")
    photo = message.photo[-1]
    telegram_id = message.from_user.id

    try:
        file = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        photo_data = file_bytes.read()
    except Exception as e:
        logger.error("Ошибка скачивания фото для анимации: %s", e, exc_info=True)
        await message.answer("⚠️ Не удалось скачать фото. Попробуй ещё раз.")
        return

    try:
        upload_result = await backend.upload_photo_raw(
            telegram_id=telegram_id,
            photo_bytes=photo_data,
            filename=f"{telegram_id}_{photo.file_id}.jpg",
        )
    except Exception as e:
        logger.error("Ошибка загрузки фото для анимации: %s", e, exc_info=True)
        await message.answer("⚠️ Не удалось загрузить фото. Попробуй позже.")
        return

    if not upload_result.get("ok"):
        await message.answer(f"⚠️ {upload_result.get('error', 'Неизвестная ошибка')}")
        return

    await state.set_state(PhotoUploadStates.waiting_for_animation_prompt)
    await state.set_data({"animation_photo_id": upload_result["photo_id"]})
    await analytics.track("photo_animation_photo_uploaded", user_id=str(telegram_id))
    await message.answer(
        "✅ Фото загружено!\n\n"
        "Опиши движение в видео: что происходит в кадре и, если важно, как движется камера.\n\n"
        "<blockquote expandable><b>Примеры:</b>\n\n"
        "• Улыбается и слегка поворачивает голову, волосы мягко колышутся на ветру\n"
        "• Медленно поднимает взгляд в камеру, камера плавно приближается\n"
        "• Идёт вперёд, лёгкий ветер двигает одежду, кинематографичный медленный кадр\n"
        "• Медленно танцует, вокруг мерцают огни вечернего города</blockquote>",
        parse_mode="HTML",
    )


@router.message(F.text, PhotoUploadStates.waiting_for_animation_photo)
async def handle_text_instead_of_animation_photo(message: Message, state: FSMContext):
    if message.text.startswith("/") or message.text in MENU_BUTTONS:
        await state.clear()
        return
    await message.answer("📎 Сначала отправь фотографию, которую нужно оживить.")


@router.message(F.text, PhotoUploadStates.waiting_for_animation_prompt)
async def handle_animation_prompt(message: Message, state: FSMContext, analytics: AnalyticsClient):
    prompt = message.text.strip()
    if prompt.startswith("/") or prompt in MENU_BUTTONS:
        await state.clear()
        return
    if len(prompt) < 3:
        await message.answer("Опиши движение хотя бы несколькими словами.")
        return
    if len(prompt) > 1000:
        await message.answer("Описание слишком длинное: максимум 1000 символов. Сократи и отправь снова.")
        return

    data = await state.get_data()
    photo_id = data.get("animation_photo_id")
    if not photo_id:
        await state.clear()
        await message.answer(
            "⚠️ Фото не найдено. Начни сначала: нажми «🎬 Оживить фото».",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    await state.clear()
    await analytics.track(
        "photo_animation_prompt_submitted",
        user_id=str(message.from_user.id),
        properties={"prompt_length": len(prompt)},
    )
    await _do_photo_animation(message, photo_id=photo_id, prompt=prompt, analytics=analytics)


async def _do_photo_animation(
    message: Message,
    photo_id: int,
    prompt: str,
    telegram_id: int | None = None,
    analytics: AnalyticsClient | None = None,
):
    """Create the animation, wait for the MP4 and deliver it to Telegram."""
    started_at = time.monotonic()
    if telegram_id is None:
        telegram_id = message.from_user.id

    await message.answer("🎬 Оживляю фото. На видео нужно немного больше времени, подожди...")
    try:
        generation = await backend.animate_photo(
            telegram_id=telegram_id,
            photo_id=photo_id,
            prompt=prompt,
        )
    except Exception as e:
        logger.error("Ошибка запуска анимации фото: %s", e, exc_info=True)
        await message.answer("⚠️ Не удалось запустить оживление фото. Попробуй позже.")
        return

    if generation.get("error") == "no_balance":
        if analytics:
            await analytics.track(
                "paywall_shown",
                user_id=str(telegram_id),
                properties={"source": "no_balance_photo_animation"},
            )
        await message.answer(
            f"❌ Для оживления фото нужно {ANIMATION_COST} генераций.\n\nПополни баланс, чтобы продолжить.",
            reply_markup=get_buy_keyboard(),
        )
        return
    if generation.get("error") == "already_generating":
        await message.answer("⏳ Подожди: предыдущая генерация ещё в процессе.")
        return
    if generation.get("error") == "photo_not_found":
        await message.answer("⚠️ Фото не найдено. Отправь его ещё раз и попробуй снова.")
        return
    if generation.get("error") == "invalid_prompt":
        await message.answer("⚠️ Описание движения должно быть от 3 до 1000 символов.")
        return

    task_id = generation.get("task_id")
    if not task_id:
        await message.answer("⚠️ Не удалось запустить оживление фото. Попробуй позже.")
        return

    try:
        task_result = await backend.poll_task(task_id, interval=5, max_attempts=120)
    except Exception as e:
        logger.error("Ошибка ожидания анимации task_id=%s: %s", task_id, e, exc_info=True)
        await message.answer("⚠️ Ошибка при ожидании видео. Генерации вернутся на баланс, если видео не создастся.")
        return

    if has_content_moderation_error(task_result):
        await message.answer(CONTENT_MODERATION_MESSAGE)
        return

    if task_result.get("status") == "completed":
        successful = [
            result for result in task_result.get("results", [])
            if result.get("status") == "completed" and result.get("result_url")
        ]
        if not successful:
            await message.answer(f"❌ Не удалось оживить фото. {ANIMATION_COST} генераций вернулись на баланс.")
            return

        try:
            video_data = await download_photo(successful[0]["result_url"])
        except Exception as e:
            logger.error("[tg=%s] Не удалось скачать видео task_id=%s: %s", telegram_id, task_id, e, exc_info=True)
            refunded = await _refund_video_delivery(telegram_id, task_id)
            await message.answer(
                f"⚠️ Не удалось скачать видео. {ANIMATION_COST} генераций вернулись на баланс."
                if refunded
                else "⚠️ Не удалось скачать видео. Служба заботы уже получила информацию о проблеме."
            )
            return

        delivery = await send_video(message, video_data, telegram_id)
        if delivery.failed:
            refunded = await _refund_video_delivery(telegram_id, task_id)
            await message.answer(
                f"{ANIMATION_COST} генераций вернулись на баланс."
                if refunded
                else "Служба заботы уже получила информацию о проблеме."
            )
            return

        if analytics:
            await analytics.track(
                "photo_animation_delivered",
                user_id=str(telegram_id),
                properties={"task_id": task_id, "duration_seconds": 5},
            )
        logger.info("[tg=%s] Photo animation delivered in %.2fs", telegram_id, time.monotonic() - started_at)
        await message.answer(
            "✅ Готово! Хочешь оживить ещё одно фото? Нажми «🎬 Оживить фото».",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    if task_result.get("status") == "failed":
        await message.answer(f"❌ Не удалось оживить фото. {ANIMATION_COST} генераций вернулись на баланс.")
        return

    refunded = await _refund_video_delivery(telegram_id, task_id)
    await message.answer(
        f"⏰ Видео создаётся слишком долго. {ANIMATION_COST} генераций вернулись на баланс."
        if refunded
        else "⏰ Видео создаётся слишком долго. Служба заботы уже получила информацию о проблеме."
    )


async def _refund_video_delivery(telegram_id: int, task_id: int) -> bool:
    try:
        await backend.refund_delivery(telegram_id=telegram_id, task_id=task_id, failed_count=ANIMATION_COST)
        return True
    except Exception as e:
        logger.error("[tg=%s] Не удалось вернуть генерации за видео task_id=%s: %s", telegram_id, task_id, e, exc_info=True)
        return False
