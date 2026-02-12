
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


# Один экземпляр на всё приложение
backend = BackendClient()
