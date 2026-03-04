from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Купить генерации ⭐️", callback_data="buy_generations")],
        ]
    )


def get_payment_method_keyboard(context: str = "menu") -> InlineKeyboardMarkup:
    """Keyboard with payment method selection: Stars or SBP."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплата звёздами ⭐️", callback_data=f"pm_stars_{context}")],
            [InlineKeyboardButton(text="Картой / СБП 💳", callback_data=f"pm_sbp_{context}")],
        ]
    )
