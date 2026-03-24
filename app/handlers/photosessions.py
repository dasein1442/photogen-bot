import logging

from aiogram import F, Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, URLInputFile

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "Фотосессии")
async def handle_photosessions(message: Message, analytics: AnalyticsClient):
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

    buttons = []
    for ps in photosessions:
        name = ps.get("name") or f"Фотосессия {ps['id']}"
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"ps_view_{ps['id']}")])

    await message.answer("Выбери фотосессию 📸👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@router.callback_query(lambda cb: cb.data and cb.data.startswith("ps_view_"))
async def handle_photosession_view(callback: CallbackQuery, analytics: AnalyticsClient):
    photosession_id = int(callback.data.split("_")[2])

    try:
        photosessions = await backend.get_photosessions()
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await callback.answer("⚠️ Не удалось загрузить фотосессию.")
        return

    ps = next((p for p in photosessions if p["id"] == photosession_id), None)
    if ps is None:
        await callback.answer("⚠️ Фотосессия не найдена.")
        return

    await analytics.track("photosession_viewed", user_id=str(callback.from_user.id), properties={"photosession_id": photosession_id})

    name = ps.get("name", f"Фотосессия {photosession_id}")
    description = ps.get("description", "")
    example_url = ps.get("example")

    detail_text = f"<b>{name}</b>"
    if description:
        detail_text += f"\n\n{description}"

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
async def handle_back(callback: CallbackQuery):
    try:
        photosessions = await backend.get_photosessions()
    except Exception as e:
        logger.error(f"Ошибка загрузки фотосессий: {e}")
        await callback.answer("⚠️ Ошибка. Попробуй позже.")
        return

    buttons = []
    for ps in photosessions:
        name = ps.get("name") or f"Фотосессия {ps['id']}"
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"ps_view_{ps['id']}")])

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer("Выбери фотосессию 📸👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()
