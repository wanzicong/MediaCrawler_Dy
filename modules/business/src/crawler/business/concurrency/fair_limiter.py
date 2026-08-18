"""按 key 公平轮转的并发限制器，不依赖任何应用层领域概念。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager
from typing import Generic, TypeVar

KeyT = TypeVar("KeyT", bound=Hashable)


class FairLimiter(Generic[KeyT]):
    """限制总并发数，并在相互独立的 key 之间公平轮转分配执行槽位。"""

    def __init__(
        self,
        limit: int,
        *,
        state_error_message: str = "并发限制器状态损坏",
    ) -> None:
        """初始化公平并发限制器。

        参数：
            limit: 允许同时执行的最大槽位数，小于 1 时按 1 处理。
            state_error_message: 释放次数超过获取次数等状态损坏场景下
                抛出 RuntimeError 时使用的错误消息。
        """
        self._limit = max(limit, 1)
        self._state_error_message = state_error_message
        self._active = 0  # 当前已占用（正在执行）的槽位数
        self._waiters: dict[
            KeyT, deque[asyncio.Future[None]]
        ] = {}  # 每个 key 的等待者队列
        self._turns: deque[KeyT] = deque()  # 各 key 的轮转顺序，保证公平性
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def slot(self, key: KeyT) -> AsyncIterator[None]:
        """为指定 key 申请一个执行槽位，退出上下文时自动释放。

        参数：
            key: 用于公平轮转的业务键（可哈希对象）。
        """
        await self._acquire(key)
        try:
            yield
        finally:
            await self._release()

    async def _acquire(self, key: KeyT) -> None:
        """排队等待槽位；等待期间被取消时清理队列并补偿已授予的槽位。"""
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
                    # 取消发生前槽位刚刚被授予，需要归还该槽位
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
        """归还一个槽位并尝试授予后续等待者；多释放时抛出状态损坏错误。"""
        async with self._lock:
            if self._active <= 0:
                raise RuntimeError(self._state_error_message)
            self._active -= 1
            self._grant_locked()

    def _grant_locked(self) -> None:
        """在持有锁的前提下，按轮转顺序将空闲槽位授予各 key 的队首等待者。"""
        while self._active < self._limit and self._turns:
            key = self._turns.popleft()
            queue = self._waiters.get(key)
            if queue is None:
                continue
            # 丢弃队首已被取消的等待者
            while queue and queue[0].cancelled():
                queue.popleft()
            if not queue:
                self._waiters.pop(key, None)
                continue
            future = queue.popleft()
            if queue:
                # 该 key 仍有等待者，排到轮转队列末尾以保证公平
                self._turns.append(key)
            else:
                self._waiters.pop(key, None)
            self._active += 1
            future.set_result(None)

    def _remove_empty_queue_locked(self, key: KeyT) -> None:
        """在持有锁的前提下，移除已清空的 key 等待队列及其轮转记录。"""
        queue = self._waiters.get(key)
        if queue:
            return
        self._waiters.pop(key, None)
        try:
            self._turns.remove(key)
        except ValueError:
            pass


__all__ = ["FairLimiter"]
