"""Capture sources: real ALSA PCM devices and a hardware-free simulator."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .ring import RingBuffer

try:  # pyalsaaudio is Linux-only; the simulator keeps the app usable elsewhere.
    import alsaaudio
except Exception:  # pragma: no cover - depends on host
    alsaaudio = None


FORMATS = ("S16_LE", "S24_3LE", "S32_LE", "FLOAT_LE")
FORMAT_WIDTH = {"S16_LE": 2, "S24_3LE": 3, "S32_LE": 4, "FLOAT_LE": 4}

COMMON_RATES = (8000, 16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000)


def decode(raw: bytes, fmt: str, channels: int) -> np.ndarray:
    """Decode an interleaved PCM byte block to float32 in [-1, 1], shape (n, ch)."""
    if fmt == "S16_LE":
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif fmt == "S32_LE":
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif fmt == "FLOAT_LE":
        a = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    elif fmt == "S24_3LE":
        b = np.frombuffer(raw, dtype=np.uint8)
        n = b.size // 3
        b = b[: n * 3].reshape(n, 3)
        a = (
            b[:, 0].astype(np.int32)
            | (b[:, 1].astype(np.int32) << 8)
            | (b[:, 2].astype(np.int8).astype(np.int32) << 16)
        ).astype(np.float32) / 8388608.0
    else:
        raise ValueError("unsupported format %r" % (fmt,))
    frames = a.size // channels
    return np.ascontiguousarray(a[: frames * channels].reshape(frames, channels))


def list_alsa_devices() -> list[str]:
    """Capture PCM names, most useful first. Empty list when ALSA is unavailable."""
    if alsaaudio is None:
        return []
    names: list[str] = []
    try:
        names.extend(alsaaudio.pcms(alsaaudio.PCM_CAPTURE))
    except Exception:
        pass
    try:
        for idx, _card in enumerate(alsaaudio.cards()):
            for cand in ("hw:%d,0" % idx, "plughw:%d,0" % idx):
                if cand not in names:
                    names.append(cand)
    except Exception:
        pass
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n in seen or n.startswith(("null", "jack")):
            continue
        seen.add(n)
        out.append(n)
    out.sort(key=lambda n: (0 if n == "default" else 1 if n.startswith("hw:")
                            else 2 if n.startswith("plughw:") else 3, n))
    return out


@dataclass
class SourceConfig:
    device: str = "default"
    rate: int = 48000
    channels: int = 2
    fmt: str = "S16_LE"
    period: int = 1024           # frames per ALSA read
    buffer_seconds: float = 2.0  # ring buffer depth
    simulate: bool = False
    sim_specs: list = field(default_factory=list)


class SourceError(RuntimeError):
    pass


class BaseSource:
    """Background capture thread that fills a RingBuffer."""

    def __init__(self, cfg: SourceConfig):
        self.cfg = cfg
        capacity = max(cfg.period * 4, int(cfg.rate * cfg.buffer_seconds))
        self.ring = RingBuffer(capacity, cfg.channels)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.overruns = 0
        self.blocks = 0
        self.error: str | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._open()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._close()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- to implement ------------------------------------------------------
    def _open(self) -> None:
        pass

    def _close(self) -> None:
        pass

    def _read(self) -> np.ndarray:
        raise NotImplementedError

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                block = self._read()
            except Exception as exc:  # pragma: no cover - hardware dependent
                self.error = str(exc)
                break
            if block is None or len(block) == 0:
                continue
            self.ring.write(block)
            self.blocks += 1
        self._close()


class AlsaSource(BaseSource):
    def __init__(self, cfg: SourceConfig):
        super().__init__(cfg)
        self._pcm = None

    def _open(self) -> None:
        if alsaaudio is None:
            raise SourceError("pyalsaaudio is not installed (pip install pyalsaaudio)")
        fmt_attr = getattr(alsaaudio, "PCM_FORMAT_" + self.cfg.fmt, None)
        if fmt_attr is None:
            raise SourceError("ALSA format %s unsupported by this build" % self.cfg.fmt)
        try:
            self._pcm = alsaaudio.PCM(
                type=alsaaudio.PCM_CAPTURE,
                mode=alsaaudio.PCM_NORMAL,
                device=self.cfg.device,
                channels=self.cfg.channels,
                rate=self.cfg.rate,
                format=fmt_attr,
                periodsize=self.cfg.period,
            )
        except Exception as exc:
            raise SourceError("cannot open %s: %s" % (self.cfg.device, exc)) from exc
        # Report what the driver actually granted; plug devices may resample.
        try:
            info = self._pcm.info()
            self.cfg.rate = int(info.get("rate", self.cfg.rate))
            self.cfg.channels = int(info.get("channels", self.cfg.channels))
        except Exception:
            pass

    def _close(self) -> None:
        if self._pcm is not None:
            try:
                self._pcm.close()
            finally:
                self._pcm = None

    def _read(self) -> np.ndarray:
        empty = np.zeros((0, self.cfg.channels), dtype=np.float32)
        length, raw = self._pcm.read()
        if length < 0:  # -EPIPE: overrun
            self.overruns += 1
            return empty
        if length == 0:
            return empty
        return decode(raw, self.cfg.fmt, self.cfg.channels)


DEFAULT_SIM = [
    {"wave": "sine", "freq": 1000.0, "amp": 0.8, "offset": 0.0, "phase": 0.0,
     "noise": 0.002},
    {"wave": "square", "freq": 250.0, "amp": 0.5, "offset": 0.0, "phase": 0.0,
     "duty": 0.3, "noise": 0.002},
]


class SimSource(BaseSource):
    """Deterministic generator that paces itself in real time.

    Lets every UI feature (trigger, cursors, measurements) be exercised without
    a sound card, which also makes the app testable in CI.
    """

    def __init__(self, cfg: SourceConfig):
        super().__init__(cfg)
        self._n = 0
        self._t0 = 0.0

    def _open(self) -> None:
        self._n = 0
        self._t0 = time.monotonic()

    def specs(self) -> list[dict]:
        specs = [dict(s) for s in (self.cfg.sim_specs or DEFAULT_SIM)]
        while len(specs) < self.cfg.channels:
            base = dict(DEFAULT_SIM[len(specs) % len(DEFAULT_SIM)])
            base["freq"] = DEFAULT_SIM[0]["freq"] * (len(specs) + 1)
            specs.append(base)
        return specs[: self.cfg.channels]

    def _read(self) -> np.ndarray:
        target = self._t0 + (self._n + self.cfg.period) / self.cfg.rate
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(min(delay, 0.2))
        block = self.generate(self._n, self.cfg.period)
        self._n += self.cfg.period
        return block

    def generate(self, start: int, n: int) -> np.ndarray:
        t = (start + np.arange(n, dtype=np.float64)) / self.cfg.rate
        out = np.zeros((n, self.cfg.channels), dtype=np.float32)
        rng = np.random.default_rng(start & 0xFFFF)
        for ch, s in enumerate(self.specs()):
            f = float(s.get("freq", 1000.0))
            amp = float(s.get("amp", 0.5))
            ph = (t * f + float(s.get("phase", 0.0)) / 360.0) % 1.0
            wave = s.get("wave", "sine")
            if wave == "square":
                y = np.where(ph < float(s.get("duty", 0.5)), 1.0, -1.0)
            elif wave == "triangle":
                y = 4 * np.abs(ph - 0.5) - 1.0
            elif wave == "saw":
                y = 2 * ph - 1.0
            elif wave == "noise":
                y = rng.standard_normal(n)
            else:
                y = np.sin(2 * np.pi * ph)
            y = amp * y + float(s.get("offset", 0.0))
            noise = float(s.get("noise", 0.0))
            if noise:
                y = y + noise * rng.standard_normal(n)
            out[:, ch] = np.clip(y, -1.0, 1.0)
        return out


def make_source(cfg: SourceConfig) -> BaseSource:
    return SimSource(cfg) if cfg.simulate else AlsaSource(cfg)
