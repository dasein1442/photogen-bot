import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, LabeledPrice

from app.api.backend import backend
from app.keyboards.common import get_main_menu_keyboard

logger = logging.getLogger(__name__)
router = Router()


async def start_payment_flow(message: Message, telegram_id: int):
    """Start the payment flow: notify backend, get price, send Stars invoice."""
    # Notify backend about payment flow start (fires push events, sets discount timer)
    try:
        await backend.notify_payment_flow(telegram_id)
    except Exception as e:
        logger.error(f"Ошибка уведомления о начале оплаты: {e}")

    # Get current price for this user (server-side, time-based discount)
    try:
        price_data = await backend.get_price(telegram_id)
    except Exception as e:
        logger.error(f"Ошибка получения цены: {e}")
        await message.answer("⚠️ Не удалось получить цену. Попробуй позже.")
        return

    stars = price_data["stars"]
    generations = price_data["generations"]

    await message.bot.send_invoice(
        chat_id=message.chat.id,
        title=f"{generations} генераций",
        description=f"Покупка {generations} генераций для создания AI-фото",
        payload=f"buy_{generations}_{telegram_id}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{generations} генераций", amount=stars)],
    )


@router.callback_query(lambda cb: cb.data == "buy_generations")
async def handle_buy_generations(callback: CallbackQuery):
    """User clicked buy button (from no_balance, profile, etc.)."""
    await callback.answer()
    await start_payment_flow(callback.message, callback.from_user.id)


@router.pre_checkout_query()
async def handle_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Approve pre-checkout query for Stars payment."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message):
    """Handle successful Stars payment — add credits via backend."""
    payment = message.successful_payment
    telegram_id = message.from_user.id

    # Parse payload for generations count: "buy_{generations}_{telegram_id}"
    try:
        parts = payment.invoice_payload.split("_")
        generations = int(parts[1])
    except (IndexError, ValueError):
        generations = 10

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

    await message.answer(
        f"✅ Спасибо за покупку!\n\n"
        f"Начислено: {generations} генераций\n"
        f"Доступно: {remaining} генераций\n\n"
        "Выбирай стиль и создавай фото 👇",
        reply_markup=get_main_menu_keyboard(),
    )
