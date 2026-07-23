"""Read-only product preview available from the onboarding paywall.

This router deliberately has its own callback namespace. It must never start a
generation, accept a photo, or change a profile before the user pays.
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, URLInputFile

from app.api.backend import backend
from app.services.analytics_sdk import AnalyticsClient

logger = logging.getLogger(__name__)
router = Router()

PHOTOSESSION_TYPES = (
    ("female", "👩 Женские"),
    ("male", "👨 Мужские"),
    ("couple", "👫 Парные"),
)
PAGE_SIZE = 12


def _home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Фотосессии", callback_data="preview_photosessions")],
        [
            InlineKeyboardButton(text="✨ AI-фотошоп", callback_data="preview_feature_edit"),
            InlineKeyboardButton(text="🎬 Оживление", callback_data="preview_feature_animation"),
        ],
        [InlineKeyboardButton(text="🔍 Улучшение качества", callback_data="preview_feature_upscale")],
        [InlineKeyboardButton(text="💜 Открыть доступ", callback_data="onboarding_pay")],
        [InlineKeyboardButton(text="◀️ Вернуться к предложению", callback_data="preview_back_to_offer")],
    ])


def _access_keyboard(back_callback: str = "preview_home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💜 Открыть доступ", callback_data="onboarding_pay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=back_callback)],
    ])


async def _preview_enabled(telegram_id: int) -> bool:
    try:
        result = await backend.get_price(telegram_id, context="onboarding_paywall")
        return bool(result.get("onboarding_preview_enabled"))
    except Exception as exc:
        logger.warning("Failed to load onboarding preview flag: %s", exc)
        return False


async def _return_to_offer(callback: CallbackQuery, analytics: AnalyticsClient) -> None:
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    from app.handlers.photo_upload import _show_onboarding_paywall
    await _show_onboarding_paywall(callback, analytics)


async def _require_preview(callback: CallbackQuery, analytics: AnalyticsClient) -> bool:
    if await _preview_enabled(callback.from_user.id):
        return True
    await _return_to_offer(callback, analytics)
    await callback.answer()
    return False


async def _edit_or_send(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "preview_home")
async def show_preview_home(callback: CallbackQuery, analytics: AnalyticsClient):
    if not await _require_preview(callback, analytics):
        return

    await analytics.track("onboarding_preview_opened", user_id=str(callback.from_user.id))
    await _edit_or_send(
        callback,
        "<b>Что умеет Кадрица</b> ✨\n\n"
        "Посмотри возможности до оплаты. В демо-режиме можно изучать функции, "
        "а создавать — после открытия доступа.",
        _home_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "preview_photosessions")
async def show_photosession_types(callback: CallbackQuery, analytics: AnalyticsClient):
    if not await _require_preview(callback, analytics):
        return

    results = await asyncio.gather(
        *(backend.get_photosessions(type=type_key) for type_key, _ in PHOTOSESSION_TYPES),
        return_exceptions=True,
    )
    counts = {
        type_key: len(result) if isinstance(result, list) else 0
        for (type_key, _), result in zip(PHOTOSESSION_TYPES, results)
    }
    total = sum(counts.values())
    buttons = [
        [InlineKeyboardButton(
            text=f"{label} — {counts[type_key]}",
            callback_data=f"preview_ps_type_{type_key}",
        )]
        for type_key, label in PHOTOSESSION_TYPES
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="preview_home")])

    await analytics.track(
        "onboarding_preview_photosessions_opened",
        user_id=str(callback.from_user.id),
        properties={"total": total},
    )
    await _edit_or_send(
        callback,
        f"<b>Фотосессии — {total} готовых сценариев</b> 📸\n\n"
        "Выбери раздел и посмотри, какие образы доступны.",
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


def _parse_page(callback_data: str) -> tuple[str, int] | None:
    parts = callback_data.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    type_key = parts[0].removeprefix("preview_ps_page_")
    return type_key, int(parts[1])


async def _show_photosession_page(callback: CallbackQuery, type_key: str, page: int) -> None:
    try:
        photosessions = await backend.get_photosessions(type=type_key)
    except Exception as exc:
        logger.error("Failed to load preview photosessions: %s", exc)
        await callback.answer("⚠️ Не удалось загрузить фотосессии.", show_alert=True)
        return

    label = dict(PHOTOSESSION_TYPES).get(type_key, "Фотосессии")
    last_page = max(0, (len(photosessions) - 1) // PAGE_SIZE)
    page = max(0, min(page, last_page))
    items = photosessions[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    buttons = [
        [InlineKeyboardButton(
            text=item.get("name") or f"Фотосессия {item['id']}",
            callback_data=f"preview_ps_view_{type_key}_{item['id']}",
        )]
        for item in items
    ]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="⬅️", callback_data=f"preview_ps_page_{type_key}_{page - 1}"))
    if page < last_page:
        navigation.append(InlineKeyboardButton(text="➡️", callback_data=f"preview_ps_page_{type_key}_{page + 1}"))
    if navigation:
        buttons.append(navigation)
    buttons.append([InlineKeyboardButton(text="◀️ К разделам", callback_data="preview_photosessions")])

    await _edit_or_send(
        callback,
        f"<b>{label}</b>\n\n"
        f"{len(photosessions)} фотосессий. Выбери любую, чтобы посмотреть детали.",
        InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("preview_ps_type_"))
async def show_photosession_type(callback: CallbackQuery, analytics: AnalyticsClient):
    if not await _require_preview(callback, analytics):
        return
    type_key = callback.data.removeprefix("preview_ps_type_")
    if type_key not in dict(PHOTOSESSION_TYPES):
        await callback.answer("Неизвестный раздел.", show_alert=True)
        return
    await analytics.track(
        "onboarding_preview_photosession_type_opened",
        user_id=str(callback.from_user.id),
        properties={"type": type_key},
    )
    await _show_photosession_page(callback, type_key, page=0)


@router.callback_query(F.data.startswith("preview_ps_page_"))
async def show_photosession_page(callback: CallbackQuery, analytics: AnalyticsClient):
    if not await _require_preview(callback, analytics):
        return
    parsed = _parse_page(callback.data)
    if parsed is None or parsed[0] not in dict(PHOTOSESSION_TYPES):
        await callback.answer("Неизвестная страница.", show_alert=True)
        return
    await _show_photosession_page(callback, *parsed)


@router.callback_query(F.data.startswith("preview_ps_view_"))
async def show_photosession_detail(callback: CallbackQuery, analytics: AnalyticsClient):
    if not await _require_preview(callback, analytics):
        return
    parts = callback.data.split("_", 4)
    if len(parts) != 5 or not parts[4].isdigit():
        await callback.answer("Не удалось открыть фотосессию.", show_alert=True)
        return
    type_key, photosession_id = parts[3], int(parts[4])
    if type_key not in dict(PHOTOSESSION_TYPES):
        await callback.answer("Неизвестная фотосессия.", show_alert=True)
        return

    try:
        photosessions = await backend.get_photosessions(type=type_key)
    except Exception as exc:
        logger.error("Failed to load preview photosession: %s", exc)
        await callback.answer("⚠️ Не удалось загрузить фотосессию.", show_alert=True)
        return
    item = next((item for item in photosessions if item["id"] == photosession_id), None)
    if item is None:
        await callback.answer("Фотосессия больше недоступна.", show_alert=True)
        return

    name = item.get("name") or f"Фотосессия {photosession_id}"
    description = item.get("description") or ""
    preset_count = item.get("preset_count")
    detail = f"<b>{name}</b>"
    if description:
        detail += f"\n\n{description}"
    if preset_count:
        detail += f"\n\nВ наборе: {preset_count} фото."

    await analytics.track(
        "onboarding_preview_photosession_viewed",
        user_id=str(callback.from_user.id),
        properties={"photosession_id": photosession_id, "type": type_key},
    )
    back_callback = f"preview_ps_page_{type_key}_0"
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    example_url = item.get("example")
    if example_url:
        try:
            await callback.message.answer_photo(
                photo=URLInputFile(example_url),
                caption=detail,
                parse_mode="HTML",
                reply_markup=_access_keyboard(back_callback),
            )
        except Exception as exc:
            logger.warning("Failed to show preview example image: %s", exc)
            await callback.message.answer(detail, parse_mode="HTML", reply_markup=_access_keyboard(back_callback))
    else:
        await callback.message.answer(detail, parse_mode="HTML", reply_markup=_access_keyboard(back_callback))
    await callback.answer()


FEATURES = {
    "animation": (
        "<b>Оживление фото</b> 🎬\n\n"
        "Превращает портрет или кадр в короткое видео на 5 секунд. "
        "Ты загружаешь фото и описываешь движение.",
    ),
    "edit": (
        "<b>AI-фотошоп</b> ✨\n\n"
        "Создавай новый образ, меняй детали на фото и генерируй результат по своему описанию.",
    ),
    "upscale": (
        "<b>Улучшение качества</b> 🔍\n\n"
        "Улучшает детализацию и качество уже готовой фотографии.",
    ),
}


@router.callback_query(F.data.startswith("preview_feature_"))
async def show_feature(callback: CallbackQuery, analytics: AnalyticsClient):
    if not await _require_preview(callback, analytics):
        return
    feature = callback.data.removeprefix("preview_feature_")
    text = FEATURES.get(feature)
    if text is None:
        await callback.answer("Неизвестная функция.", show_alert=True)
        return
    await analytics.track(
        "onboarding_preview_feature_viewed",
        user_id=str(callback.from_user.id),
        properties={"feature": feature},
    )
    await _edit_or_send(callback, text, _access_keyboard())
    await callback.answer()


@router.callback_query(F.data == "preview_back_to_offer")
async def back_to_offer(callback: CallbackQuery, analytics: AnalyticsClient):
    await _return_to_offer(callback, analytics)
    await callback.answer()
