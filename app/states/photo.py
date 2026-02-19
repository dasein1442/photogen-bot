from aiogram.fsm.state import State, StatesGroup


class PhotoUploadStates(StatesGroup):
    waiting_for_main_photo = State()
    waiting_for_additional_photo = State()
