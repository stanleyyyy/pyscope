"""Offscreen UI smoke test: build the window, run the simulator, save a PNG.

    QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py [out.png]

Exercises the whole pipeline (capture thread -> ring -> trigger -> plot ->
measurements -> cursors) without a sound card or a visible display.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyqtgraph.Qt import QtCore, QtWidgets  # noqa: E402

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
    win.tb_combo.setCurrentIndex(win.tb_combo.findText("500 us"))
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
    assert win.pos_slider.value() == 20, "trigger point drag ignored"
    assert win.engine.cfg.position == 0.5 - 0.3

    # --- autoset: it should find the simulated signals on its own ----------
    win.tb_combo.setCurrentIndex(0)                         # 1 us/div, far off
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
        % (cycles, win.tb_combo.currentText()))
    assert win.pos_slider.value() == 50
    print("autoset:", win.status.currentMessage())

    deadline = time.time() + 2.0
    while time.time() < deadline and not (win.frame and win.frame.triggered):
        app.processEvents()
        time.sleep(0.01)
    assert win.frame is not None and win.frame.triggered, "not running after autoset"

    win.grab().save(out)
    win.close()
    QtCore.QCoreApplication.processEvents()
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
