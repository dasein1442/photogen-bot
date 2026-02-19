from aiogram.fsm.state import State, StatesGroup


class PhotoUploadStates(StatesGroup):
    waiting_for_main_photo = State()
    waiting_for_additional_photo = State()


class GenerationStates(StatesGroup):
    waiting_for_photo = State()  # ожидаем фото после выбора пресета
