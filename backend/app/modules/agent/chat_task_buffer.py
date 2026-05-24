"""
聊天任务输出缓冲区

按任务维度管理 SSE 输出 chunk，支持：
1. 生产者（ChatTaskRunner）写入 chunk
2. 消费者（SSE 端点）按 offset 读取
3. 任务完成后归档到 DB，内存 buffer TTL 清理
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class BufferedChunk:
    """单个缓冲的 SSE 事件"""

    index: int  # 单调递增的序列号
    data: dict[str, Any]  # SSE 事件数据（已解析的 JSON）
    timestamp: float  # 写入时间（秒级时间戳）


class ChatTaskBuffer:
    """单个任务的输出缓冲区"""

    MAX_CHUNKS: int = 10000  # 每个任务最多保留的 chunk 数
    KEEPALIVE_INTERVAL: float = 30.0  # SSE keepalive 间隔（秒）

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._chunks: deque[BufferedChunk] = deque()
        self._next_index = 0
        self._completed = False
        self._failed = False
        self._error: str | None = None
        self._final_result: dict[str, Any] | None = None
        self._lock = asyncio.Lock()
        self._new_chunk_event = asyncio.Event()

    async def append(self, data: dict[str, Any]) -> int:
        """写入新 chunk，返回分配的 index"""
        async with self._lock:
            chunk = BufferedChunk(
                index=self._next_index,
                data=data,
                timestamp=time.time(),
            )
            self._chunks.append(chunk)
            self._next_index += 1

            # 环形截断：保留最近 MAX_CHUNKS 条
            while len(self._chunks) > self.MAX_CHUNKS:
                self._chunks.popleft()

            self._new_chunk_event.set()
            self._new_chunk_event = asyncio.Event()
            return chunk.index

    async def consume_from(
        self,
        offset: int = 0,
    ) -> AsyncIterator[BufferedChunk]:
        """从指定 offset 开始消费 chunk（含阻塞等待新数据）"""
        current_offset = offset

        while True:
            # 先发送已缓冲的数据
            chunks_to_yield: list[BufferedChunk] = []
            async with self._lock:
                for chunk in self._chunks:
                    if chunk.index >= current_offset:
                        chunks_to_yield.append(chunk)

            for chunk in chunks_to_yield:
                yield chunk
                current_offset = chunk.index + 1

            # 检查任务是否已结束
            async with self._lock:
                if self._completed or self._failed:
                    # 发送 final_result（封装在 done 事件里）
                    if self._final_result:
                        yield BufferedChunk(
                            index=self._next_index,
                            data={"type": "done", **self._final_result},
                            timestamp=time.time(),
                        )
                    return

            # 等待新数据或超时（发送 keepalive）
            wait_event = self._new_chunk_event
            try:
                await asyncio.wait_for(
                    wait_event.wait(),
                    timeout=self.KEEPALIVE_INTERVAL,
                )
            except asyncio.TimeoutError:
                yield BufferedChunk(
                    index=-1,
                    data={"type": "keepalive"},
                    timestamp=time.time(),
                )

    async def mark_completed(self, final_result: dict[str, Any]) -> list[dict[str, Any]]:
        """标记任务完成，返回完整 chunk 列表用于 DB 归档"""
        async with self._lock:
            self._completed = True
            self._final_result = final_result
            self._new_chunk_event.set()
            return [c.data for c in self._chunks]

    async def mark_failed(self, error: str) -> None:
        """标记任务失败"""
        async with self._lock:
            self._failed = True
            self._error = error
            self._final_result = {"status": "failed", "error_message": error}
            self._new_chunk_event.set()

    @property
    def is_completed(self) -> bool:
        return self._completed or self._failed

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def next_index(self) -> int:
        return self._next_index


class ChatTaskBufferRegistry:
    """全局 buffer 注册表（进程级单例）"""

    def __init__(self, ttl_seconds: float = 300.0):
        self._buffers: dict[str, ChatTaskBuffer] = {}
        self._ttl_seconds = ttl_seconds
        self._cleanup_task: asyncio.Task | None = None

    def get_or_create(self, task_id: str) -> ChatTaskBuffer:
        if task_id not in self._buffers:
            self._buffers[task_id] = ChatTaskBuffer(task_id)
        return self._buffers[task_id]

    def get(self, task_id: str) -> ChatTaskBuffer | None:
        return self._buffers.get(task_id)

    def remove(self, task_id: str) -> None:
        self._buffers.pop(task_id, None)

    async def start_cleanup_loop(self) -> None:
        """启动定期清理已完成 buffer 的后台循环"""

        async def _cleanup():
            while True:
                await asyncio.sleep(60)
                now = time.time()
                to_remove = []
                for task_id, buf in self._buffers.items():
                    if buf.is_completed and buf._chunks:
                        last_time = buf._chunks[-1].timestamp
                        if now - last_time > self._ttl_seconds:
                            to_remove.append(task_id)
                for task_id in to_remove:
                    self.remove(task_id)
                    logger.debug(f"[ChatTaskBuffer] Cleaned up buffer for {task_id}")

        self._cleanup_task = asyncio.create_task(_cleanup())

    def stop_cleanup_loop(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()


# 全局实例（延迟初始化，便于测试时替换）
_buffer_registry: ChatTaskBufferRegistry | None = None


def get_buffer_registry() -> ChatTaskBufferRegistry:
    global _buffer_registry
    if _buffer_registry is None:
        _buffer_registry = ChatTaskBufferRegistry()
    return _buffer_registry


def set_buffer_registry(registry: ChatTaskBufferRegistry) -> None:
    global _buffer_registry
    _buffer_registry = registry
