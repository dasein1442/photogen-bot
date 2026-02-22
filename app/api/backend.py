"""
Клиент для обращения к бэкенду photogen.
"""

import asyncio
import logging
from io import BytesIO

import aiohttp
from app import config

logger = logging.getLogger(__name__)


class BackendClient:
    def __init__(self):
        self.base_url = config.BACKEND_URL.rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {config.API_SECRET_TOKEN}"}

    async def register_user(
        self, telegram_id: int, username: str | None, first_name: str | None, last_name: str | None
    ) -> dict:
        """POST /users/register — регистрация/обновление пользователя."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "telegram_id": telegram_id,
                "username": username or "",
                "first_name": first_name or "",
                "last_name": last_name or "",
            }
            async with session.post(
                f"{self.base_url}/users/register", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_user(self, telegram_id: int) -> dict:
        """GET /users/me?telegram_id=... — данные пользователя и баланс."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/users/me",
                params={"telegram_id": telegram_id},
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_photosessions(self) -> list[dict]:
        """GET /photosessions — список доступных фотосессий."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/photosessions", headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def upload_photo(self, telegram_id: int, photo_bytes: bytes, filename: str) -> dict:
        """
        POST /photos/upload — загрузка фото на бэкенд с валидацией.

        Возвращает:
          {"ok": True, "photo_id": ..., "s3_key": ...}  — при успехе
          {"ok": False, "errors": ["...", "..."]}        — при ошибке валидации
        """
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("file", BytesIO(photo_bytes), filename=filename, content_type="image/jpeg")
            async with session.post(
                f"{self.base_url}/photos/upload",
                params={"telegram_id": telegram_id},
                data=form,
                headers=self._headers(),
            ) as resp:
                body = await resp.json()

                if resp.status == 200:
                    return {"ok": True, **body}

                # Ошибка валидации (400) или другая ошибка
                detail = body.get("detail", {})
                if isinstance(detail, dict):
                    errors = detail.get("errors", [])
                elif isinstance(detail, str):
                    errors = [detail]
                else:
                    errors = ["Неизвестная ошибка"]

                return {"ok": False, "errors": errors}

    async def set_profile_photo(self, telegram_id: int, photo_id: int) -> dict:
        """PUT /users/profile-photo — установка фото профиля."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id, "photo_id": photo_id}
            async with session.put(
                f"{self.base_url}/users/profile-photo", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def generate_photo(self, telegram_id: int, photosession_id: int) -> dict:
        """POST /photos/generate — запуск генерации."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "telegram_id": telegram_id,
                "photosession_id": photosession_id,
            }
            async with session.post(
                f"{self.base_url}/photos/generate", json=payload, headers=self._headers()
            ) as resp:
                if resp.status == 402:
                    return {"error": "no_balance"}
                resp.raise_for_status()
                return await resp.json()

    async def generate_onboarding_photo(self, telegram_id: int) -> dict:
        """POST /photos/generate-onboarding — онбординговая генерация по фиксированному пресету."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id}
            async with session.post(
                f"{self.base_url}/photos/generate-onboarding", json=payload, headers=self._headers()
            ) as resp:
                if resp.status == 402:
                    return {"error": "no_balance"}
                if resp.status == 404:
                    return {"error": "no_presets"}
                resp.raise_for_status()
                return await resp.json()

    async def generate_random_photo(self, telegram_id: int) -> dict:
        """POST /photos/generate-random — запуск случайной генерации."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id}
            async with session.post(
                f"{self.base_url}/photos/generate-random", json=payload, headers=self._headers()
            ) as resp:
                if resp.status == 402:
                    return {"error": "no_balance"}
                if resp.status == 404:
                    return {"error": "no_presets"}
                resp.raise_for_status()
                return await resp.json()

    async def get_task_status(self, task_id: int) -> dict:
        """GET /photos/task/{task_id} — статус задачи генерации."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/photos/task/{task_id}", headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def poll_task(self, task_id: int, interval: int = 5, max_attempts: int = 60) -> dict:
        """Поллинг задачи до завершения. Возвращает финальный статус."""
        for _ in range(max_attempts):
            result = await self.get_task_status(task_id)
            status = result.get("status")
            if status in ("completed", "failed"):
                return result
            await asyncio.sleep(interval)
        return {"status": "timeout", "error_message": "Превышено время ожидания генерации"}


# Один экземпляр на всё приложение
backend = BackendClient()
