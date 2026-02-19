
"""
Клиент для обращения к бэкенду photogen.

Здесь будут все запросы к backend API.
Пока это заготовка — методы возвращают заглушки.

Когда бэкенд будет готов:
1. Убери заглушки
2. Раскомментируй HTTP-запросы
3. Поменяй BACKEND_URL в .env
"""

import aiohttp
from app import config


class BackendClient:
    def __init__(self):
        self.base_url = config.BACKEND_URL

    async def get_user(self, telegram_id: int) -> dict | None:
        """Получить пользователя по telegram_id."""
        # TODO: раскомментировать когда бэкенд готов
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(f"{self.base_url}/users/{telegram_id}") as resp:
        #         if resp.status == 200:
        #             return await resp.json()
        #         return None
        return None  # заглушка

    async def create_user(self, telegram_id: int, username: str | None) -> dict:
        """Создать нового пользователя."""
        # TODO: раскомментировать когда бэкенд готов
        # async with aiohttp.ClientSession() as session:
        #     payload = {"telegram_id": telegram_id, "username": username}
        #     async with session.post(f"{self.base_url}/users", json=payload) as resp:
        #         return await resp.json()
        return {"telegram_id": telegram_id, "username": username}  # заглушка

    async def moderate_photo(self, telegram_id: int, file_id: str) -> dict:
        """Проверить фото на соответствие правилам модерации."""
        # TODO: раскомментировать когда бэкенд готов
        # async with aiohttp.ClientSession() as session:
        #     payload = {"telegram_id": telegram_id, "file_id": file_id}
        #     async with session.post(f"{self.base_url}/moderation/photo", json=payload) as resp:
        #         return await resp.json()
        return {
            "is_valid": True,
            "reason": None,
            "telegram_id": telegram_id,
            "file_id": file_id,
        }  # заглушка

    async def generate_photo(self, telegram_id: int, source_file_id: str) -> dict:
        """Сгенерировать фото на основе исходного изображения пользователя."""
        # TODO: раскомментировать когда бэкенд готов
        # async with aiohttp.ClientSession() as session:
        #     payload = {"telegram_id": telegram_id, "source_file_id": source_file_id}
        #     async with session.post(f"{self.base_url}/generation/photo", json=payload) as resp:
        #         return await resp.json()
        return {
            "generated_file_id": source_file_id,
            "telegram_id": telegram_id,
        }  # заглушка

    async def get_user_data(self, telegram_id: int) -> dict:
        """Получить данные пользователя (количество генераций и т.д.)."""
        # TODO: раскомментировать когда бэкенд готов
        # async with aiohttp.ClientSession() as session:
        #     async with session.get(f"{self.base_url}/users/{telegram_id}/data") as resp:
        #         if resp.status == 200:
        #             return await resp.json()
        #         return {"generations_left": 0}
        return {"generations_left": 3}  # заглушка

    async def update_user_photo(self, telegram_id: int, file_id: str, photo_type: str) -> dict:
        """Обновить фото пользователя (основное или дополнительное)."""
        # TODO: раскомментировать когда бэкенд готов
        # async with aiohttp.ClientSession() as session:
        #     payload = {"telegram_id": telegram_id, "file_id": file_id, "photo_type": photo_type}
        #     async with session.post(f"{self.base_url}/users/{telegram_id}/photo", json=payload) as resp:
        #         return await resp.json()
        return {
            "success": True,
            "telegram_id": telegram_id,
            "file_id": file_id,
            "photo_type": photo_type,
        }  # заглушка


# Один экземпляр на всё приложение
backend = BackendClient()
