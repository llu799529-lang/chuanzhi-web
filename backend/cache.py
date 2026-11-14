"""有界 TTL 缓存：给「同样的输入短时间内重复请求」用，避免重复消耗模型额度。

为什么单独成模块
----------------
原来 `/api/ai/multimodal` 在 main.py 里手写了一个 dict 缓存，第一版**没有上限**：
key 含用户与记录时间戳，几乎不会重复命中，过期判断又只在「读」的时候做，
过期的键永远没人删——每点一次「综合分析」就多一份完整报告常驻内存。
修好以后它仍然是路由文件里的一段私有状态，没法单独测试。抽出来之后：
  · 容量上限与过期清理是这个类的不变量，有单元测试锁住；
  · 业务代码只剩 `get` / `put` 两个调用。

线程安全：FastAPI 的同步路由在线程池里并发执行，读写都在锁里。
基础层模块：不依赖任何内部模块。
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float, max_items: int, clock: Callable[[], float] = time.time):
        if ttl_seconds <= 0 or max_items <= 0:
            raise ValueError("ttl_seconds 与 max_items 必须为正数")
        self.ttl = float(ttl_seconds)
        self.max_items = int(max_items)
        self._clock = clock
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """未命中或已过期返回 None（过期项顺手删掉）。"""
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return None
            if self._clock() - hit[0] >= self.ttl:
                self._items.pop(key, None)
                return None
            return hit[1]

    def put(self, key: str, value: Any) -> None:
        """写入前先清过期项，再按上限淘汰最旧的。"""
        with self._lock:
            now = self._clock()
            for k in [k for k, (ts, _) in self._items.items() if now - ts >= self.ttl]:
                self._items.pop(k, None)
            self._items.pop(key, None)
            while len(self._items) >= self.max_items:
                oldest = min(self._items.items(), key=lambda kv: kv[1][0])[0]
                self._items.pop(oldest, None)
            self._items[key] = (now, value)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
