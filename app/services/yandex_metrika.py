import logging
import time

import aiohttp

from app import config

logger = logging.getLogger(__name__)


class YandexMetrikaClient:
    def __init__(self):
        self.enabled = (
            config.YANDEX_METRIKA_ENABLED
            and bool(config.YANDEX_METRIKA_OAUTH_TOKEN)
            and bool(config.YANDEX_METRIKA_COUNTER_ID)
            and bool(config.YANDEX_METRIKA_GOAL)
        )
        self.token = config.YANDEX_METRIKA_OAUTH_TOKEN
        self.counter_id = config.YANDEX_METRIKA_COUNTER_ID
        self.goal = config.YANDEX_METRIKA_GOAL
        self.base_url = "https://api-metrika.yandex.net/management/v1/counter"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"OAuth {self.token}"}

    @staticmethod
    def build_offline_conversion_csv(identifier_name: str, identifier_value: str, target: str, timestamp: int) -> bytes:
        csv_text = f"{identifier_name},Target,DateTime\n{identifier_value},{target},{timestamp}\n"
        return csv_text.encode("utf-8")

    async def _send_bot_started(
        self,
        identifier_name: str,
        identifier_value: str,
        source: str | None = None,
        telegram_id: int | None = None,
    ) -> bool:
        if not self.enabled:
            logger.info("Yandex Metrika bot_started skipped: client disabled")
            return False

        if not identifier_value or any(ch in identifier_value for ch in {",", "\n", "\r"}):
            logger.warning(
                "Yandex Metrika bot_started skipped: invalid %s=%r",
                identifier_name,
                identifier_value,
            )
            return False

        timestamp = int(time.time())
        comment_parts = [self.goal]
        if source:
            comment_parts.append(f"source={source}")
        if telegram_id is not None:
            comment_parts.append(f"tg={telegram_id}")

        form = aiohttp.FormData()
        form.add_field(
            "file",
            self.build_offline_conversion_csv(identifier_name, identifier_value, self.goal, timestamp),
            filename="offline_conversions.csv",
            content_type="text/csv",
        )
        form.add_field("comment", " ".join(comment_parts))

        url = f"{self.base_url}/{self.counter_id}/offline_conversions/upload"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form, headers=self._headers()) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    logger.error(
                        "Yandex Metrika bot_started upload failed: status=%s body=%s",
                        resp.status,
                        body[:500],
                    )
                    return False

                logger.info(
                    "Yandex Metrika bot_started uploaded: %s=%s source=%s tg=%s response=%s",
                    identifier_name,
                    identifier_value,
                    source,
                    telegram_id,
                    body[:500],
                )
                return True

    async def send_bot_started_by_client_id(
        self,
        client_id: str,
        source: str | None = None,
        telegram_id: int | None = None,
    ) -> bool:
        if not client_id.isdigit():
            logger.warning("Yandex Metrika bot_started skipped: invalid ClientId=%r", client_id)
            return False

        return await self._send_bot_started(
            identifier_name="ClientId",
            identifier_value=client_id,
            source=source,
            telegram_id=telegram_id,
        )

    async def send_bot_started_by_yclid(
        self,
        yclid: str,
        source: str | None = None,
        telegram_id: int | None = None,
    ) -> bool:
        return await self._send_bot_started(
            identifier_name="Yclid",
            identifier_value=yclid,
            source=source,
            telegram_id=telegram_id,
        )


metrika = YandexMetrikaClient()
