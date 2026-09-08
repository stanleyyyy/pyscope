"""Lock-protected multi-channel ring buffer with a global sample counter."""
from __future__ import annotations

import threading

import numpy as np


class RingBuffer:
    """Stores the most recent `capacity` frames of `channels` interleaved data.

    `total` counts every frame ever written, which gives every sample a stable
    global index. The trigger engine uses that index for hold-off bookkeeping.
    """

    def __init__(self, capacity: int, channels: int):
        if capacity < 1 or channels < 1:
            raise ValueError("capacity and channels must be >= 1")
        self.capacity = int(capacity)
        self.channels = int(channels)
        self._buf = np.zeros((self.capacity, self.channels), dtype=np.float32)
        self._lock = threading.Lock()
        self.total = 0

    def clear(self) -> None:
        with self._lock:
            self._buf[:] = 0.0
            self.total = 0

    def write(self, block: np.ndarray) -> None:
        block = np.asarray(block, dtype=np.float32)
        if block.ndim != 2 or block.shape[1] != self.channels:
            raise ValueError(f"expected (n, {self.channels}) block, got {block.shape}")
        written = block.shape[0]
        if written == 0:
            return
        n = written
        if n >= self.capacity:
            # Too big to keep whole; drop the oldest part but still advance the
            # global counter so sample indices stay aligned with the stream.
            block = block[-self.capacity:]
            n = self.capacity
        with self._lock:
            # Skipped frames still occupy stream positions.
            pos = (self.total + (written - n)) % self.capacity
            first = min(n, self.capacity - pos)
            self._buf[pos:pos + first] = block[:first]
            if first < n:
                self._buf[:n - first] = block[first:]
            self.total += written

    @property
    def available(self) -> int:
        with self._lock:
            return min(self.total, self.capacity)

    def snapshot(self, n: int | None = None) -> tuple[np.ndarray, int]:
        """Return (frames, start_global_index) for the newest `n` frames."""
        with self._lock:
            avail = min(self.total, self.capacity)
            n = avail if n is None else min(int(n), avail)
            if n <= 0:
                return np.zeros((0, self.channels), dtype=np.float32), self.total
            end = self.total % self.capacity
            start = (end - n) % self.capacity
            if start + n <= self.capacity:
                out = self._buf[start:start + n].copy()
            else:
                tail = self.capacity - start
                out = np.concatenate((self._buf[start:], self._buf[:n - tail]), axis=0)
            return out, self.total - n
