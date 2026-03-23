from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Фотосессии")],
            [KeyboardButton(text="Случайное фото"), KeyboardButton(text="ИИ-фотошоп")],
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
