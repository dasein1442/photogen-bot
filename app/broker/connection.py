import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractConnection, AbstractChannel


async def setup_broker(url: str) -> tuple[AbstractConnection, AbstractChannel]:
    connection = await aio_pika.connect_robust(url)
    channel = await connection.channel()

    bot_action_exchange = await channel.declare_exchange(
        "bot_action.direct",
        type=ExchangeType.DIRECT,
        durable=True,
    )

    bot_action_queue = await channel.declare_queue(
        "bot_action_queue",
        durable=True,
    )
    await bot_action_queue.bind(bot_action_exchange, routing_key="action")

    return connection, channel


async def close_broker(connection: AbstractConnection) -> None:
    await connection.close()
