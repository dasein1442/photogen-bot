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
        self, telegram_id: int, username: str | None, first_name: str | None, last_name: str | None,
        source: str | None = None,
    ) -> dict:
        """POST /users/register — регистрация/обновление пользователя."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "telegram_id": telegram_id,
                "username": username or "",
                "first_name": first_name or "",
                "last_name": last_name or "",
            }
            if source is not None:
                payload["source"] = source
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

    async def upload_photo_raw(self, telegram_id: int, photo_bytes: bytes, filename: str) -> dict:
        """POST /photos/upload-raw — загрузка фото без face validation (для ИИ-фотошопа)."""
        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("file", BytesIO(photo_bytes), filename=filename, content_type="image/jpeg")
            async with session.post(
                f"{self.base_url}/photos/upload-raw",
                params={"telegram_id": telegram_id},
                data=form,
                headers=self._headers(),
            ) as resp:
                if resp.status == 200:
                    return {"ok": True, **(await resp.json())}
                body = await resp.json()
                detail = body.get("detail", "Неизвестная ошибка")
                return {"ok": False, "error": detail}

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
            logger.info(f"generate_photo: telegram_id={telegram_id}, photosession_id={photosession_id}")
            async with session.post(
                f"{self.base_url}/photos/generate", json=payload, headers=self._headers()
            ) as resp:
                if resp.status == 402:
                    return {"error": "no_balance"}
                if resp.status == 429:
                    return {"error": "already_generating"}
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error(f"generate_photo failed: status={resp.status}, body={body}")
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history,
                        status=resp.status, message=body,
                    )
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
                if resp.status == 429:
                    return {"error": "already_generating"}
                resp.raise_for_status()
                return await resp.json()

    async def generate_custom_prompt(self, telegram_id: int, prompt: str, photo_id: int) -> dict:
        """POST /photos/generate-custom — генерация по кастомному промту пользователя."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id, "prompt": prompt, "photo_id": photo_id}
            async with session.post(
                f"{self.base_url}/photos/generate-custom", json=payload, headers=self._headers()
            ) as resp:
                if resp.status == 402:
                    return {"error": "no_balance"}
                if resp.status == 429:
                    return {"error": "already_generating"}
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error(f"generate_custom_prompt failed: status={resp.status}, body={body}")
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history,
                        status=resp.status, message=body,
                    )
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
                if resp.status == 429:
                    return {"error": "already_generating"}
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

    async def refund_delivery(self, telegram_id: int, task_id: int, failed_count: int) -> dict:
        """POST /photos/refund-delivery -- refund credits for failed Telegram delivery."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "telegram_id": telegram_id,
                "task_id": task_id,
                "failed_count": failed_count,
            }
            async with session.post(
                f"{self.base_url}/photos/refund-delivery",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_price(self, telegram_id: int, context: str = "menu") -> dict:
        """GET /payments/price — pricing tiers for user."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/payments/price",
                params={"telegram_id": telegram_id, "context": context},
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def create_yookassa_payment(self, telegram_id: int, generations: int, amount_rubles: int) -> dict:
        """POST /payments/yookassa/create — создать платёж ЮКасса."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "telegram_id": telegram_id,
                "generations": generations,
                "amount_rubles": amount_rubles,
            }
            async with session.post(
                f"{self.base_url}/payments/yookassa/create", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def check_yookassa_payment(self, telegram_id: int, yookassa_id: str | None = None) -> dict:
        """GET /payments/yookassa/status — проверить статус платежа."""
        async with aiohttp.ClientSession() as session:
            params = {"telegram_id": telegram_id}
            if yookassa_id:
                params["yookassa_id"] = yookassa_id
            async with session.get(
                f"{self.base_url}/payments/yookassa/status",
                params=params,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def notify_payment_flow(self, telegram_id: int) -> dict:
        """POST /payments/flow-started — сообщить о начале оплаты."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id}
            async with session.post(
                f"{self.base_url}/payments/flow-started", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def save_photo_feedback(self, telegram_id: int, generation_task_id: int, feedback: str) -> dict:
        """POST /payments/photo-feedback — save like/dislike feedback on a generation."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id, "generation_task_id": generation_task_id, "feedback": feedback}
            async with session.post(
                f"{self.base_url}/payments/photo-feedback", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def save_photo_feedback_reason(self, telegram_id: int, generation_task_id: int, reason: str) -> dict:
        """POST /payments/photo-feedback-reason — save dislike reason."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id, "generation_task_id": generation_task_id, "reason": reason}
            async with session.post(
                f"{self.base_url}/payments/photo-feedback-reason", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def notify_onboarding_paywall(self, telegram_id: int) -> dict:
        """POST /payments/onboarding-paywall-shown — notify backend about post-onboarding paywall."""
        async with aiohttp.ClientSession() as session:
            payload = {"telegram_id": telegram_id}
            async with session.post(
                f"{self.base_url}/payments/onboarding-paywall-shown", json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                return await resp.json()


# Один экземпляр на всё приложение
backend = BackendClient()
