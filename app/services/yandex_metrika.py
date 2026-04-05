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
    def build_offline_conversion_csv(client_id: str, target: str, timestamp: int) -> bytes:
        csv_text = f"ClientId,Target,DateTime\n{client_id},{target},{timestamp}\n"
        return csv_text.encode("utf-8")

    async def send_bot_started(self, client_id: str, source: str | None = None, telegram_id: int | None = None) -> bool:
        if not self.enabled:
            logger.info("Yandex Metrika bot_started skipped: client disabled")
            return False

        if not client_id.isdigit():
            logger.warning("Yandex Metrika bot_started skipped: invalid ClientId=%r", client_id)
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
            self.build_offline_conversion_csv(client_id, self.goal, timestamp),
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
                    "Yandex Metrika bot_started uploaded: client_id=%s source=%s tg=%s response=%s",
                    client_id,
                    source,
                    telegram_id,
                    body[:500],
                )
                return True


metrika = YandexMetrikaClient()
