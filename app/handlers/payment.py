import logging

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.keyboards.common import get_main_menu_keyboard
from app.services.analytics_sdk import AnalyticsClient
from app.states.photo import PhotoUploadStates

logger = logging.getLogger(__name__)
router = Router()


async def _create_and_send_payment(message, telegram_id: int, generations: int, rubles: int, analytics: AnalyticsClient | None = None, source: str = "menu"):
    """Create YooKassa payment and send payment link to user."""
    try:
        result = await backend.create_yookassa_payment(
            telegram_id=telegram_id,
            generations=generations,
            amount_rubles=rubles,
        )
    except Exception as e:
        logger.error(f"Ошибка создания платежа ЮКасса: {e}")
        await message.answer("⚠️ Не удалось создать платёж. Попробуй позже.")
        return

    confirmation_url = result.get("confirmation_url")
    yookassa_id = result.get("yookassa_id")

    if not confirmation_url:
        await message.answer("⚠️ Не удалось получить ссылку на оплату.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить 💳", url=confirmation_url)],
        [InlineKeyboardButton(text="Проверить оплату ✅", callback_data=f"check_yookassa_{yookassa_id}")],
    ])

    await message.answer(
        f"Оплата {rubles}₽\n\n"
        f"Вы оплачиваете: «Доступ в бота и {generations} генераций "
        f"(примерно {generations} фотографий)».\n\n"
        f"Мы не имеем доступа к вашим личным и платежным данным. "
        f"Переходя к оплате, вы подтверждаете ознакомление и согласие с нашим "
        f'<a href="http://38.180.30.173/pages/terms.html">пользовательским соглашением</a> и '
        f'<a href="http://38.180.30.173/pages/privacy.html">политикой конфиденциальности</a>.\n\n'
        f"Генерации — валюта нашего сервиса.\n\n"
        f"В случае возникновения проблем обращайтесь в "
        f'<a href="https://t.me/IIUSNO">чат поддержки</a>.',
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    if analytics:
        await analytics.track("payment_link_sent", user_id=str(telegram_id), properties={
            "amount_rubles": rubles, "generations": generations, "yookassa_id": yookassa_id, "source": source,
        })


async def start_payment_flow(message, telegram_id: int, analytics: AnalyticsClient | None = None):
    """Start the payment flow: show tier selection in rubles."""
    try:
        await backend.notify_payment_flow(telegram_id)
    except Exception as e:
        logger.error(f"Ошибка уведомления о начале оплаты: {e}")

    try:
        price_data = await backend.get_price(telegram_id, context="menu")
    except Exception as e:
        logger.error(f"Ошибка получения цены: {e}")
        await message.answer("⚠️ Не удалось получить цену. Попробуй позже.")
        return

    tiers = price_data.get("tiers", [])
    if not tiers:
        await message.answer("⚠️ Не удалось получить тарифы. Попробуй позже.")
        return

    buttons = []
    for t in tiers:
        gen = t["generations"]
        rubles = t.get("rubles", 0)
        if not rubles:
            continue
        buttons.append([InlineKeyboardButton(
            text=f"{gen} генераций — {rubles} ₽",
            callback_data=f"buy_tier_{gen}_{rubles}",
        )])

    if not buttons:
        await message.answer("⚠️ Нет доступных тарифов. Попробуй позже.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выбери пакет генераций 👇", reply_markup=keyboard)

    if analytics:
        await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "menu", "tiers_count": len(buttons)})


async def start_onboarding_payment(message, telegram_id: int, state: FSMContext, analytics: AnalyticsClient | None = None):
    """Create onboarding payment directly (single tier, no selection needed)."""
    try:
        price_data = await backend.get_price(telegram_id, context="onboarding_paywall")
        tier = price_data["tiers"][0]
        rubles = tier.get("rubles", 0)
        generations = tier["generations"]
    except Exception as e:
        logger.error(f"Ошибка получения цены онбординга: {e}")
        rubles = 389
        generations = 20

    if not rubles:
        await message.answer("⚠️ Тариф недоступен.")
        return

    await state.set_state(PhotoUploadStates.onboarding_paywall)
    await _create_and_send_payment(message, telegram_id, generations, rubles, analytics, source="onboarding")


@router.callback_query(lambda cb: cb.data == "buy_generations")
async def handle_buy_generations(callback: CallbackQuery, analytics: AnalyticsClient):
    """User clicked buy button — show tier selection in rubles."""
    await callback.answer()
    await start_payment_flow(callback.message, callback.from_user.id, analytics=analytics)


@router.callback_query(lambda cb: cb.data and cb.data.startswith("buy_tier_"))
async def handle_buy_tier(callback: CallbackQuery, analytics: AnalyticsClient):
    """User selected a tier — create YooKassa payment."""
    await callback.answer()

    try:
        parts = callback.data.split("_")
        generations = int(parts[2])
        rubles = int(parts[3])
    except (IndexError, ValueError):
        await callback.message.answer("⚠️ Ошибка выбора тарифа.")
        return

    await _create_and_send_payment(callback.message, callback.from_user.id, generations, rubles, analytics, source="menu_tier")


@router.callback_query(lambda cb: cb.data and cb.data.startswith("check_yookassa_"))
async def handle_check_yookassa(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """User clicked 'Check payment' — verify YooKassa payment status."""
    await callback.answer()
    yookassa_id = callback.data.replace("check_yookassa_", "")
    telegram_id = callback.from_user.id

    try:
        result = await backend.check_yookassa_payment(telegram_id, yookassa_id)
    except Exception as e:
        logger.error(f"Ошибка проверки платежа ЮКасса: {e}")
        await callback.message.answer("⚠️ Не удалось проверить статус. Попробуй ещё раз.")
        return

    if not result.get("found"):
        await callback.message.answer("⚠️ Платёж не найден.")
        return

    status = result.get("status")
    generations = result.get("generations", 0)

    if status == "succeeded":
        current_state = await state.get_state()
        if current_state == PhotoUploadStates.onboarding_paywall.state:
            await state.clear()

        try:
            user_data = await backend.get_user(telegram_id)
            remaining = user_data.get("generations_remaining", "?")
        except Exception:
            remaining = "?"

        await callback.message.answer(
            f"✅ Оплата прошла!\n\n"
            f"Тебе доступно {remaining} генераций — выбирай стиль и создавай фото 👇",
            reply_markup=get_main_menu_keyboard(),
        )

        if analytics:
            await analytics.track("payment_confirmed", user_id=str(telegram_id), properties={
                "yookassa_id": yookassa_id, "generations": generations,
            })

    elif status == "canceled":
        await callback.message.answer("❌ Платёж отменён. Попробуй ещё раз.")

    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Проверить ещё раз ✅", callback_data=f"check_yookassa_{yookassa_id}")],
        ])
        await callback.message.answer(
            "⏳ Оплата ещё не подтверждена. Если ты уже оплатил — подожди минуту и нажми кнопку ещё раз.",
            reply_markup=keyboard,
        )
