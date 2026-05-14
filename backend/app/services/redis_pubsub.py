"""
Redis Pub/Sub Service for WebSocket cross-worker message delivery.

Each Gunicorn worker subscribes to workspace channels when connections arrive.
Outgoing broadcasts are published to Redis; this listener delivers them to
the local WebSocket connections held by this worker.
"""
import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)


class RedisPubSub:
    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._subscriptions: set[str] = set()
        self._callback: Optional[Callable[[str, dict], Awaitable[None]]] = None

    def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    def _get_pubsub(self) -> aioredis.client.PubSub:
        if self._pubsub is None:
            self._pubsub = self._get_client().pubsub()
        return self._pubsub

    async def publish(self, channel: str, message: dict) -> None:
        try:
            await self._get_client().publish(channel, json.dumps(message))
        except Exception as e:
            logger.error(f"Redis publish error on {channel}: {e}")

    async def subscribe(self, channel: str) -> None:
        if channel in self._subscriptions:
            return
        try:
            await self._get_pubsub().subscribe(channel)
            self._subscriptions.add(channel)
            logger.info(f"Redis: subscribed to {channel}")
        except Exception as e:
            logger.error(f"Redis subscribe error on {channel}: {e}")

    async def unsubscribe(self, channel: str) -> None:
        if channel not in self._subscriptions:
            return
        try:
            await self._get_pubsub().unsubscribe(channel)
            self._subscriptions.discard(channel)
            logger.info(f"Redis: unsubscribed from {channel}")
        except Exception as e:
            logger.error(f"Redis unsubscribe error on {channel}: {e}")

    async def start_listener(
        self, callback: Callable[[str, dict], Awaitable[None]]
    ) -> None:
        """
        Background loop that reads messages from subscribed channels and calls
        callback(channel, message_dict). Launch with asyncio.create_task().
        """
        self._callback = callback
        logger.info("Redis pub/sub listener started")
        while True:
            try:
                if not self._subscriptions:
                    await asyncio.sleep(0.1)
                    continue
                msg = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.01
                )
                if msg and msg["type"] == "message":
                    channel: str = msg["channel"]
                    data: dict = json.loads(msg["data"])
                    if self._callback:
                        await self._callback(channel, data)
                else:
                    await asyncio.sleep(0.005)
            except Exception as e:
                logger.error(f"Redis listener error: {e}", exc_info=True)
                await asyncio.sleep(1)


redis_pubsub = RedisPubSub()
