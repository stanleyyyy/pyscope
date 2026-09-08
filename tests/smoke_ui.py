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

    win.grab().save(out)
    win.close()
    QtCore.QCoreApplication.processEvents()
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
