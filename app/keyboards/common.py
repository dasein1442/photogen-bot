from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Галерея образов")],
            [KeyboardButton(text="Случайное фото"), KeyboardButton(text="Фотосессии")],
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Служба заботы")],
        ],
        resize_keyboard=True
    )


def get_profile_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Приобрести генерации")],
            [KeyboardButton(text="Установить новое фото")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True
    )


def get_photo_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Основное", callback_data="photo_main"),
                InlineKeyboardButton(text="Дополнительное", callback_data="photo_additional")
            ],
        ]
    )
