import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.keyboards.common import get_main_menu_keyboard
from app.services.analytics_sdk import AnalyticsClient
from app.states.photo import PhotoUploadStates

logger = logging.getLogger(__name__)
router = Router()


async def start_payment_flow(message: Message, telegram_id: int, analytics: AnalyticsClient | None = None):
    """Start the payment flow: notify backend, show tier selection."""
    # Notify backend about payment flow start (no push notifications from menu)
    try:
        await backend.notify_payment_flow(telegram_id)
    except Exception as e:
        logger.error(f"Ошибка уведомления о начале оплаты: {e}")

    # Get pricing tiers
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

    # Build tier selection keyboard
    buttons = []
    for t in tiers:
        gen = t["generations"]
        stars = t["stars"]
        buttons.append([InlineKeyboardButton(
            text=f"{gen} генераций — {stars} ⭐️",
            callback_data=f"buy_tier_{gen}_{stars}",
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        "Выбери пакет генераций 👇",
        reply_markup=keyboard,
    )

    if analytics:
        await analytics.track("paywall_shown", user_id=str(telegram_id), properties={"source": "menu", "tiers_count": len(tiers)})


@router.callback_query(lambda cb: cb.data and cb.data.startswith("buy_tier_"))
async def handle_buy_tier(callback: CallbackQuery, analytics: AnalyticsClient):
    """User selected a tier — send Stars invoice."""
    await callback.answer()

    try:
        parts = callback.data.split("_")
        generations = int(parts[2])
        stars = int(parts[3])
    except (IndexError, ValueError):
        await callback.message.answer("⚠️ Ошибка выбора тарифа.")
        return

    telegram_id = callback.from_user.id

    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=f"{generations} генераций",
        description=f"Покупка {generations} генераций для создания AI-фото",
        payload=f"buy_{generations}_{telegram_id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{generations} генераций", amount=stars)],
    )

    if analytics:
        await analytics.track("invoice_sent", user_id=str(telegram_id), properties={"stars": stars, "generations": generations, "source": "menu_tier"})


@router.callback_query(lambda cb: cb.data == "buy_generations")
async def handle_buy_generations(callback: CallbackQuery, analytics: AnalyticsClient):
    """User clicked buy button (from no_balance, profile, etc.)."""
    await callback.answer()
    await start_payment_flow(callback.message, callback.from_user.id, analytics=analytics)


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Approve pre-checkout query for Stars payment."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, state: FSMContext, analytics: AnalyticsClient):
    """Handle successful Stars payment — add credits via backend."""
    payment = message.successful_payment
    telegram_id = message.from_user.id

    # Parse payload for generations count: "buy_{generations}_{telegram_id}"
    try:
        parts = payment.invoice_payload.split("_")
        generations = int(parts[1])
    except (IndexError, ValueError):
        generations = 20

    stars_paid = payment.total_amount

    try:
        result = await backend.add_credits(
            telegram_id=telegram_id,
            generations=generations,
            comment=f"Stars payment: {stars_paid} XTR",
        )
        remaining = result.get("generations_remaining", "?")
    except Exception as e:
        logger.error(f"Ошибка добавления кредитов после оплаты: {e}")
        await message.answer(
            "⚠️ Оплата прошла, но не удалось начислить генерации. "
            "Обратись в поддержку: @fotushkasupport"
        )
        return

    await analytics.track("payment_completed", user_id=str(message.from_user.id), properties={"stars_paid": message.successful_payment.total_amount, "generations": generations, "telegram_payment_charge_id": message.successful_payment.telegram_payment_charge_id})

    # Clear onboarding_paywall state if active
    current_state = await state.get_state()
    if current_state == PhotoUploadStates.onboarding_paywall.state:
        await state.clear()

    await message.answer(
        f"✅ Спасибо за покупку!\n\n"
        f"Начислено: {generations} генераций\n"
        f"Доступно: {remaining} генераций\n\n"
        "Выбирай стиль и создавай фото 👇",
        reply_markup=get_main_menu_keyboard(),
    )
