"""Edge trigger engine with hysteresis, hold-off and pre-trigger positioning."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

RISING = "rising"
FALLING = "falling"
EITHER = "either"

AUTO = "auto"
NORMAL = "normal"
SINGLE = "single"


def find_edge(x: np.ndarray, level: float, slope: str = RISING,
              hysteresis: float = 0.0, start: int = 0) -> int | None:
    """Index of the first qualifying edge in `x` at or after `start`.

    A rising edge needs the signal to first sit below `level - hysteresis`
    (arming) and then reach `level + hysteresis`; that suppresses retriggering
    on noise riding on the threshold.
    """
    x = np.asarray(x)
    if x.ndim != 1 or x.size < 2:
        return None
    if slope == EITHER:
        a = find_edge(x, level, RISING, hysteresis, start)
        b = find_edge(x, level, FALLING, hysteresis, start)
        cands = [i for i in (a, b) if i is not None]
        return min(cands) if cands else None
    if slope == FALLING:
        idx = find_edge(-x, -level, RISING, hysteresis, start)
        return idx

    h = abs(float(hysteresis))
    lo, hi = float(level) - h, float(level) + h
    armed_idx = np.flatnonzero(x[start:] < lo)
    if armed_idx.size == 0:
        return None
    i = int(armed_idx[0]) + start
    fired = np.flatnonzero(x[i:] >= hi)
    if fired.size == 0:
        return None
    return int(fired[0]) + i


def refine_edge(x: np.ndarray, idx: int, level: float) -> float:
    """Sub-sample crossing position, so the trace does not jitter by a sample."""
    if idx <= 0 or idx >= len(x):
        return float(idx)
    y0, y1 = float(x[idx - 1]), float(x[idx])
    if y1 == y0:
        return float(idx)
    frac = (float(level) - y0) / (y1 - y0)
    return (idx - 1) + min(max(frac, 0.0), 1.0)


@dataclass
class TriggerConfig:
    source: int = 0
    level: float = 0.0
    slope: str = RISING
    hysteresis: float = 0.01
    mode: str = AUTO
    holdoff: float = 0.0   # seconds between accepted triggers
    position: float = 0.5  # fraction of the record shown before the trigger


@dataclass
class Frame:
    """One acquisition ready for display."""
    data: np.ndarray        # (n, channels)
    t: np.ndarray           # seconds, 0.0 at the trigger point
    triggered: bool
    rate: int
    trigger_index: int      # sample index of the trigger within `data`


class TriggerEngine:
    """Turns the free-running ring buffer into stable, positioned records."""

    def __init__(self, cfg: TriggerConfig | None = None):
        self.cfg = cfg or TriggerConfig()
        self.last_trigger_global: int | None = None
        self.armed_single = True

    def reset(self) -> None:
        self.last_trigger_global = None
        self.armed_single = True

    def acquire(self, block: np.ndarray, start_global: int, rate: int,
                record_len: int) -> Frame | None:
        """Search `block` (starting at global sample `start_global`) for a record.

        Returns None when nothing can be shown yet (normal/single mode with no
        edge, or not enough data buffered).
        """
        cfg = self.cfg
        n = block.shape[0]
        record_len = int(record_len)
        if record_len < 2 or n < record_len:
            return None
        pre = int(round(min(max(cfg.position, 0.0), 1.0) * (record_len - 1)))
        post = record_len - pre

        src = min(max(cfg.source, 0), block.shape[1] - 1)
        x = block[:, src]

        # Only edges with a full record around them are usable.
        search = pre
        holdoff_samples = int(cfg.holdoff * rate)
        if self.last_trigger_global is not None and holdoff_samples > 0:
            earliest = self.last_trigger_global + holdoff_samples - start_global
            search = max(search, int(earliest))
        limit = n - post

        idx = None
        if search < limit and (cfg.mode != SINGLE or self.armed_single):
            cand = find_edge(x, cfg.level, cfg.slope, cfg.hysteresis, search)
            # A later edge would be even further right, so one probe is enough.
            if cand is not None and cand < limit:
                idx = cand

        if idx is not None:
            self.last_trigger_global = start_global + idx
            if cfg.mode == SINGLE:
                self.armed_single = False
            return self._frame(block, idx, pre, record_len, rate, True)

        if cfg.mode == AUTO:
            # Free-run: show the newest record so the user still sees the signal.
            idx = n - post
            return self._frame(block, idx, pre, record_len, rate, False)
        return None

    @staticmethod
    def _frame(block: np.ndarray, idx: int, pre: int, record_len: int,
               rate: int, triggered: bool) -> Frame:
        s = idx - pre
        data = block[s:s + record_len]
        t = (np.arange(record_len, dtype=np.float64) - pre) / rate
        return Frame(data=data, t=t, triggered=triggered, rate=rate,
                     trigger_index=pre)
