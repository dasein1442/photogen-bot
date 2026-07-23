import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, URLInputFile
from aiogram.fsm.context import FSMContext

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient

logger = logging.getLogger(__name__)
router = Router()

# Mapping type key -> display label
PS_TYPES = {
    "female": "👩 Женская",
    "male": "👨 Мужская",
    "couple": "👫 Парная",
}

PHOTOSESSIONS_PAGE_SIZE = 18
PHOTOSESSIONS_COLUMNS = 2


def _type_selection_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа фотосессии."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👩 Женская", callback_data="ps_type_female")],
        [InlineKeyboardButton(text="👨 Мужская", callback_data="ps_type_male")],
        [InlineKeyboardButton(text="👫 Парная", callback_data="ps_type_couple")],
    ])


def _photosession_list_keyboard(photosessions: list[dict], ps_type: str, page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура списка фотосессий с пагинацией."""
    buttons = []
    total_pages = max(1, (len(photosessions) + PHOTOSESSIONS_PAGE_SIZE - 1) // PHOTOSESSIONS_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_items = photosessions[page * PHOTOSESSIONS_PAGE_SIZE:(page + 1) * PHOTOSESSIONS_PAGE_SIZE]

    for index in range(0, len(page_items), PHOTOSESSIONS_COLUMNS):
        row = []
        for ps in page_items[index:index + PHOTOSESSIONS_COLUMNS]:
            name = ps.get("name") or f"Фотосессия {ps['id']}"
            row.append(InlineKeyboardButton(text=name, callback_data=f"ps_view_{ps['id']}"))
        buttons.append(row)

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"ps_page_{ps_type}_{page - 1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="⬅️", callback_data="ps_back_to_types"))

    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"ps_page_{ps_type}_{page + 1}"))
    else:
        nav_buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"ps_page_{ps_type}_{page}"))
    buttons.append(nav_buttons)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _photosession_page_from_callback(callback_data: str) -> tuple[str, int] | None:
    """Parse ps_page_<type>_<page> callback data."""
    parts = callback_data.rsplit("_", 1)
    if len(parts) != 2:
        return None
    prefix, page_text = parts
    if not prefix.startswith("ps_page_") or not page_text.isdigit():
        return None
    ps_type = prefix.replace("ps_page_", "", 1)
    return ps_type, int(page_text)


def _generation_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "генерацию"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "генерации"
    return "генераций"


@router.message(F.text == "📸 Создать фотосессию")
async def handle_photosessions(message: Message, analytics: AnalyticsClient):
    await analytics.track("photosessions_viewed", user_id=str(message.from_user.id))

    await message.answer(
        "📸 Готовые фотосессии — наш главный инструмент.\n"
        "Выбери тип, внутри — готовые сценарии.\n"
        "Каждая фотосессия списывает столько генераций, сколько фото входит в набор.\n\n"
        "Для мужской или парной нужно загрузить фото партнёра в профиле.\n\n"
        "Выбери тип:",
        reply_markup=_type_selection_keyboard(),
    )


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_type_"))
async def handle_type_selection(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    """Пользователь выбрал тип фотосессии."""
    ps_type = callback.data.replace("ps_type_", "")  # female, male, couple

    await analytics.track(
        "photosession_type_selected",
        user_id=str(callback.from_user.id),
        properties={"type": ps_type},
    )

    # Сохраняем тип в FSM state data для дальнейшего использования
    await state.update_data(ps_type=ps_type, ps_page=0)

    try:
        photosessions = await backend.get_photosessions(type=ps_type)
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий (type={ps_type}): {e}")
        await callback.answer("⚠️ Не удалось загрузить фотосессии. Попробуй позже.")
        return

    type_label = PS_TYPES.get(ps_type, ps_type)

    if not photosessions:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="ps_back_to_types")],
        ])
        try:
            await callback.message.edit_text(
                f"{type_label} — пока нет доступных фотосессий. Заходи позже!",
                reply_markup=keyboard,
            )
        except Exception:
            await callback.message.answer(
                f"{type_label} — пока нет доступных фотосессий. Заходи позже!",
                reply_markup=keyboard,
            )
        await callback.answer()
        return

    try:
        await callback.message.edit_text(
            f"{type_label} — выбери фотосессию 📸👇",
            reply_markup=_photosession_list_keyboard(photosessions, ps_type),
        )
    except Exception:
        await callback.message.answer(
            f"{type_label} — выбери фотосессию 📸👇",
            reply_markup=_photosession_list_keyboard(photosessions, ps_type),
        )
    await callback.answer()


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_page_"))
async def handle_photosession_page(callback: CallbackQuery, state: FSMContext):
    parsed = _photosession_page_from_callback(callback.data)
    if parsed is None:
        await callback.answer("⚠️ Ошибка навигации.")
        return

    ps_type, page = parsed
    await state.update_data(ps_type=ps_type, ps_page=page)

    try:
        photosessions = await backend.get_photosessions(type=ps_type)
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий (type={ps_type}, page={page}): {e}")
        await callback.answer("⚠️ Не удалось загрузить фотосессии. Попробуй позже.")
        return

    type_label = PS_TYPES.get(ps_type, ps_type)
    try:
        await callback.message.edit_text(
            f"{type_label} — выбери фотосессию 📸👇",
            reply_markup=_photosession_list_keyboard(photosessions, ps_type, page=page),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"Ошибка обновления страницы фотосессий (type={ps_type}, page={page}): {e}")
            await callback.answer("⚠️ Не удалось обновить список.")
            return
        await callback.answer("Это последняя страница")
        return
    except Exception as e:
        logger.error(f"Ошибка обновления страницы фотосессий (type={ps_type}, page={page}): {e}")
        await callback.answer("⚠️ Не удалось обновить список.")
        return
    await callback.answer()


@router.callback_query(lambda cb: cb.data == "ps_back_to_types")
async def handle_back_to_types(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору типа фотосессии."""
    try:
        await callback.message.edit_text(
            "Выберите тип фотосессии:",
            reply_markup=_type_selection_keyboard(),
        )
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            "Выберите тип фотосессии:",
            reply_markup=_type_selection_keyboard(),
        )
    await callback.answer()


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_view_"))
async def handle_photosession_view(callback: CallbackQuery, state: FSMContext, analytics: AnalyticsClient):
    photosession_id = int(callback.data.split("_")[2])

    # Получаем тип из state data
    data = await state.get_data()
    ps_type = data.get("ps_type")

    try:
        photosessions = await backend.get_photosessions(type=ps_type)
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await callback.answer("⚠️ Не удалось загрузить фотосессию.")
        return

    ps = next((p for p in photosessions if p["id"] == photosession_id), None)
    if ps is None:
        await callback.answer("⚠️ Фотосессия не найдена.")
        return

    await analytics.track("photosession_viewed", user_id=str(callback.from_user.id), properties={"photosession_id": photosession_id, "type": ps_type})

    name = ps.get("name", f"Фотосессия {photosession_id}")
    description = ps.get("description", "")
    example_url = ps.get("example")
    preset_count = ps.get("preset_count")

    # Сохраняем тип и цену фотосессии для purchase gate перед загрузкой фото.
    actual_type = ps.get("type", ps_type)
    await state.update_data(
        ps_type=actual_type,
        photosession_id=photosession_id,
        photosession_cost=int(preset_count or 1),
    )

    detail_text = f"<b>{name}</b>"
    if description:
        detail_text += f"\n\n{description}"
    if preset_count:
        detail_text += f"\n\nВ наборе: {preset_count} фото за {preset_count} {_generation_word(preset_count)}."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать генерацию", callback_data=f"ps_gen_{photosession_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="ps_back")],
    ])

    try:
        await callback.message.delete()
    except Exception:
        pass

    if example_url:
        await callback.message.answer_photo(
            photo=URLInputFile(example_url),
            caption=detail_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await callback.message.answer(detail_text, parse_mode="HTML", reply_markup=keyboard)

    await callback.answer()


@router.callback_query(lambda cb: cb.data == "ps_back")
async def handle_back(callback: CallbackQuery, state: FSMContext):
    """Назад к списку фотосессий выбранного типа."""
    data = await state.get_data()
    ps_type = data.get("ps_type")
    ps_page = data.get("ps_page", 0)

    try:
        photosessions = await backend.get_photosessions(type=ps_type)
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await callback.answer("⚠️ Ошибка. Попробуй позже.")
        return

    type_label = PS_TYPES.get(ps_type, ps_type or "")

    try:
        await callback.message.delete()
    except Exception:
        pass

    if not photosessions:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="ps_back_to_types")],
        ])
        await callback.message.answer(
            f"{type_label} — пока нет доступных фотосессий.",
            reply_markup=keyboard,
        )
    else:
        await callback.message.answer(
            f"{type_label} — выбери фотосессию 📸👇",
            reply_markup=_photosession_list_keyboard(photosessions, ps_type, page=ps_page),
        )
    await callback.answer()
