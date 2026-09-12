"""Offscreen UI smoke test: build the window, run the simulator, save a PNG.

    QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py [out.png]

Exercises the whole pipeline (capture thread -> ring -> trigger -> plot ->
measurements -> cursors) without a sound card or a visible display.
"""
import os
import sys

import pytest
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never touch the real settings file from a test run.
os.environ.setdefault("PYSCOPE_CONFIG_DIR",
                      os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "_smoke_config"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyqtgraph.Qt import QtCore, QtWidgets  # noqa: E402

from pyscope import settings  # noqa: E402
from pyscope.__main__ import parse_args, resolve_state  # noqa: E402
from pyscope.autoset import VDIV_STEPS  # noqa: E402
from pyscope.sources import SourceConfig  # noqa: E402
from pyscope.ui import ScopeWindow  # noqa: E402


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "smoke.png"
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    cfg = SourceConfig(rate=48000, channels=2, period=512, simulate=True)
    win = ScopeWindow(cfg)
    win.show()

    win.trg_mode.setCurrentText("normal")
    win.trg_level.setValue(0.0)
    win.tb_knob.setValue(500e-6)
    win.cur_t_on.setChecked(True)
    win.cur_y_on.setChecked(True)

    deadline = time.time() + 3.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
        if win.frame is not None and win.frame.triggered and win.table.rowCount():
            break

    assert win.source is not None and win.source.running, "capture thread died"
    assert win.frame is not None, "no frame acquired"
    assert win.frame.triggered, "never triggered on the simulated 1 kHz sine"
    assert win.table.rowCount() == 2, "measurement rows missing"
    freq = win.table.item(0, 6).text()
    print("CH1 measured frequency:", freq)
    num, prefix = freq.split(" ", 1)
    hz = float(num) * (1000.0 if prefix.startswith("k") else 1.0)
    assert abs(hz - 1000.0) < 10.0, "expected ~1 kHz on CH1, got %s" % freq
    print("cursors:", win.cursor_label.text())
    print("status:", win.status_label.text())

    # --- mouse-driven trigger: drag the level line and the T marker --------
    strip = win.strips[0]
    win.trig_line.setPos(1.0 + strip.position.value())      # 1 division up
    win._trig_line_moved()
    assert abs(win.trg_level.value() - strip.scale) < 1e-6, "level drag ignored"
    assert "TRIG CH1" in win.trig_line.label.format

    lo, hi = win._time_span()
    win.trig_marker.setPos(lo + 0.2 * (hi - lo))
    win._trig_marker_moved()
    assert win.pos_knob.value() == 20, "trigger point drag ignored"
    assert win.engine.cfg.position == 0.5 - 0.3

    # --- autoset: it should find the simulated signals on its own ----------
    win.tb_knob.setIndex(0)                                # 1 us/div, far off
    win.trg_level.setValue(0.9)                             # level off the signal
    for st in win.strips:
        st.enable.setChecked(False)
    win.autoset()
    deadline = time.time() + 3.0
    while win._autoset_pending and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not win._autoset_pending, "autoset never found enough data"
    assert all(st.enable.isChecked() for st in win.strips), "channels not re-enabled"
    assert win.trg_src.currentIndex() == 0, "should trigger on the larger CH1"
    assert abs(win.trg_level.value()) < 0.05, "level should land mid-waveform"
    cycles = win._timebase() * 10 * 1000.0        # screen widths of 1 kHz
    assert 1.5 <= cycles <= 5.0, (
        "expected a few cycles on screen, got %.1f at %s/div"
        % (cycles, win.tb_knob.text()))
    assert win.pos_knob.value() == 50
    print("autoset:", win.status.currentMessage())

    deadline = time.time() + 2.0
    while time.time() < deadline and not (win.frame and win.frame.triggered):
        app.processEvents()
        time.sleep(0.01)
    assert win.frame is not None and win.frame.triggered, "not running after autoset"

    # --- a level parked off the signal must explain itself, not just freeze -
    win.trg_mode.setCurrentText("normal")
    win.trg_src.setCurrentIndex(0)
    assert "TRIG CH1" in win.trig_line.label.format
    win.trg_src.setCurrentIndex(1)
    assert "TRIG CH2" in win.trig_line.label.format, "source change not shown"
    assert win.trig_line.pen.color().name() == win.strips[1].color, (
        "trigger line should wear the source channel's colour")

    win.trg_level.setValue(0.99)          # above anything the simulator makes
    win.frame = None
    deadline = time.time() + 1.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert win.frame is None, "normal mode must not draw without an edge"
    assert "NO TRIG" in win.status_label.text(), win.status_label.text()
    assert "outside" in win.status_label.text(), win.status_label.text()
    print("starved:", win.status_label.text())

    win.level_to_50()                     # the one-click fix
    deadline = time.time() + 2.0
    while time.time() < deadline and not (win.frame and win.frame.triggered):
        app.processEvents()
        time.sleep(0.01)
    assert win.frame is not None and win.frame.triggered, "50% level did not trigger"
    print("after level_to_50:", win.status_label.text())

    win.trg_src.setCurrentIndex(0)
    win.trg_mode.setCurrentText("auto")
    win.level_to_50()
    deadline = time.time() + 2.0
    while time.time() < deadline and not (win.frame and win.frame.triggered):
        app.processEvents()
        time.sleep(0.01)

    # --- knobs: wheel, drag, snapping and reset ---------------------------
    from pyqtgraph.Qt import QtGui
    from pyscope.knobs import RangeKnob, StepKnob

    k = win.strips[0].vdiv
    assert isinstance(k, StepKnob)
    start = k.value()
    k._nudge(1)                                     # one wheel click up
    assert k.value() > start and k.value() in VDIV_STEPS, "step knob off grid"
    k._nudge(-1)
    assert k.value() == start
    k.setValue(0.037)                               # arbitrary value snaps
    assert k.value() in VDIV_STEPS

    lvl = win.trg_level
    assert isinstance(lvl, RangeKnob)
    seen = []
    lvl.valueChanged.connect(seen.append)
    lvl.setValue(0.25)
    assert seen and abs(lvl.value() - 0.25) < 1e-9, "range knob did not emit"
    lvl.setValue(99.0)
    assert lvl.value() == 1.0, "range knob must clamp"
    lvl.reset()
    assert lvl.value() == 0.0, "double-click reset should return the default"

    # A knob must render without a live paint device backing it.
    pix = QtGui.QPixmap(k.size())
    k.render(pix)

    assert "CH1" in win.trg_group.title(), win.trg_group.title()
    win.trg_src.setCurrentIndex(1)
    assert "CH2" in win.trg_group.title(), win.trg_group.title()
    win.trg_src.setCurrentIndex(0)
    print("trigger group titled:", win.trg_group.title())

    # --- typing into a knob's field, and auto hysteresis -------------------
    k = win.strips[0].vdiv
    k.edit.setText("20 mFS")
    k.edit.editingFinished.emit()
    assert k.value() == pytest.approx(0.02), "typed value not applied"
    k.edit.setText("nonsense")
    k.edit.editingFinished.emit()
    assert k.value() == pytest.approx(0.02), "junk must not change the value"
    assert k.edit.text() == k.text(), "field should snap back to the real value"

    win.tb_knob.edit.setText("500 us")
    win.tb_knob.edit.editingFinished.emit()
    assert win.tb_knob.value() == pytest.approx(500e-6)

    # A weak signal must still trigger: hysteresis follows the amplitude in
    # auto mode, then carries over to normal.
    win.trg_mode.setCurrentText("auto")
    assert not win.trg_hyst.isEnabled(), "auto mode owns the hysteresis knob"
    win.source.cfg.sim_specs = [{"wave": "sine", "freq": 1000.0, "amp": 0.0025},
                                {"wave": "sine", "freq": 250.0, "amp": 0.002}]
    win.strips[0].vdiv.setValue(0.001)
    win.trg_level.setValue(0.0)
    # Let the ring refill, otherwise the first frame is still the loud signal.
    settle = time.time() + 0.6
    while time.time() < settle:
        app.processEvents()
        time.sleep(0.01)
    win.trg_mode.setCurrentText("normal")
    assert win.trg_hyst.isEnabled(), "normal mode hands the knob back"
    assert win.trg_hyst.edit.isEnabled(), "and its field with it"
    win.frame = None
    deadline = time.time() + 3.0
    while time.time() < deadline and not (win.frame and win.frame.triggered):
        app.processEvents()
        time.sleep(0.01)
    assert win.engine.cfg.hysteresis < 0.001, (
        "hysteresis did not follow the small signal: %r"
        % win.engine.cfg.hysteresis)
    assert win.frame is not None and win.frame.triggered, (
        "a 5 mFS signal must trigger: %s" % win.status_label.text())
    print("weak signal: hysteresis %.6f, %s"
          % (win.engine.cfg.hysteresis, win.status_label.text()))
    win.source.cfg.sim_specs = []

    # --- a real PortAudio device, when this host has one -------------------
    from pyscope import sources
    inputs = sources.list_portaudio_devices()
    if inputs:
        state = resolve_state(parse_args(["--backend", "portaudio",
                                          "-d", "default", "-c", "1",
                                          "-r", "48000", "--no-restore"]))
        win3 = ScopeWindow(settings.state_to_config(state), restore=state)
        win3.show()
        assert win3.backend_combo.currentText() == "portaudio"
        assert not win3.fmt_combo.isEnabled(), "format is ALSA-only"
        deadline = time.time() + 3.0
        while time.time() < deadline and (win3.source is None
                                          or win3.source.blocks < 10):
            app.processEvents()
            time.sleep(0.01)
        assert win3.source is not None and win3.source.running, (
            "PortAudio capture did not start: %s" % win3.status_label.text())
        assert win3.source.blocks >= 10, "no audio blocks arrived"
        assert win3.status_label.text().startswith("portaudio:")
        print("portaudio live:", win3.status_label.text())
        win3.close()
    else:
        print("portaudio: no input device on this host, live check skipped")

    # Leave the screen in a representative state for the screenshot.
    win.autoset()
    deadline = time.time() + 3.0
    while time.time() < deadline and not (win.frame and win.frame.triggered):
        app.processEvents()
        time.sleep(0.01)

    # --- command line settings must survive into the widgets ---------------
    state = resolve_state(parse_args(["-d", "hw:2,0", "-c", "4", "-r", "96000",
                                      "-f", "S32_LE", "--simulate"]))
    win2 = ScopeWindow(settings.state_to_config(state), restore=state)
    win2.show()
    assert win2.dev_combo.currentText() == "hw:2,0", (
        "command line device lost: %r" % win2.dev_combo.currentText())
    assert win2.rate_combo.currentText() == "96000"
    assert win2.chan_spin.value() == 4
    assert win2.fmt_combo.currentText() == "S32_LE"
    assert len(win2.strips) == 4
    assert win2.source is not None and win2.source.running, (
        "capture should be running as soon as the window opens")
    assert win2.running

    # --- presets round-trip through the real widgets -----------------------
    win2.tb_knob.setValue(2e-4)
    win2.strips[0].vdiv.setValue(0.05)
    win2.strips[2].enable.setChecked(True)
    win2.trg_src.setCurrentIndex(2)
    win2.trg_slope.setCurrentText("falling")
    win2.cur_t_on.setChecked(True)
    saved = win2.capture_state()
    settings.save_preset("smoke", saved)

    win2.reset_ui()
    assert win2.tb_knob.value() == pytest.approx(1e-3), "reset should restore 1 ms"
    assert win2.strips[0].vdiv.value() == pytest.approx(0.5)
    assert win2.trg_slope.currentText() == "rising"
    assert not win2.cur_t_on.isChecked()
    assert win2.chan_spin.value() == 4, "reset must not touch the capture"
    assert win2.dev_combo.currentText() == "hw:2,0"

    win2.preset_combo.setCurrentText("smoke")
    win2._preset_load()
    assert win2.tb_knob.value() == pytest.approx(2e-4), "preset did not load"
    assert win2.strips[0].vdiv.value() == pytest.approx(0.05)
    assert win2.strips[2].enable.isChecked()
    assert win2.trg_src.currentIndex() == 2
    assert win2.trg_slope.currentText() == "falling"
    assert win2.cur_t_on.isChecked()
    print("preset round-trip ok:", sorted(settings.load_store()["presets"]))

    # Closing stores the session, and the next launch picks it up.
    win2.close()
    restored = resolve_state(parse_args([]))
    assert restored["input"]["device"] == "hw:2,0"
    assert restored["horizontal"]["timebase"] == pytest.approx(2e-4)
    settings.delete_preset("smoke")

    win.grab().save(out)
    win.close()
    QtCore.QCoreApplication.processEvents()
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
