"""Broker SSE em memória (pub/sub asyncio)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any


class EventBroker:
    """Fan-out de eventos para clientes SSE conectados."""

    def __init__(self, max_queue: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"topic": topic, "ts": time.time()}
        if payload:
            message.update(payload)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Cliente lento: descarta o evento em vez de travar o job
                pass


def sse_format(message: dict[str, Any]) -> str:
    return f"event: {message['topic']}\ndata: {json.dumps(message)}\n\n"
