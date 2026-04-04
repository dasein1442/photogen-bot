import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, FSInputFile, InputMediaPhoto

from app.api.backend import backend
from app.keyboards.onboarding import get_welcome_keyboard, get_more_examples_keyboard, get_gender_choice_keyboard
from app.services.analytics_sdk import AnalyticsClient
from app.services.yandex_metrika import metrika
from app.states.photo import PhotoUploadStates

logger = logging.getLogger(__name__)
router = Router()
METRIKA_DEEP_LINK_PREFIX = "yd_"
DIRECT_BOT_DEEP_LINK_PREFIX = "ydb_"

ONBOARDING_PUSH_SLUGS = {
    "onboarding_reminder_1",
    "onboarding_reminder_2",
}
PAYMENT_PUSH_OFFERS = {
    "onboarding_paywall_reminder_1": {"generations": 20, "rubles": 289, "source": "onboarding_paywall_reminder_1"},
    "onboarding_paywall_reminder_2": {"generations": 10, "rubles": 189, "source": "onboarding_paywall_reminder_2"},
    "onboarding_paywall_reminder_3": {"generations": 10, "rubles": 99, "source": "onboarding_paywall_reminder_3"},
    "first_payment_discount": {"generations": 20, "rubles": 289, "source": "first_payment_discount"},
}

WELCOME_PROMO_IMAGE_DIR = Path(__file__).resolve().parents[1] / "assets"
WELCOME_PROMO_IMAGE_CANDIDATES = (
    "welcome_promo.png",
    "welcome_promo.jpg",
    "welcome_promo.jpeg",
    "welcome_promo.png.jpg",
)
TRY_NOW_IMAGE_PATH = WELCOME_PROMO_IMAGE_DIR / "welocme_one_generation.jpg"
WELCOME_EXAMPLE_IMAGE_PATHS = (
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_1.jpg",
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_2.jpg",
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_3.jpg",
    WELCOME_PROMO_IMAGE_DIR / "welcome_example_4.jpg",
)


def _parse_deep_link(message: Message) -> str | None:
    """Extract deep link argument from /start command text."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1] if len(parts) > 1 else None


def _parse_metrika_deep_link(deep_link: str | None) -> tuple[str | None, str | None]:
    """Extract source and ClientId from yd_<source>_<client_id> deep links."""
    if not deep_link or not deep_link.startswith(METRIKA_DEEP_LINK_PREFIX):
        return deep_link, None

    payload = deep_link.removeprefix(METRIKA_DEEP_LINK_PREFIX)
    source, separator, client_id = payload.rpartition("_")
    if not separator or not source or not client_id.isdigit():
        logger.warning("Malformed Metrika deep link: %r", deep_link[:80])
        return "landing", None

    return source, client_id


def _parse_direct_bot_deep_link(deep_link: str | None) -> str | None:
    if not deep_link or not deep_link.startswith(DIRECT_BOT_DEEP_LINK_PREFIX):
        return None

    suffix = deep_link.removeprefix(DIRECT_BOT_DEEP_LINK_PREFIX)
    if len(suffix) < 8 or not all(ch.isalnum() or ch in {"_", "-"} for ch in suffix):
        logger.warning("Malformed direct bot deep link: %r", deep_link[:80])
        return None

    return deep_link


def _analytics_deep_link(
    deep_link: str | None,
    source: str | None,
    client_id: str | None,
    direct_bot_token: str | None,
) -> str:
    if client_id:
        return f"{METRIKA_DEEP_LINK_PREFIX}{source or 'landing'}"
    if direct_bot_token:
        return f"{DIRECT_BOT_DEEP_LINK_PREFIX}{source or 'direct'}"
    return deep_link or "none"


async def _report_bot_started_to_metrika_by_client_id(telegram_id: int, source: str | None, client_id: str) -> None:
    try:
        await metrika.send_bot_started_by_client_id(client_id=client_id, source=source, telegram_id=telegram_id)
    except Exception as exc:
        logger.error("Failed to upload bot_started to Yandex Metrika for tg=%s: %s", telegram_id, exc, exc_info=True)


async def _report_bot_started_to_metrika_by_yclid(telegram_id: int, source: str | None, yclid: str) -> None:
    try:
        await metrika.send_bot_started_by_yclid(yclid=yclid, source=source, telegram_id=telegram_id)
    except Exception as exc:
        logger.error("Failed to upload bot_started to Yandex Metrika for tg=%s: %s", telegram_id, exc, exc_info=True)


async def _show_welcome(message: Message):
    """Show the welcome message with promo image."""
    welcome_text = (
        "<b>Привет</b> 👋\n\n"
        "Ты в <b>Кадрице</b> — боте, который делает из твоего фото профессиональные снимки с помощью ИИ ✨\n\n"
        "Загрузи одно селфи — и нейросеть создаст <b>реалистичные фотосессии</b>: на яхте, в деловом образе, на обложке журнала или даже в стиле селебрити 💅\n\n"
        "<b>Попробуй прямо сейчас — это займёт минуту!</b>"
    )

    promo_image_path = next(
        (WELCOME_PROMO_IMAGE_DIR / name for name in WELCOME_PROMO_IMAGE_CANDIDATES if (WELCOME_PROMO_IMAGE_DIR / name).exists()),
        None,
    )

    if promo_image_path:
        await message.answer_photo(
            photo=FSInputFile(str(promo_image_path)),
            caption=welcome_text,
            reply_markup=get_welcome_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            welcome_text,
            reply_markup=get_welcome_keyboard(),
            parse_mode="HTML",
        )


async def _send_onboarding_paywall(message: Message, telegram_id: int, state: FSMContext):
    """Show paywall for user who completed onboarding but hasn't purchased. Go directly to payment."""
    from app.handlers.payment import start_onboarding_payment
    await start_onboarding_payment(message, telegram_id, state)


async def _show_upload_photo_prompt(message: Message, state: FSMContext):
    """Show the 'upload photo' prompt for returning users."""
    data = await state.get_data()
    onboarding_gender = data.get("onboarding_gender", "female")
    gender_label = "женский" if onboarding_gender == "female" else "мужской"
    try_now_text = (
        f"🔥 Давай покажу твой первый {gender_label} образ!\n\n"
        "Отправь 1 фото — лучше всего селфи с хорошим светом, без фильтров и других людей."
    )

    if TRY_NOW_IMAGE_PATH.exists():
        await message.answer_photo(
            photo=FSInputFile(str(TRY_NOW_IMAGE_PATH)),
            caption=try_now_text,
        )
    else:
        await message.answer(try_now_text)

    await state.update_data(onboarding_mode=True, onboarding_gender=onboarding_gender)
    await state.set_state(PhotoUploadStates.waiting_for_main_photo)


async def _show_gender_choice_prompt(message: Message, state: FSMContext):
    await state.update_data(onboarding_mode=True)
    await message.answer(
        "Выбери пол, чтобы мы сразу подстроили первый результат под подходящий образ.",
        reply_markup=get_gender_choice_keyboard(),
    )


async def _show_selfie_prompt(message: Message, state: FSMContext, onboarding_gender: str):
    try_now_text = (
        "🔥 Отлично, теперь пришли одно селфи.\n\n"
        "Лучше всего фото с хорошим светом, без фильтров и других людей."
    )

    if TRY_NOW_IMAGE_PATH.exists():
        await message.answer_photo(
            photo=FSInputFile(str(TRY_NOW_IMAGE_PATH)),
            caption=try_now_text,
        )
    else:
        await message.answer(try_now_text)

    await state.update_data(onboarding_mode=True, onboarding_gender=onboarding_gender)
    await state.set_state(PhotoUploadStates.waiting_for_main_photo)


async def _register_user(message: Message, source: str | None = None) -> dict:
    """Register user on backend (idempotent). Returns result dict or empty on error."""
    user = message.from_user
    try:
        t0 = time.monotonic()
        result = await backend.register_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            source=source,
        )
        logger.info(f"[tg={user.id}] register_user took {time.monotonic() - t0:.2f}s")
        return result
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя {user.id}: {e}")
        return {}


async def _check_onboarding_paywall(message: Message, state: FSMContext) -> bool:
    """Check if user completed onboarding but hasn't purchased. Returns True if paywall shown."""
    try:
        t0 = time.monotonic()
        user_data = await backend.get_user(telegram_id=message.from_user.id)
        logger.info(f"[tg={message.from_user.id}] get_user took {time.monotonic() - t0:.2f}s")
        user_info = user_data.get("user", {})
        if user_info.get("onboarding_completed") and not user_info.get("has_purchased"):
            await _send_onboarding_paywall(message, message.from_user.id, state)
            return True
    except Exception:
        pass
    return False


async def _resume_onboarding_from_user_state(message: Message, state: FSMContext) -> None:
    try:
        user_data = await backend.get_user(telegram_id=message.from_user.id)
    except Exception as e:
        logger.error(f"Не удалось загрузить пользователя для onboarding resume {message.from_user.id}: {e}")
        await _show_gender_choice_prompt(message, state)
        return

    user_info = user_data.get("user", {})
    if user_info.get("onboarding_completed") and not user_info.get("has_purchased"):
        await _send_onboarding_paywall(message, message.from_user.id, state)
        return

    gender = user_info.get("gender")
    await state.clear()

    if gender in {"female", "male"}:
        await _show_selfie_prompt(message, state, gender)
        return

    await _show_gender_choice_prompt(message, state)


async def _dedup_start(message: Message, state: FSMContext) -> bool:
    """Returns True if this is a duplicate /start within 5 seconds (should be skipped)."""
    data = await state.get_data()
    last_start_date = data.get("_last_start_date")
    if last_start_date and (message.date - last_start_date) < timedelta(seconds=5):
        return True
    await state.update_data(_last_start_date=message.date)
    return False


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Single /start handler — routes by deep link argument value."""
    user = message.from_user
    deep_link = _parse_deep_link(message)
    parsed_source, metrika_client_id = _parse_metrika_deep_link(deep_link)
    direct_bot_token = _parse_direct_bot_deep_link(deep_link)
    safe_deep_link = deep_link
    if metrika_client_id:
        safe_deep_link = f"{METRIKA_DEEP_LINK_PREFIX}{parsed_source}_<client_id>"
    elif direct_bot_token:
        safe_deep_link = f"{DIRECT_BOT_DEEP_LINK_PREFIX}<token>"
    logger.info(
        "handle_start: user=%s, deep_link=%r, source=%r, metrika_client_id=%s, direct_bot_token=%s",
        user.id,
        safe_deep_link,
        "direct" if direct_bot_token else parsed_source,
        bool(metrika_client_id),
        bool(direct_bot_token),
    )

    if await _dedup_start(message, state):
        logger.info(f"handle_start SKIPPED (dedup): user={user.id}")
        return

    if deep_link == "upload_photo":
        await _handle_start_upload_photo(message, state, analytics)
    elif deep_link == "buy":
        await _handle_start_buy(message, state, analytics)
    elif deep_link == "discount":
        await _handle_start_discount(message, state, analytics)
    elif deep_link in {"photosessions", "photosession"}:
        await _handle_start_photosessions(message, state, analytics, deep_link)
    elif deep_link and deep_link.startswith("p_"):
        await _handle_start_push(message, state, analytics, deep_link)
    elif deep_link and deep_link.startswith("c_"):
        await _handle_start_campaign(message, state, analytics, deep_link)
    else:
        await _handle_start_generic(
            message,
            state,
            analytics,
            deep_link,
            parsed_source,
            metrika_client_id,
            direct_bot_token,
        )


async def _handle_start_upload_photo(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Deep link: upload_photo — go straight to photo upload for returning users."""
    result = await _register_user(message, source=None)

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={
        "deep_link": "upload_photo", "source": "upload_photo",
    })

    # New user — show full welcome instead of jumping to upload
    is_new = result.get("user", {}).get("is_new", False)
    if is_new:
        await state.clear()
        return await _show_welcome(message)

    if await _check_onboarding_paywall(message, state):
        return

    await _show_upload_photo_prompt(message, state)


async def _handle_start_buy(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Deep link: buy — go straight to payment."""
    await _register_user(message, source=None)

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={
        "deep_link": "buy", "source": "buy",
    })

    if await _check_onboarding_paywall(message, state):
        return

    from app.handlers.payment import start_payment_flow
    await start_payment_flow(message, message.from_user.id, analytics=analytics)


async def _handle_start_discount(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Deep link: discount — special offer 20 generations for 289₽."""
    await _register_user(message, source=None)

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={
        "deep_link": "discount", "source": "discount",
    })

    from app.handlers.payment import _create_and_send_payment
    await _create_and_send_payment(
        message, message.from_user.id,
        generations=20, rubles=289,
        analytics=analytics, source="discount",
    )


async def _handle_start_campaign(message: Message, state: FSMContext, analytics: AnalyticsClient, deep_link: str):
    """Deep link: c_<campaign> — campaign click-through, route to photosessions."""
    await _register_user(message, source=None)

    await analytics.track("campaign_click", user_id=str(message.from_user.id), properties={
        "campaign": deep_link,
    })
    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={
        "deep_link": deep_link, "source": None,
    })

    await state.clear()

    if await _check_onboarding_paywall(message, state):
        return

    from app.handlers.photosessions import handle_photosessions
    await handle_photosessions(message, analytics)


async def _handle_start_photosessions(message: Message, state: FSMContext, analytics: AnalyticsClient, deep_link: str):
    """Deep link: photosessions — open photosessions flow instead of welcome."""
    await _register_user(message, source=None)

    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={
        "deep_link": deep_link, "source": None,
    })

    await state.clear()

    if await _check_onboarding_paywall(message, state):
        return

    from app.handlers.photosessions import handle_photosessions
    await handle_photosessions(message, analytics)


async def _handle_start_push(message: Message, state: FSMContext, analytics: AnalyticsClient, deep_link: str):
    """Deep link: p_<slug> — route by push type."""
    await _register_user(message, source=None)
    push_slug = deep_link.removeprefix("p_")

    await analytics.track("push_click", user_id=str(message.from_user.id), properties={
        "push_slug": push_slug,
        "deep_link": deep_link,
    })
    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={
        "deep_link": deep_link, "source": None,
    })

    await state.clear()

    if push_slug in ONBOARDING_PUSH_SLUGS:
        await _resume_onboarding_from_user_state(message, state)
        return

    payment_offer = PAYMENT_PUSH_OFFERS.get(push_slug)
    if payment_offer:
        from app.handlers.payment import _create_and_send_payment
        await _create_and_send_payment(
            message,
            message.from_user.id,
            generations=payment_offer["generations"],
            rubles=payment_offer["rubles"],
            analytics=analytics,
            source=payment_offer["source"],
        )
        return

    if await _check_onboarding_paywall(message, state):
        return

    from app.handlers.photosessions import handle_photosessions
    await handle_photosessions(message, analytics)


async def _handle_start_generic(
    message: Message,
    state: FSMContext,
    analytics: AnalyticsClient,
    deep_link: str | None,
    parsed_source: str | None = None,
    metrika_client_id: str | None = None,
    direct_bot_token: str | None = None,
):
    """Default /start — welcome screen. External deep link is used as source for tracking."""
    # Internal deep links are navigation actions, not traffic sources
    _internal_links = {"photosessions", "photosession", "upload_photo", "buy", "discount"}
    source = parsed_source if parsed_source is not None else deep_link
    source = None if source in _internal_links else source
    metrika_yclid = None
    should_track_direct_bot_start = False

    if direct_bot_token:
        source = "direct"
        try:
            claim = await backend.claim_direct_bot_start(direct_bot_token, message.from_user.id)
            source = claim.get("source") or source
            metrika_yclid = claim.get("yclid")
            should_track_direct_bot_start = bool(claim.get("should_track") and metrika_yclid)
        except Exception as exc:
            logger.error(
                "Failed to claim direct bot start token for tg=%s: %s",
                message.from_user.id,
                exc,
                exc_info=True,
            )

    result = await _register_user(message, source=source)

    t0 = time.monotonic()
    await analytics.track("bot_start", user_id=str(message.from_user.id), properties={
        "deep_link": _analytics_deep_link(deep_link, source, metrika_client_id, direct_bot_token),
        "source": source,
        "has_metrika_client_id": bool(metrika_client_id),
        "has_metrika_yclid": bool(metrika_yclid),
    })
    logger.info(f"[tg={message.from_user.id}] analytics.track took {time.monotonic() - t0:.2f}s")

    if metrika_client_id:
        asyncio.create_task(
            _report_bot_started_to_metrika_by_client_id(message.from_user.id, source, metrika_client_id),
            name=f"metrika-bot-started-{message.from_user.id}",
        )
    elif should_track_direct_bot_start and metrika_yclid:
        asyncio.create_task(
            _report_bot_started_to_metrika_by_yclid(message.from_user.id, source, metrika_yclid),
            name=f"metrika-bot-started-direct-{message.from_user.id}",
        )

    # Clear any stale FSM state (e.g. onboarding_paywall) so buttons work
    await state.clear()

    if await _check_onboarding_paywall(message, state):
        return

    t0 = time.monotonic()
    await _show_welcome(message)
    logger.info(f"[tg={message.from_user.id}] _show_welcome took {time.monotonic() - t0:.2f}s")


@router.callback_query(lambda callback: callback.data == "more_examples")
async def handle_more_examples(callback: CallbackQuery, analytics: AnalyticsClient):
    await analytics.track("examples_viewed", user_id=str(callback.from_user.id))
    await callback.message.delete()

    existing_example_images = [path for path in WELCOME_EXAMPLE_IMAGE_PATHS if path.exists()]

    if existing_example_images:
        await callback.message.answer_media_group(
            media=[InputMediaPhoto(media=FSInputFile(str(path))) for path in existing_example_images],
        )

    await callback.message.answer(
        "Вау, посмотри на эти кадры 🤯\n"
        "Первое фото — настоящее, а всё остальное создала нейросеть!\n\n"
        "Представь, как твои соцсети будут выглядеть с такими снимками 😎\n"
        "Реалистично, стильно и с вайбом настоящей фотосессии.\n\n"
        "Хочешь такие же?\n"
        "👉 Попробуй прямо сейчас — загрузить свои фото",
        reply_markup=get_more_examples_keyboard()
    )

    await callback.answer()


@router.callback_query(lambda callback: callback.data == "try_now")
async def handle_try_now(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    await analytics.track("onboarding_try_now_clicked", user_id=str(callback.from_user.id))
    await _show_gender_choice_prompt(callback.message, state)

    await callback.answer()


@router.callback_query(lambda callback: callback.data in {"onboarding_gender_female", "onboarding_gender_male"})
async def handle_onboarding_gender_choice(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    onboarding_gender = callback.data.removeprefix("onboarding_gender_")

    await analytics.track(
        "onboarding_gender_selected",
        user_id=str(callback.from_user.id),
        properties={"gender": onboarding_gender},
    )

    try:
        await backend.set_gender(callback.from_user.id, onboarding_gender)
    except Exception as e:
        logger.error(f"Ошибка сохранения onboarding gender для {callback.from_user.id}: {e}", exc_info=True)
        await callback.answer("⚠️ Не удалось сохранить выбор. Попробуй ещё раз.", show_alert=True)
        return

    await state.update_data(onboarding_mode=True, onboarding_gender=onboarding_gender)

    await _show_selfie_prompt(callback.message, state, onboarding_gender)

    await callback.answer()
