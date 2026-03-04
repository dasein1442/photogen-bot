import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.keyboards.common import get_main_menu_keyboard
from app.keyboards.payment import get_payment_method_keyboard
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
    """User clicked buy button — show payment method selection."""
    await callback.answer()
    await callback.message.answer(
        "Выбери способ оплаты 👇",
        reply_markup=get_payment_method_keyboard("menu"),
    )


@router.callback_query(lambda cb: cb.data and cb.data.startswith("pm_stars_"))
async def handle_pay_method_stars(callback: CallbackQuery, analytics: AnalyticsClient):
    """User chose Stars payment method."""
    await callback.answer()
    context = callback.data.replace("pm_stars_", "")

    if context == "onboarding":
        # Onboarding paywall — send single-tier invoice with discount
        telegram_id = callback.from_user.id
        try:
            price_data = await backend.get_price(telegram_id, context="onboarding_paywall")
            tier = price_data["tiers"][0]
            stars = tier["stars"]
            generations = tier["generations"]
        except Exception:
            stars = 299
            generations = 20

        await callback.message.bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=f"{generations} генераций",
            description=f"Покупка {generations} генераций для создания AI-фото",
            payload=f"buy_{generations}_{telegram_id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{generations} генераций", amount=stars)],
        )

        if analytics:
            await analytics.track("invoice_sent", user_id=str(telegram_id), properties={"stars": stars, "generations": generations, "source": "onboarding_stars"})
    else:
        # Menu flow — show tier selection
        await start_payment_flow(callback.message, callback.from_user.id, analytics=analytics)


@router.callback_query(lambda cb: cb.data and cb.data.startswith("pm_sbp_"))
async def handle_pay_method_sbp(callback: CallbackQuery, analytics: AnalyticsClient):
    """User chose card/SBP/SberPay — for onboarding (1 tier) go straight to payment link, otherwise show tier selection."""
    await callback.answer()
    context = callback.data.replace("pm_sbp_", "")
    telegram_id = callback.from_user.id

    price_context = "onboarding_paywall" if context == "onboarding" else "menu"
    try:
        price_data = await backend.get_price(telegram_id, context=price_context)
    except Exception as e:
        logger.error(f"Ошибка получения цены: {e}")
        await callback.message.answer("⚠️ Не удалось получить тарифы. Попробуй позже.")
        return

    tiers = price_data.get("tiers", [])
    if not tiers:
        await callback.message.answer("⚠️ Не удалось получить тарифы. Попробуй позже.")
        return

    # Onboarding: 1 tier — skip selection, create payment immediately
    if len(tiers) == 1:
        t = tiers[0]
        gen = t["generations"]
        rubles = t.get("rubles", 0)
        if not rubles:
            await callback.message.answer("⚠️ Тариф недоступен.")
            return

        try:
            result = await backend.create_yookassa_payment(
                telegram_id=telegram_id,
                generations=gen,
                amount_rubles=rubles,
            )
        except Exception as e:
            logger.error(f"Ошибка создания платежа ЮКасса: {e}")
            await callback.message.answer("⚠️ Не удалось создать платёж. Попробуй позже.")
            return

        confirmation_url = result.get("confirmation_url")
        yookassa_id = result.get("yookassa_id")

        if not confirmation_url:
            await callback.message.answer("⚠️ Не удалось получить ссылку на оплату.")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить 💳", url=confirmation_url)],
            [InlineKeyboardButton(text="Проверить оплату ✅", callback_data=f"check_yookassa_{yookassa_id}")],
        ])

        await callback.message.answer(
            f"💳 Оплата: {rubles} ₽ за {gen} генераций\n\n"
            f"Доступны: банковская карта, СБП, SberPay\n\n"
            f"1. Нажми «Оплатить» — откроется страница оплаты\n"
            f"2. Выбери удобный способ и оплати\n"
            f"3. Вернись сюда и нажми «Проверить оплату»",
            reply_markup=keyboard,
        )

        if analytics:
            await analytics.track("sbp_payment_link_sent", user_id=str(telegram_id), properties={
                "amount_rubles": rubles, "generations": gen, "yookassa_id": yookassa_id, "source": context,
            })
        return

    # Menu: multiple tiers — show selection
    buttons = []
    for t in tiers:
        gen = t["generations"]
        rubles = t.get("rubles", 0)
        if not rubles:
            continue
        buttons.append([InlineKeyboardButton(
            text=f"{gen} генераций — {rubles} ₽",
            callback_data=f"sbp_tier_{gen}_{rubles}",
        )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("Выбери пакет генераций 👇", reply_markup=keyboard)


@router.callback_query(lambda cb: cb.data and cb.data.startswith("sbp_tier_"))
async def handle_sbp_tier(callback: CallbackQuery, analytics: AnalyticsClient):
    """User selected an SBP tier — create YooKassa payment and send payment link."""
    await callback.answer()

    try:
        parts = callback.data.split("_")
        generations = int(parts[2])
        rubles = int(parts[3])
    except (IndexError, ValueError):
        await callback.message.answer("⚠️ Ошибка выбора тарифа.")
        return

    telegram_id = callback.from_user.id

    try:
        result = await backend.create_yookassa_payment(
            telegram_id=telegram_id,
            generations=generations,
            amount_rubles=rubles,
        )
    except Exception as e:
        logger.error(f"Ошибка создания платежа ЮКасса: {e}")
        await callback.message.answer("⚠️ Не удалось создать платёж. Попробуй позже.")
        return

    confirmation_url = result.get("confirmation_url")
    yookassa_id = result.get("yookassa_id")

    if not confirmation_url:
        await callback.message.answer("⚠️ Не удалось получить ссылку на оплату.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Оплатить 💳", url=confirmation_url)],
        [InlineKeyboardButton(text="Проверить оплату ✅", callback_data=f"check_yookassa_{yookassa_id}")],
    ])

    await callback.message.answer(
        f"💳 Оплата: {rubles} ₽\n\n"
        f"Доступны: банковская карта, СБП, SberPay\n\n"
        f"1. Нажми «Оплатить» — откроется страница оплаты\n"
        f"2. Выбери удобный способ и оплати\n"
        f"3. Вернись сюда и нажми «Проверить оплату»",
        reply_markup=keyboard,
    )

    if analytics:
        await analytics.track("sbp_payment_link_sent", user_id=str(telegram_id), properties={
            "amount_rubles": rubles, "generations": generations, "yookassa_id": yookassa_id,
        })


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
        # Clear onboarding_paywall state if active
        current_state = await state.get_state()
        if current_state == PhotoUploadStates.onboarding_paywall.state:
            await state.clear()

        # Get fresh user balance
        try:
            user_data = await backend.get_user(telegram_id)
            remaining = user_data.get("generations_remaining", "?")
        except Exception:
            remaining = "?"

        await callback.message.answer(
            f"✅ Оплата прошла!\n\n"
            f"Начислено: {generations} генераций\n"
            f"Доступно: {remaining} генераций\n\n"
            "Выбирай стиль и создавай фото 👇",
            reply_markup=get_main_menu_keyboard(),
        )

        if analytics:
            await analytics.track("sbp_payment_confirmed", user_id=str(telegram_id), properties={
                "yookassa_id": yookassa_id, "generations": generations,
            })

    elif status == "canceled":
        await callback.message.answer("❌ Платёж отменён. Попробуй ещё раз.")

    else:
        # Still pending
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Проверить ещё раз ✅", callback_data=f"check_yookassa_{yookassa_id}")],
        ])
        await callback.message.answer(
            "⏳ Оплата ещё не подтверждена. Если ты уже оплатил — подожди минуту и нажми кнопку ещё раз.",
            reply_markup=keyboard,
        )


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
