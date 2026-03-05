import logging
from math import ceil

from aiogram import F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, URLInputFile

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient

logger = logging.getLogger(__name__)
router = Router()

ITEMS_PER_PAGE = 10  # 5 rows × 2 columns


def _build_list_keyboard(photosessions: list, page: int) -> InlineKeyboardMarkup:
    total_pages = ceil(len(photosessions) / ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    page_items = photosessions[start:start + ITEMS_PER_PAGE]

    rows = []
    for i in range(0, len(page_items), 2):
        pair = page_items[i:i + 2]
        row = []
        for ps in pair:
            name = ps.get("name") or f"Фотосессия {ps['id']}"
            row.append(InlineKeyboardButton(
                text=name,
                callback_data=f"ps_view_{ps['id']}_p{page}",
            ))
        rows.append(row)

    if total_pages > 1:
        nav = []
        nav.append(
            InlineKeyboardButton(text="◀️", callback_data=f"ps_list_{page - 1}")
            if page > 0 else InlineKeyboardButton(text=" ", callback_data="ps_noop")
        )
        nav.append(
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="ps_noop")
        )
        nav.append(
            InlineKeyboardButton(text="▶️", callback_data=f"ps_list_{page + 1}")
            if page < total_pages - 1 else InlineKeyboardButton(text=" ", callback_data="ps_noop")
        )
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "Фотосессии")
async def handle_photosessions(message: Message, analytics: AnalyticsClient):
    """Загружает фотосессии с бэкенда и показывает как inline-кнопки."""
    try:
        photosessions = await backend.get_photosessions()
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await message.answer("⚠️ Не удалось загрузить фотосессии. Попробуй позже.")
        return

    await analytics.track("photosessions_viewed", user_id=str(message.from_user.id), properties={"count": len(photosessions)})

    if not photosessions:
        await message.answer("Пока нет доступных фотосессий. Заходи позже!")
        return

    await message.answer("Выбери фотосессию 📸👇", reply_markup=_build_list_keyboard(photosessions, 0))


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_list_"))
async def handle_page(callback: CallbackQuery):
    """Переключение страниц — редактируем текущее сообщение."""
    page = int(callback.data.split("_")[2])
    try:
        photosessions = await backend.get_photosessions()
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await callback.answer("⚠️ Ошибка. Попробуй позже.")
        return

    await callback.message.edit_reply_markup(reply_markup=_build_list_keyboard(photosessions, page))
    await callback.answer()


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_view_"))
async def handle_photosession_view(callback: CallbackQuery, analytics: AnalyticsClient):
    """Показываем детальный вид фотосессии — удаляем список, показываем карточку."""
    # callback_data: ps_view_{id}_p{page}
    parts = callback.data.split("_")
    photosession_id = int(parts[2])
    page = int(parts[3][1:]) if len(parts) > 3 else 0

    try:
        photosessions = await backend.get_photosessions()
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}", exc_info=True)
        await callback.answer("⚠️ Не удалось загрузить фотосессию.")
        return

    ps = next((p for p in photosessions if p["id"] == photosession_id), None)
    if ps is None:
        await callback.answer("⚠️ Фотосессия не найдена.")
        return

    await analytics.track("photosession_viewed", user_id=str(callback.from_user.id), properties={"photosession_id": photosession_id})

    name = ps.get("name", f"Фотосессия {photosession_id}")
    description = ps.get("description", "")
    example_images = ps.get("example_images") or []

    detail_text = f"<b>{name}</b>"
    if description:
        detail_text += f"\n\n{description}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать генерацию", callback_data=f"ps_gen_{photosession_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"ps_back_{page}")],
    ])

    # Удаляем сообщение со списком
    try:
        await callback.message.delete()
    except Exception:
        pass

    if example_images:
        await callback.message.answer_photo(
            photo=URLInputFile(example_images[0]),
            caption=detail_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    else:
        await callback.message.answer(detail_text, parse_mode="HTML", reply_markup=keyboard)

    await callback.answer()


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_back_"))
async def handle_back(callback: CallbackQuery):
    """Вернуться к списку — удаляем карточку, показываем список."""
    page = int(callback.data.split("_")[2])
    try:
        photosessions = await backend.get_photosessions()
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await callback.answer("⚠️ Ошибка. Попробуй позже.")
        return

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer("Выбери фотосессию 📸👇", reply_markup=_build_list_keyboard(photosessions, page))
    await callback.answer()


@router.callback_query(lambda cb: cb.data == "ps_noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer()
