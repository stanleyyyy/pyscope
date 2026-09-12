"""Persisted settings: the last session, plus named presets.

Kept free of Qt so the schema, merging and file handling can be tested
headlessly; `ui.py` only converts between this dictionary and its widgets.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from .sources import SourceConfig

VERSION = 1
CONFIG_ENV = "PYSCOPE_CONFIG_DIR"   # overridable, mostly for tests


def config_dir() -> Path:
    env = os.environ.get(CONFIG_ENV)
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / "pyscope"


def store_path() -> Path:
    return config_dir() / "settings.json"


def default_channel(index: int) -> dict:
    return {
        "on": index < 2,
        "vdiv": 0.5,
        "position": 2.0 if index == 0 else -2.0 if index == 1 else 0.0,
        "coupling": "DC",
        "invert": False,
    }


def default_state(channels: int | None = None) -> dict:
    cfg = SourceConfig()
    n = channels if channels is not None else cfg.channels
    return {
        "version": VERSION,
        "input": {
            "device": cfg.device,
            "rate": cfg.rate,
            "channels": n,
            "fmt": cfg.fmt,
            "period": cfg.period,
            "buffer_seconds": cfg.buffer_seconds,
            "simulate": cfg.simulate,
            "backend": cfg.backend,
        },
        "channels": [default_channel(i) for i in range(n)],
        "horizontal": {"timebase": 1e-3, "position": 50.0},
        "trigger": {"mode": "auto", "source": 0, "slope": "rising",
                    "level": 0.0, "hysteresis": 0.01, "holdoff": 0.0},
        "cursors": {"time_on": False, "level_on": False, "ref": 0},
    }


def merge(base: dict, override: dict | None) -> dict:
    """Deep-merge `override` onto a copy of `base`; lists replace wholesale."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        elif value is not None:
            out[key] = copy.deepcopy(value)
    return out


def _number(value, fallback, cast=int, lo=None, hi=None):
    """Coerce a value from a hand-editable JSON file, falling back if absurd."""
    try:
        out = cast(value)
    except (TypeError, ValueError):
        return fallback
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def normalise(state: dict | None) -> dict:
    """Fill a partial or foreign state out to a complete, usable one."""
    state = state if isinstance(state, dict) else {}
    defaults = default_state()["input"]
    out = merge(default_state(), state)

    inp = out["input"]
    n = _number(inp.get("channels"), defaults["channels"], int, 1, 32)
    inp["channels"] = n
    inp["rate"] = _number(inp.get("rate"), defaults["rate"], int, 1000, 1000000)
    inp["period"] = _number(inp.get("period"), defaults["period"], int, 16,
                            1 << 20)
    inp["buffer_seconds"] = _number(inp.get("buffer_seconds"),
                                    defaults["buffer_seconds"], float, 0.1, 60.0)
    inp["device"] = str(inp.get("device") or defaults["device"])
    if inp.get("fmt") not in ("S16_LE", "S24_3LE", "S32_LE", "FLOAT_LE"):
        inp["fmt"] = defaults["fmt"]
    inp["simulate"] = bool(inp.get("simulate"))
    if inp.get("backend") not in ("auto", "alsa", "portaudio", "sim"):
        inp["backend"] = defaults["backend"]

    # A stored channel list may be shorter or longer than the channel count.
    chans = out.get("channels")
    if not isinstance(chans, list):
        chans = []
    out["channels"] = [
        merge(default_channel(i),
              chans[i] if i < len(chans) and isinstance(chans[i], dict) else {})
        for i in range(n)
    ]
    out["trigger"]["source"] = _number(out["trigger"].get("source"), 0, int,
                                       0, n - 1)
    out["cursors"]["ref"] = _number(out["cursors"].get("ref"), 0, int, 0, n - 1)
    out["version"] = VERSION
    return out


def empty_store() -> dict:
    return {"version": VERSION, "last": None, "presets": {}}


def load_store(path: Path | None = None) -> dict:
    """Read the store, falling back to an empty one on anything unreadable."""
    path = path or store_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return empty_store()
    if not isinstance(data, dict):
        return empty_store()
    store = empty_store()
    if isinstance(data.get("last"), dict):
        store["last"] = data["last"]
    presets = data.get("presets")
    if isinstance(presets, dict):
        store["presets"] = {str(k): v for k, v in presets.items()
                            if isinstance(v, dict)}
    return store


def save_store(store: dict, path: Path | None = None) -> None:
    """Write the store atomically, so a crash cannot truncate it."""
    path = path or store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def save_preset(name: str, state: dict, path: Path | None = None) -> dict:
    store = load_store(path)
    store["presets"][name] = copy.deepcopy(state)
    save_store(store, path)
    return store


def delete_preset(name: str, path: Path | None = None) -> dict:
    store = load_store(path)
    store["presets"].pop(name, None)
    save_store(store, path)
    return store


def save_last(state: dict, path: Path | None = None) -> dict:
    store = load_store(path)
    store["last"] = copy.deepcopy(state)
    save_store(store, path)
    return store


def state_to_config(state: dict) -> SourceConfig:
    inp = normalise(state)["input"]
    return SourceConfig(device=inp["device"], rate=int(inp["rate"]),
                        channels=int(inp["channels"]), fmt=inp["fmt"],
                        period=int(inp["period"]),
                        buffer_seconds=float(inp["buffer_seconds"]),
                        simulate=bool(inp["simulate"]),
                        backend=inp["backend"])
