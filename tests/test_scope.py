"""Headless tests for the acquisition core (no Qt, no sound card needed)."""
import numpy as np
import pytest

from pyscope import autoset
from pyscope.measure import eng, measure, parse_eng
from pyscope.ring import RingBuffer
from pyscope.sources import SimSource, SourceConfig, decode
from pyscope.trigger import (EITHER, FALLING, NORMAL, RISING, SINGLE,
                             TriggerConfig, TriggerEngine, find_edge,
                             refine_edge)

RATE = 48000


def sine(freq=1000.0, n=4096, rate=RATE, amp=1.0, phase=0.0):
    t = np.arange(n) / rate
    return (amp * np.sin(2 * np.pi * freq * t + phase)).astype(np.float32)


# --------------------------------------------------------------- ring buffer
def test_ring_wraps_and_tracks_global_index():
    rb = RingBuffer(10, 2)
    for i in range(4):
        rb.write(np.full((4, 2), i, dtype=np.float32))
    assert rb.total == 16
    data, start = rb.snapshot(10)
    assert data.shape == (10, 2)
    assert start == 6
    # Newest six frames are all from the last write.
    assert np.all(data[-4:] == 3)
    assert np.all(data[:2] == 1)


def test_ring_snapshot_clamps_to_available():
    rb = RingBuffer(100, 1)
    rb.write(np.ones((5, 1), dtype=np.float32))
    data, start = rb.snapshot(50)
    assert data.shape == (5, 1) and start == 0


def test_ring_write_larger_than_capacity_keeps_tail():
    rb = RingBuffer(8, 1)
    rb.write(np.arange(20, dtype=np.float32).reshape(20, 1))
    data, start = rb.snapshot()
    assert start == 12
    assert data.ravel().tolist() == list(range(12, 20))


# ------------------------------------------------------------------ decoding
def test_decode_s16_roundtrip():
    raw = np.array([0, 16384, -16384, 32767], dtype="<i2").tobytes()
    out = decode(raw, "S16_LE", 2)
    assert out.shape == (2, 2)
    assert out[0, 1] == pytest.approx(0.5)
    assert out[1, 0] == pytest.approx(-0.5)


def test_decode_s24_3le_handles_sign():
    # -1 and +1 in 24-bit little endian.
    raw = bytes([0xFF, 0xFF, 0xFF]) + bytes([0x01, 0x00, 0x00])
    out = decode(raw, "S24_3LE", 1)
    assert out[0, 0] < 0 and out[1, 0] > 0
    assert out[0, 0] == pytest.approx(-1.0 / 8388608.0)


def test_decode_float_and_s32():
    f = np.array([0.25, -0.75], dtype="<f4").tobytes()
    assert decode(f, "FLOAT_LE", 1).ravel().tolist() == pytest.approx([0.25, -0.75])
    i = np.array([2 ** 30], dtype="<i4").tobytes()
    assert decode(i, "S32_LE", 1)[0, 0] == pytest.approx(0.5)


# ------------------------------------------------------------------- trigger
def test_find_edge_rising_and_falling():
    x = sine(1000.0, n=480)          # 10 periods at 48 kHz
    ri = find_edge(x, 0.0, RISING, 0.01)
    fi = find_edge(x, 0.0, FALLING, 0.01)
    assert ri is not None and fi is not None
    assert x[ri] >= 0 >= x[ri - 1]
    assert x[fi] <= 0 <= x[fi - 1]
    assert find_edge(x, 0.0, EITHER, 0.01) == min(ri, fi)


def test_find_edge_needs_arming_below_level():
    x = np.concatenate([np.full(50, 0.9), sine(1000.0, n=430)]).astype(np.float32)
    idx = find_edge(x, 0.5, RISING, 0.05)
    assert idx is not None and idx > 50   # not triggered by the initial high level


def test_hysteresis_rejects_noise_on_the_threshold():
    rng = np.random.default_rng(0)
    x = (0.01 * rng.standard_normal(2000)).astype(np.float32)
    assert find_edge(x, 0.0, RISING, 0.2) is None    # noise is inside the band
    assert find_edge(x, 0.0, RISING, 0.0) is not None


def test_find_edge_returns_none_when_level_unreachable():
    assert find_edge(sine(n=512), 5.0, RISING, 0.0) is None


def test_refine_edge_interpolates():
    x = np.array([-1.0, 1.0])
    assert refine_edge(x, 1, 0.0) == pytest.approx(0.5)


def test_engine_places_trigger_at_requested_position():
    x = sine(1000.0, n=20000)
    block = np.stack([x, x], axis=1)
    eng_ = TriggerEngine(TriggerConfig(level=0.0, slope=RISING, hysteresis=0.05,
                                       mode=NORMAL, position=0.5))
    frame = eng_.acquire(block, 0, RATE, 4800)
    assert frame is not None and frame.triggered
    assert frame.data.shape == (4800, 2)
    assert frame.trigger_index == 2400
    assert frame.t[frame.trigger_index] == pytest.approx(0.0, abs=1e-9)
    # Signal crosses the level upward at the trigger point.
    assert frame.data[frame.trigger_index, 0] >= 0.0
    assert frame.data[frame.trigger_index - 1, 0] <= 0.05


def test_engine_position_zero_shows_only_post_trigger():
    x = sine(1000.0, n=20000)
    block = np.stack([x], axis=1)
    eng_ = TriggerEngine(TriggerConfig(mode=NORMAL, hysteresis=0.05, position=0.0))
    frame = eng_.acquire(block, 0, RATE, 1000)
    assert frame is not None and frame.trigger_index == 0
    assert frame.t[0] == pytest.approx(0.0)


def test_normal_mode_returns_nothing_without_an_edge():
    block = np.zeros((20000, 1), dtype=np.float32)
    eng_ = TriggerEngine(TriggerConfig(level=0.5, mode=NORMAL))
    assert eng_.acquire(block, 0, RATE, 1000) is None


def test_auto_mode_free_runs_without_an_edge():
    block = np.zeros((20000, 1), dtype=np.float32)
    eng_ = TriggerEngine(TriggerConfig(level=0.5))   # auto is the default
    frame = eng_.acquire(block, 0, RATE, 1000)
    assert frame is not None and not frame.triggered


def test_single_mode_fires_once():
    block = np.stack([sine(1000.0, n=20000)], axis=1)
    eng_ = TriggerEngine(TriggerConfig(mode=SINGLE, hysteresis=0.05))
    assert eng_.acquire(block, 0, RATE, 1000) is not None
    assert eng_.acquire(block, 0, RATE, 1000) is None
    eng_.reset()
    assert eng_.acquire(block, 0, RATE, 1000) is not None


def test_holdoff_suppresses_the_next_trigger():
    block = np.stack([sine(1000.0, n=40000)], axis=1)
    cfg = TriggerConfig(mode=NORMAL, hysteresis=0.05, holdoff=0.1)
    eng_ = TriggerEngine(cfg)
    first = eng_.acquire(block, 0, RATE, 1000)
    assert first is not None
    first_global = eng_.last_trigger_global
    second = eng_.acquire(block, 0, RATE, 1000)
    assert second is not None
    assert eng_.last_trigger_global - first_global >= 0.1 * RATE


def test_engine_needs_a_full_record():
    block = np.stack([sine(n=100)], axis=1)
    eng_ = TriggerEngine(TriggerConfig())
    assert eng_.acquire(block, 0, RATE, 1000) is None


def test_trigger_source_selects_the_channel():
    quiet = np.zeros(20000, dtype=np.float32)
    active = sine(1000.0, n=20000)
    block = np.stack([quiet, active], axis=1)
    eng_ = TriggerEngine(TriggerConfig(source=1, mode=NORMAL, hysteresis=0.05))
    assert eng_.acquire(block, 0, RATE, 1000) is not None
    eng_.cfg.source = 0
    eng_.reset()
    assert eng_.acquire(block, 0, RATE, 1000) is None


# -------------------------------------------------------------- measurements
def test_measure_sine():
    m = measure(sine(1000.0, n=RATE // 10, amp=0.8), RATE)
    assert m["vpp"] == pytest.approx(1.6, rel=0.02)
    assert m["rms"] == pytest.approx(0.8 / np.sqrt(2), rel=0.02)
    assert m["mean"] == pytest.approx(0.0, abs=0.01)
    assert m["freq"] == pytest.approx(1000.0, rel=0.01)
    assert m["period"] == pytest.approx(1e-3, rel=0.01)


def test_measure_square_duty():
    t = np.arange(RATE // 10) / RATE
    ph = (t * 500.0) % 1.0
    x = np.where(ph < 0.25, 1.0, -1.0)
    m = measure(x, RATE)
    assert m["freq"] == pytest.approx(500.0, rel=0.02)
    assert m["duty"] == pytest.approx(25.0, abs=1.5)
    assert m["vpp"] == pytest.approx(2.0, rel=1e-6)


def test_measure_dc_has_no_frequency():
    m = measure(np.full(1000, 0.3), RATE)
    assert m["mean"] == pytest.approx(0.3)
    assert m["vpp"] == pytest.approx(0.0)
    assert not np.isfinite(m["freq"])


def test_measure_empty_is_all_nan():
    m = measure(np.array([]), RATE)
    assert all(not np.isfinite(v) for v in m.values())


def test_eng_formatting():
    assert eng(0.001234, "s").endswith("ms")
    assert eng(1234.0, "Hz").startswith("1.234 k")
    assert eng(float("nan")) == "--"
    assert eng(0.0, "V") == "0 V"


# ------------------------------------------------------------- simulator e2e
def test_simulator_feeds_the_trigger_engine():
    cfg = SourceConfig(rate=RATE, channels=2, period=1024, simulate=True)
    src = SimSource(cfg)
    block = src.generate(0, 20000)
    assert block.shape == (20000, 2)
    eng_ = TriggerEngine(TriggerConfig(mode=NORMAL, hysteresis=0.05))
    frame = eng_.acquire(block, 0, RATE, 4800)
    assert frame is not None and frame.triggered
    m = measure(frame.data[:, 0], RATE)
    assert m["freq"] == pytest.approx(1000.0, rel=0.02)   # CH1 default is 1 kHz


def test_simulator_channel_count_is_honoured():
    src = SimSource(SourceConfig(rate=RATE, channels=5, simulate=True))
    assert src.generate(0, 256).shape == (256, 5)
    assert len(src.specs()) == 5


# ------------------------------------------------------------------- autoset
def test_snap_rounds_up_and_near():
    steps = [1e-3, 2e-3, 5e-3, 1e-2]
    assert autoset.snap(2.5e-3, steps, "up") == 5e-3
    assert autoset.snap(2.5e-3, steps, "near") == 2e-3
    assert autoset.snap(99.0, steps, "up") == 1e-2       # clamps to the top
    assert autoset.snap(float("nan"), steps, "up") in steps


def test_autoset_picks_the_strongest_channel_and_fits_it():
    weak = sine(1000.0, n=RATE // 4, amp=0.05)
    strong = sine(250.0, n=RATE // 4, amp=0.6)
    block = np.stack([weak, strong], axis=1)
    p = autoset.plan(block, RATE)

    assert p.found and p.source == 1
    assert all(c.active for c in p.channels)
    # Two active channels share the 8 divisions, so each is sized to ~3.75:
    # 1.2 Vpp -> 0.5 FS/div, 0.1 Vpp -> 0.05 FS/div.
    assert p.channels[1].vdiv == pytest.approx(0.5)
    assert p.channels[0].vdiv == pytest.approx(0.05)
    # Three cycles of 250 Hz across ten divisions -> 1.2 ms/div, snapped to 1 ms.
    assert p.timebase == pytest.approx(1e-3)
    assert p.level == pytest.approx(0.0, abs=0.02)
    assert p.hysteresis == pytest.approx(0.05 * 1.2, rel=0.1)


def test_autoset_centres_a_dc_offset_signal():
    x = sine(1000.0, n=RATE // 4, amp=0.2) + 0.5
    p = autoset.plan(np.stack([x], axis=1), RATE)
    cp = p.channels[0]
    # Gain opens up from 0.1 so the 0.5 FS offset fits the position range,
    # then the trace is pushed down by exactly that offset.
    assert cp.vdiv == pytest.approx(0.2)
    assert cp.position == pytest.approx(-0.5 / cp.vdiv, rel=0.05)
    assert abs(cp.position) <= autoset.Y_LIMIT
    assert p.level == pytest.approx(0.5, abs=0.02)


def test_autoset_spreads_multiple_active_channels():
    # The simulator's own amplitudes: near full scale, which is the case that
    # overflows the graticule if stacked traces are each sized for 6 divisions.
    block = np.stack([sine(1000.0, n=RATE // 4, amp=0.8),
                      sine(250.0, n=RATE // 4, amp=0.5)], axis=1)
    p = autoset.plan(block, RATE)
    assert p.channels[0].position > p.channels[1].position   # stacked, not overlaid
    # Neither trace may run off the graticule once stacked.
    for cp in p.channels:
        assert abs(cp.position) + 0.5 * cp.vpp / cp.vdiv <= autoset.Y_DIVS / 2


def test_autoset_reports_no_signal_on_silence():
    block = np.zeros((RATE // 4, 2), dtype=np.float32)
    p = autoset.plan(block, RATE)
    assert not p.found
    assert not any(c.active for c in p.channels)


def test_autoset_falls_back_to_a_default_timebase_without_a_frequency():
    block = np.full((RATE // 4, 1), 0.5, dtype=np.float32)   # DC only
    p = autoset.plan(block, RATE)
    assert p.timebase == pytest.approx(1e-3)


def test_autoset_step_tables_are_ordered_and_cover_the_range():
    assert autoset.VDIV_STEPS[0] == pytest.approx(1e-4)
    assert autoset.VDIV_STEPS[-1] == pytest.approx(1.0)
    assert autoset.TIMEBASE_STEPS == sorted(autoset.TIMEBASE_STEPS)


# ------------------------------------------------------- engineering parsing
@pytest.mark.parametrize("text,expected", [
    ("500 us", 500e-6), ("20 mFS", 0.02), ("-0.0005", -5e-4), ("1.5k", 1500.0),
    ("2 ms", 2e-3), ("50 %", 50.0), ("1.234 kHz", 1234.0), ("0.5 s", 0.5),
    (".5m", 5e-4), ("1e3", 1000.0), ("  7 ", 7.0), ("2,5", 2.5),
])
def test_parse_eng_reads_what_eng_writes(text, expected):
    assert parse_eng(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "abc", "FS", "--3", None])
def test_parse_eng_rejects_junk(text):
    assert parse_eng(text) is None


@pytest.mark.parametrize("value,unit", [
    (500e-6, "s"), (0.02, "FS"), (-5e-4, "FS"), (1234.0, "Hz"), (0.0, "FS"),
])
def test_eng_and_parse_eng_round_trip(value, unit):
    assert parse_eng(eng(value, unit)) == pytest.approx(value, rel=1e-3,
                                                       abs=1e-12)


def test_hysteresis_wider_than_the_signal_blocks_every_edge():
    """The failure that looks like a broken trigger: a 5 mFS signal cannot
    arm across a 10 mFS band, so the fix is to scale hysteresis to the signal."""
    x = (0.0025 * np.sin(2 * np.pi * 1000 * np.arange(4800) / RATE)).astype(
        np.float32)
    assert find_edge(x, 0.0, RISING, 0.01) is None
    assert find_edge(x, 0.0, RISING, 0.05 * (x.max() - x.min())) is not None
