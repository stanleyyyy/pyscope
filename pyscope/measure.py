"""Automatic waveform measurements on a single captured record."""
from __future__ import annotations

import numpy as np

MEASUREMENTS = ("vpp", "vmax", "vmin", "mean", "rms", "std",
                "freq", "period", "duty", "rise")


def _crossings(x: np.ndarray, level: float, hyst: float, rising: bool) -> np.ndarray:
    """Interpolated indices of every hysteresis-qualified crossing."""
    lo, hi = level - hyst, level + hyst
    s = x if rising else -x
    lo2, hi2 = (lo, hi) if rising else (-hi, -lo)
    out: list[float] = []
    armed = False
    prev = s[0]
    for i in range(1, s.size):
        v = s[i]
        if not armed:
            if v < lo2:
                armed = True
        elif v >= hi2:
            y0, y1 = prev, v
            frac = 0.0 if y1 == y0 else (hi2 - y0) / (y1 - y0)
            out.append((i - 1) + min(max(frac, 0.0), 1.0))
            armed = False
        prev = v
    return np.asarray(out, dtype=np.float64)


def _freq_fft(x: np.ndarray, rate: int) -> float:
    n = x.size
    if n < 8:
        return float("nan")
    w = np.hanning(n)
    spec = np.abs(np.fft.rfft((x - x.mean()) * w))
    if spec.size < 3:
        return float("nan")
    k = int(np.argmax(spec[1:]) + 1)
    if k <= 0 or k >= spec.size - 1:
        return k * rate / n
    # Parabolic interpolation around the peak bin.
    a, b, c = spec[k - 1], spec[k], spec[k + 1]
    denom = a - 2 * b + c
    delta = 0.0 if denom == 0 else 0.5 * (a - c) / denom
    return float((k + delta) * rate / n)


def measure(x: np.ndarray, rate: int) -> dict:
    """Compute standard scope measurements for one channel of a record."""
    x = np.asarray(x, dtype=np.float64).ravel()
    res = {k: float("nan") for k in MEASUREMENTS}
    if x.size == 0:
        return res
    vmax, vmin = float(x.max()), float(x.min())
    res.update(vmax=vmax, vmin=vmin, vpp=vmax - vmin, mean=float(x.mean()),
               rms=float(np.sqrt(np.mean(x * x))), std=float(x.std()))

    amplitude = vmax - vmin
    if amplitude < 1e-9:
        return res
    mid = 0.5 * (vmax + vmin)
    hyst = 0.05 * amplitude

    rises = _crossings(x, mid, hyst, rising=True)
    falls = _crossings(x, mid, hyst, rising=False)

    if rises.size >= 2:
        period = float(np.mean(np.diff(rises))) / rate
    else:
        f = _freq_fft(x, rate)
        period = 1.0 / f if f and np.isfinite(f) and f > 0 else float("nan")
    if np.isfinite(period) and period > 0:
        res["period"] = period
        res["freq"] = 1.0 / period

    # Duty cycle from the first complete rise -> fall -> rise sequence.
    if rises.size >= 2 and falls.size >= 1:
        r0 = rises[0]
        after = falls[falls > r0]
        if after.size:
            high = float(after[0] - r0)
            full = float(rises[1] - r0)
            if full > 0:
                res["duty"] = 100.0 * high / full

    # 10-90% rise time on the first rising edge.
    if rises.size >= 1:
        lo_lvl, hi_lvl = vmin + 0.1 * amplitude, vmin + 0.9 * amplitude
        i = int(rises[0])
        j = i
        while j > 0 and x[j] > lo_lvl:
            j -= 1
        k = i
        while k < x.size - 1 and x[k] < hi_lvl:
            k += 1
        if k > j:
            res["rise"] = (k - j) / rate
    return res


def eng(value: float, unit: str = "", digits: int = 4) -> str:
    """Engineering-notation formatting, e.g. 1.234 kHz / 12.50 us."""
    if value is None or not np.isfinite(value):
        return "--"
    if value == 0:
        return "0 " + unit if unit else "0"
    prefixes = [(1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"),
                (1e-6, "u"), (1e-9, "n"), (1e-12, "p")]
    a = abs(value)
    for scale, p in prefixes:
        if a >= scale:
            return "%.*g %s%s" % (digits, value / scale, p, unit)
    return "%.*g %s" % (digits, value, unit)
