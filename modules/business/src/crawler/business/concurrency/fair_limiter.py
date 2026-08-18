"""Fair keyed concurrency limiting without application-domain dependencies."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager
from typing import Generic, TypeVar

KeyT = TypeVar("KeyT", bound=Hashable)


class FairLimiter(Generic[KeyT]):
    """Bound concurrency while rotating fairly between independent keys."""

    def __init__(
        self,
        limit: int,
        *,
        state_error_message: str = "并发限制器状态损坏",
    ) -> None:
        self._limit = max(limit, 1)
        self._state_error_message = state_error_message
        self._active = 0
        self._waiters: dict[KeyT, deque[asyncio.Future[None]]] = {}
        self._turns: deque[KeyT] = deque()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def slot(self, key: KeyT) -> AsyncIterator[None]:
        await self._acquire(key)
        try:
            yield
        finally:
            await self._release()

    async def _acquire(self, key: KeyT) -> None:
        future = asyncio.get_running_loop().create_future()
        async with self._lock:
            queue = self._waiters.get(key)
            if queue is None:
                queue = deque()
                self._waiters[key] = queue
                self._turns.append(key)
            queue.append(future)
            self._grant_locked()
        try:
            await future
        except BaseException:
            async with self._lock:
                queue = self._waiters.get(key)
                if future.done() and not future.cancelled():
                    # The slot was granted immediately before cancellation.
                    self._active -= 1
                elif queue is not None:
                    try:
                        queue.remove(future)
                    except ValueError:
                        pass
                self._remove_empty_queue_locked(key)
                self._grant_locked()
            raise

    async def _release(self) -> None:
        async with self._lock:
            if self._active <= 0:
                raise RuntimeError(self._state_error_message)
            self._active -= 1
            self._grant_locked()

    def _grant_locked(self) -> None:
        while self._active < self._limit and self._turns:
            key = self._turns.popleft()
            queue = self._waiters.get(key)
            if queue is None:
                continue
            while queue and queue[0].cancelled():
                queue.popleft()
            if not queue:
                self._waiters.pop(key, None)
                continue
            future = queue.popleft()
            if queue:
                self._turns.append(key)
            else:
                self._waiters.pop(key, None)
            self._active += 1
            future.set_result(None)

    def _remove_empty_queue_locked(self, key: KeyT) -> None:
        queue = self._waiters.get(key)
        if queue:
            return
        self._waiters.pop(key, None)
        try:
            self._turns.remove(key)
        except ValueError:
            pass


__all__ = ["FairLimiter"]
