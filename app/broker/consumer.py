import json
import logging

from aiogram import Bot
from aiogram.types import LabeledPrice
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage

from app.api.backend import backend

logger = logging.getLogger(__name__)


class BotActionConsumer:
    def __init__(self, channel: AbstractChannel, bot: Bot) -> None:
        self._channel = channel
        self._bot = bot

    async def start(self) -> None:
        await self._channel.set_qos(prefetch_count=5)
        queue = await self._channel.get_queue("bot_action_queue")
        await queue.consume(self._process_message)
        logger.info("BotActionConsumer started, listening on bot_action_queue")

    async def _process_message(self, message: AbstractIncomingMessage) -> None:
        try:
            data = json.loads(message.body)
            action = data.get("action")

            if action == "send_invoice":
                await self._handle_send_invoice(data)
            else:
                logger.warning("Unknown bot action: %s", action)

            await message.ack()
        except Exception:
            logger.exception("Error processing bot action message")
            await message.nack(requeue=False)

    async def _handle_send_invoice(self, data: dict) -> None:
        chat_id = data["chat_id"]
        delivery_id = data.get("delivery_id")

        # 1. Get current price from backend
        try:
            price_data = await backend.get_price(chat_id)
        except Exception as e:
            logger.error("Failed to get price for chat_id %s: %s", chat_id, e)
            return

        stars = price_data["stars"]
        generations = price_data["generations"]

        # 3. Send Stars invoice
        try:
            await self._bot.send_invoice(
                chat_id=chat_id,
                title=f"{generations} генераций",
                description=f"Покупка {generations} генераций для создания AI-фото",
                payload=f"buy_{generations}_{chat_id}",
                currency="XTR",
                prices=[LabeledPrice(label=f"{generations} генераций", amount=stars)],
            )
            logger.info("Invoice sent for delivery %s, chat_id %s (%d XTR)", delivery_id, chat_id, stars)
        except Exception as e:
            logger.error("Failed to send invoice for delivery %s: %s", delivery_id, e)
