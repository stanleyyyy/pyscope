"""Autoset: derive sensible vertical, horizontal and trigger settings from data.

Kept free of Qt so the decision logic can be tested headlessly; `ui.py` only
pushes the resulting plan into the widgets.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import X_DIVS, Y_DIVS
from .measure import measure

TARGET_DIVS = 6.0     # vertical divisions a lone signal should fill
TARGET_CYCLES = 3.0   # periods that should span the screen
SILENCE = 2e-3        # Vpp below this counts as no signal (~ -54 dBFS)
MARGIN = 0.5          # divisions kept clear at the top and bottom
Y_LIMIT = Y_DIVS / 2.0 - MARGIN   # how far a trace may be positioned


def seq_125(lo: float, hi: float) -> list[float]:
    """1-2-5 sequence covering [lo, hi], the way scope knobs step."""
    out: list[float] = []
    exp = math.floor(math.log10(lo))
    while True:
        for m in (1.0, 2.0, 5.0):
            v = m * (10.0 ** exp)
            if v < lo * 0.999:
                continue
            if v > hi * 1.001:
                return out
            out.append(v)
        exp += 1


VDIV_STEPS = seq_125(1e-4, 1.0)          # full-scale units per division
TIMEBASE_STEPS = seq_125(1e-6, 1.0)      # seconds per division


def snap(value: float, steps: list[float], mode: str = "up") -> float:
    """Nearest step at or above (`up`) / nearest in log distance (`near`)."""
    if not np.isfinite(value) or value <= 0:
        return steps[len(steps) // 2]
    if mode == "up":
        for s in steps:
            if s >= value * 0.999:
                return s
        return steps[-1]
    best = min(steps, key=lambda s: abs(math.log10(s) - math.log10(value)))
    return best


@dataclass
class ChannelPlan:
    index: int
    active: bool
    vpp: float
    centre: float
    freq: float
    vdiv: float
    position: float


@dataclass
class AutosetPlan:
    channels: list[ChannelPlan] = field(default_factory=list)
    found: bool = False
    source: int = 0
    level: float = 0.0
    hysteresis: float = 0.01
    timebase: float = 1e-3


def plan(block: np.ndarray, rate: int) -> AutosetPlan:
    """Choose gain, position, timebase and trigger for a captured block."""
    block = np.atleast_2d(np.asarray(block, dtype=np.float64))
    if block.ndim != 2 or block.shape[0] < 2:
        return AutosetPlan()

    stats = [measure(block[:, c], rate) for c in range(block.shape[1])]
    active = [c for c, m in enumerate(stats) if m["vpp"] >= SILENCE]

    # Stacked traces share the screen, so each gets a slice of the height
    # rather than all of it - otherwise two channels overflow the graticule.
    height = min(TARGET_DIVS, (Y_DIVS - MARGIN) / max(len(active), 1))

    plans: list[ChannelPlan] = []
    for c, m in enumerate(stats):
        vdiv = snap(m["vpp"] / height, VDIV_STEPS, "up")
        # Midpoint, not mean: it stays centred for asymmetric duty cycles.
        centre = 0.5 * (m["vmax"] + m["vmin"])
        # A large DC offset needs more position travel than the screen has, so
        # open the gain up until the trace can actually be centred.
        while abs(centre) / vdiv > Y_LIMIT and vdiv < VDIV_STEPS[-1]:
            vdiv = VDIV_STEPS[VDIV_STEPS.index(vdiv) + 1]
        plans.append(ChannelPlan(index=c, active=c in active, vpp=m["vpp"],
                                 centre=centre, freq=m["freq"], vdiv=vdiv,
                                 position=0.0))

    # Spread the traces that carry signal evenly, then centre each one on its
    # own DC level so it sits in its slot rather than at the screen edge.
    top = Y_DIVS / 2.0 - height / 2.0
    slots = (np.linspace(top, -top, len(active)) if len(active) > 1
             else np.zeros(max(len(active), 1)))
    for slot, c in zip(slots, active):
        p = plans[c]
        p.position = float(np.clip(slot - p.centre / p.vdiv, -Y_LIMIT, Y_LIMIT))

    result = AutosetPlan(channels=plans, found=bool(active))
    if not active:
        return result

    # Trigger on the strongest signal; midpoint level is the most reliable.
    src = max(active, key=lambda c: stats[c]["vpp"])
    m = stats[src]
    result.source = src
    result.level = float(np.clip(0.5 * (m["vmax"] + m["vmin"]), -1.0, 1.0))
    result.hysteresis = float(np.clip(0.05 * m["vpp"], 1e-4, 0.5))

    freq = m["freq"]
    if np.isfinite(freq) and freq > 0:
        result.timebase = snap(TARGET_CYCLES / (freq * 10.0), TIMEBASE_STEPS,
                               "near")
    else:
        result.timebase = 1e-3
    return result
