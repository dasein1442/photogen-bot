# analytics_sdk.py
# Использование:
#   from analytics_sdk import AnalyticsClient
#   analytics = AnalyticsClient(url="http://analytics.internal", api_key="...")
#   await analytics.track("photo_generated", user_id="123", properties={"preset": "headshot"})

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Any

import httpx


class AnalyticsClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        auto_flush_interval: float = 5.0,  # секунд
        batch_size: int = 50,
        enabled: bool = True,
    ):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.auto_flush_interval = auto_flush_interval
        self.batch_size = batch_size
        self.enabled = enabled
        self._queue: deque = deque()
        self._flush_task: asyncio.Task | None = None
        self._client = httpx.AsyncClient(
            headers={"X-API-Key": api_key},
            timeout=10.0,
        )

    async def start(self):
        """Запустить фоновую задачу автосброса. Вызывать при старте приложения."""
        if not self.enabled:
            return
        self._flush_task = asyncio.create_task(self._auto_flush_loop())

    async def stop(self):
        """Остановить и сбросить оставшиеся события. Вызывать при остановке приложения."""
        if not self.enabled:
            return
        if self._flush_task:
            self._flush_task.cancel()
        await self.flush()
        await self._client.aclose()

    async def track(
        self,
        event_name: str,
        user_id: str | None = None,
        properties: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Отправить одно событие (буферизованно)."""
        if not self.enabled:
            return
        self._queue.append({
            "event_name": event_name,
            "user_id": user_id,
            "properties": properties or {},
            "timestamp": (timestamp or datetime.utcnow()).isoformat(),
        })
        if len(self._queue) >= self.batch_size:
            await self.flush()

    async def track_immediate(
        self,
        event_name: str,
        user_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict:
        """Отправить событие немедленно (без буфера). Возвращает ответ сервера."""
        if not self.enabled:
            return {}
        response = await self._client.post(
            f"{self.url}/api/v1/events",
            json={
                "event_name": event_name,
                "user_id": user_id,
                "properties": properties or {},
            },
        )
        response.raise_for_status()
        return response.json()

    async def flush(self) -> None:
        """Отправить все накопленные события батчем."""
        if not self._queue:
            return
        events = []
        while self._queue and len(events) < self.batch_size:
            events.append(self._queue.popleft())
        if not events:
            return
        try:
            response = await self._client.post(
                f"{self.url}/api/v1/events/batch",
                json={"events": events},
            )
            response.raise_for_status()
        except Exception:
            # При ошибке вернуть события в очередь (prepend)
            for event in reversed(events):
                self._queue.appendleft(event)

    async def _auto_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.auto_flush_interval)
            await self.flush()


# aiogram middleware — автоматический трекинг команд и callback'ов
class AiogramAnalyticsMiddleware:
    def __init__(self, analytics: AnalyticsClient):
        self.analytics = analytics

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        user_id = str(user.id) if user else None

        # Определить имя события
        if hasattr(event, "text") and event.text and event.text.startswith("/"):
            event_name = f"command_{event.text.split()[0][1:]}"
        elif hasattr(event, "data"):
            event_name = f"callback_{event.data.split(':')[0]}"
        else:
            event_name = "message"

        await self.analytics.track(event_name, user_id=user_id)
        return await handler(event, data)


# FastAPI middleware — автоматический трекинг HTTP запросов
class FastAPIAnalyticsMiddleware:
    def __init__(self, app, analytics: AnalyticsClient):
        self.app = app
        self.analytics = analytics

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            method = scope.get("method", "")
            start_time = time.monotonic()

            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    asyncio.create_task(self.analytics.track(
                        "http_request",
                        properties={
                            "path": path,
                            "method": method,
                            "status": message.get("status"),
                            "duration_ms": duration_ms,
                        },
                    ))
                await send(message)

            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)
