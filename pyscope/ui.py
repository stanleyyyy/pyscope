"""Qt/pyqtgraph oscilloscope front end."""
from __future__ import annotations

import csv
import math

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from . import X_DIVS, Y_DIVS, autoset, sources, trigger
from .autoset import TIMEBASE_STEPS, VDIV_STEPS
from .measure import eng, measure
from .sources import COMMON_RATES, FORMATS, SourceConfig, SourceError, make_source
from .trigger import TriggerConfig, TriggerEngine

AUTOSET_WINDOW = 0.25   # seconds of data autoset inspects
HALF_Y = Y_DIVS / 2.0

CH_COLORS = ["#ffd400", "#00d0ff", "#ff5dd0", "#5dff8f",
             "#ff8c40", "#c0c0ff", "#ff6060", "#40e0d0"]


def qt_enum(owner, scope: str, name: str):
    """Fetch an enum member across Qt bindings.

    Qt6 bindings (PyQt6, PySide6) only expose enums through their scope
    (`Qt.PenStyle.DashLine`); Qt5 bindings expose them unscoped as well, and a
    few members are missing from one form or the other. Try scoped first, then
    fall back, so the app runs on whichever binding pyqtgraph picked.
    """
    holder = getattr(owner, scope, None)
    if holder is not None and hasattr(holder, name):
        return getattr(holder, name)
    return getattr(owner, name)


DASH_LINE = qt_enum(QtCore.Qt, "PenStyle", "DashLine")
DOT_LINE = qt_enum(QtCore.Qt, "PenStyle", "DotLine")
DASH_DOT_LINE = qt_enum(QtCore.Qt, "PenStyle", "DashDotLine")
HORIZONTAL = qt_enum(QtCore.Qt, "Orientation", "Horizontal")
KEY_SPACE = qt_enum(QtCore.Qt, "Key", "Key_Space")
KEY_S = qt_enum(QtCore.Qt, "Key", "Key_S")
KEY_F = qt_enum(QtCore.Qt, "Key", "Key_F")
KEY_A = qt_enum(QtCore.Qt, "Key", "Key_A")
NO_EDIT = qt_enum(QtWidgets.QAbstractItemView, "EditTrigger", "NoEditTriggers")
STRETCH = qt_enum(QtWidgets.QHeaderView, "ResizeMode", "Stretch")


class ChannelStrip(QtWidgets.QGroupBox):
    """Per-channel vertical controls: enable, V/div, position, coupling, invert."""

    changed = QtCore.Signal()

    def __init__(self, index: int, parent=None):
        super().__init__("CH%d" % (index + 1), parent)
        self.index = index
        self.color = CH_COLORS[index % len(CH_COLORS)]
        self.setStyleSheet("QGroupBox::title { color: %s; font-weight: bold; }"
                           % self.color)

        self.enable = QtWidgets.QCheckBox("on")
        self.enable.setChecked(index < 2)

        self.vdiv = QtWidgets.QComboBox()
        for v in VDIV_STEPS:
            self.vdiv.addItem(eng(v, "FS"), v)
        # 0.5 FS/div keeps a full-scale signal inside the 8 visible divisions.
        self.vdiv.setCurrentIndex(VDIV_STEPS.index(0.5))

        self.position = QtWidgets.QDoubleSpinBox()
        self.position.setRange(-HALF_Y, HALF_Y)
        self.position.setSingleStep(0.25)
        self.position.setDecimals(2)
        self.position.setSuffix(" div")
        self.position.setValue(2.0 if index == 0 else -2.0 if index == 1 else 0.0)

        self.coupling = QtWidgets.QComboBox()
        self.coupling.addItems(["DC", "AC"])
        self.invert = QtWidgets.QCheckBox("invert")

        form = QtWidgets.QFormLayout(self)
        form.setContentsMargins(6, 4, 6, 4)
        form.setVerticalSpacing(3)
        form.addRow(self.enable)
        form.addRow("V/div", self.vdiv)
        form.addRow("pos", self.position)
        form.addRow("cpl", self.coupling)
        form.addRow(self.invert)

        for w, sig in ((self.enable, "toggled"), (self.vdiv, "currentIndexChanged"),
                       (self.position, "valueChanged"),
                       (self.coupling, "currentIndexChanged"),
                       (self.invert, "toggled")):
            # Swallow each widget's own argument: `changed` carries none.
            getattr(w, sig).connect(lambda *_: self.changed.emit())

    @property
    def scale(self) -> float:
        return float(self.vdiv.currentData())

    @property
    def on(self) -> bool:
        return self.enable.isChecked()

    def apply(self, y: np.ndarray) -> np.ndarray:
        """Coupling and inversion, in signal units (not screen divisions)."""
        if self.coupling.currentText() == "AC":
            y = y - float(np.mean(y))
        if self.invert.isChecked():
            y = -y
        return y


class ScopeWindow(QtWidgets.QMainWindow):
    def __init__(self, cfg: SourceConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("pyscope - ALSA oscilloscope")
        self.resize(1360, 820)

        self.cfg = cfg
        self.source: sources.BaseSource | None = None
        self.engine = TriggerEngine(TriggerConfig())
        self.frame: trigger.Frame | None = None
        self.running = False
        self._autoset_pending = False
        self._starved: tuple | None = None

        self.strips: list[ChannelStrip] = []
        self.curves: list[pg.PlotDataItem] = []

        self._build_plot()
        self._build_controls()
        self._build_status()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(25)

        self._rebuild_channels()
        self._refresh_devices()
        self._apply_config(start=cfg.simulate)

    # ------------------------------------------------------------------ plot
    def _build_plot(self) -> None:
        pg.setConfigOptions(antialias=False, background="#101418", foreground="#c8c8c8")
        self.plot = pg.PlotWidget()
        self.pi = self.plot.getPlotItem()
        self.pi.setMenuEnabled(False)
        self.pi.hideButtons()
        self.pi.setMouseEnabled(False, False)
        self.pi.showGrid(x=True, y=True, alpha=0.35)
        # Ticks are written out explicitly below, so pyqtgraph must not also
        # apply an SI prefix to the label - that made it read "ms" over values
        # that were plain seconds.
        self.pi.getAxis("bottom").enableAutoSIPrefix(False)
        self.pi.setLabel("bottom", "time (s)")
        self.pi.setLabel("left", "divisions")
        self.pi.setYRange(-HALF_Y, HALF_Y, padding=0)
        self.pi.setDownsampling(auto=True, mode="peak")
        self.pi.setClipToView(True)

        # Both trigger handles are mouse-draggable: the horizontal line sets
        # the level, the vertical one slides the trigger point along the record.
        trig_pen = pg.mkPen("#ff4040", width=1, style=DASH_LINE)
        hover_pen = pg.mkPen("#ff9090", width=2, style=DASH_LINE)
        label_opts = {"color": "#ff8080", "movable": False,
                      "fill": (16, 20, 24, 200)}
        self.trig_line = pg.InfiniteLine(angle=0, movable=True, pen=trig_pen,
                                         hoverPen=hover_pen, label="TRIG",
                                         labelOpts=dict(label_opts, position=0.03))
        self.trig_line.sigDragged.connect(self._trig_line_moved)
        self.pi.addItem(self.trig_line)

        self.trig_marker = pg.InfiniteLine(
            angle=90, movable=True, pen=pg.mkPen("#ff4040", width=1,
                                                 style=DOT_LINE),
            hoverPen=hover_pen, label="T",
            labelOpts=dict(label_opts, position=0.97))
        self.trig_marker.setPos(0.0)
        self.trig_marker.sigDragged.connect(self._trig_marker_moved)
        self.pi.addItem(self.trig_marker)

        cur_pen = pg.mkPen("#ffffff", width=1, style=DASH_DOT_LINE)
        self.cur_t = [pg.InfiniteLine(angle=90, movable=True, pen=cur_pen)
                      for _ in range(2)]
        self.cur_y = [pg.InfiniteLine(angle=0, movable=True, pen=cur_pen)
                      for _ in range(2)]
        for line in self.cur_t + self.cur_y:
            line.setVisible(False)
            line.sigPositionChanged.connect(self._update_cursor_readout)
            self.pi.addItem(line)

    # -------------------------------------------------------------- controls
    def _build_controls(self) -> None:
        panel = QtWidgets.QWidget()
        vbox = QtWidgets.QVBoxLayout(panel)
        vbox.setContentsMargins(6, 6, 6, 6)
        vbox.addWidget(self._input_group())
        vbox.addWidget(self._horizontal_group())
        vbox.addWidget(self._trigger_group())
        vbox.addWidget(self._cursor_group())
        vbox.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(320)

        self.ch_box = QtWidgets.QWidget()
        self.ch_layout = QtWidgets.QHBoxLayout(self.ch_box)
        self.ch_layout.setContentsMargins(4, 0, 4, 0)
        self.ch_layout.addStretch(1)
        ch_scroll = QtWidgets.QScrollArea()
        ch_scroll.setWidget(self.ch_box)
        ch_scroll.setWidgetResizable(True)
        ch_scroll.setFixedHeight(190)

        self.table = QtWidgets.QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["Ch", "Vpp", "Vmax", "Vmin", "Mean", "RMS", "Freq", "Period",
             "Duty", "Rise"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(NO_EDIT)
        self.table.horizontalHeader().setSectionResizeMode(
            STRETCH)
        self.table.setFixedHeight(150)

        right = QtWidgets.QWidget()
        rl = QtWidgets.QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.plot, 1)
        self.cursor_label = QtWidgets.QLabel("")
        self.cursor_label.setStyleSheet("color:#dddddd; padding:2px;")
        rl.addWidget(self.cursor_label)
        rl.addWidget(ch_scroll)
        rl.addWidget(self.table)

        central = QtWidgets.QWidget()
        cl = QtWidgets.QHBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(scroll)
        cl.addWidget(right, 1)
        self.setCentralWidget(central)

    def _input_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Input (ALSA)")
        f = QtWidgets.QFormLayout(g)

        self.dev_combo = QtWidgets.QComboBox()
        self.dev_combo.setEditable(True)
        dev_row = QtWidgets.QHBoxLayout()
        dev_row.addWidget(self.dev_combo, 1)
        rescan = QtWidgets.QPushButton("scan")
        rescan.setFixedWidth(48)
        rescan.clicked.connect(self._refresh_devices)
        dev_row.addWidget(rescan)
        f.addRow("device", self._wrap(dev_row))

        self.rate_combo = QtWidgets.QComboBox()
        self.rate_combo.setEditable(True)
        for r in COMMON_RATES:
            self.rate_combo.addItem(str(r), r)
        self.rate_combo.setCurrentText(str(self.cfg.rate))
        f.addRow("rate (Hz)", self.rate_combo)

        self.chan_spin = QtWidgets.QSpinBox()
        self.chan_spin.setRange(1, 32)
        self.chan_spin.setValue(self.cfg.channels)
        f.addRow("channels", self.chan_spin)

        self.fmt_combo = QtWidgets.QComboBox()
        self.fmt_combo.addItems(list(FORMATS))
        self.fmt_combo.setCurrentText(self.cfg.fmt)
        f.addRow("format", self.fmt_combo)

        self.period_combo = QtWidgets.QComboBox()
        for p in (64, 128, 256, 512, 1024, 2048, 4096, 8192):
            self.period_combo.addItem(str(p), p)
        self.period_combo.setCurrentText(str(self.cfg.period))
        f.addRow("period", self.period_combo)

        self.buf_spin = QtWidgets.QDoubleSpinBox()
        self.buf_spin.setRange(0.1, 30.0)
        self.buf_spin.setValue(self.cfg.buffer_seconds)
        self.buf_spin.setSuffix(" s")
        f.addRow("ring buffer", self.buf_spin)

        self.sim_check = QtWidgets.QCheckBox("simulator (no hardware)")
        self.sim_check.setChecked(self.cfg.simulate)
        f.addRow(self.sim_check)

        apply_btn = QtWidgets.QPushButton("Apply / restart capture")
        apply_btn.clicked.connect(lambda: self._apply_config(start=True))
        f.addRow(apply_btn)
        return g

    def _horizontal_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Horizontal / acquisition")
        f = QtWidgets.QFormLayout(g)

        self.tb_combo = QtWidgets.QComboBox()
        for v in TIMEBASE_STEPS:
            self.tb_combo.addItem(eng(v, "s"), v)
        self.tb_combo.setCurrentIndex(TIMEBASE_STEPS.index(0.001))
        self.tb_combo.currentIndexChanged.connect(self._redraw)
        f.addRow("time/div", self.tb_combo)

        self.pos_slider = QtWidgets.QSlider(HORIZONTAL)
        self.pos_slider.setRange(0, 100)
        self.pos_slider.setValue(50)
        self.pos_slider.valueChanged.connect(self._pos_changed)
        self.pos_label = QtWidgets.QLabel("trigger at 50%")
        f.addRow(self.pos_label, self.pos_slider)

        row = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Run")
        self.run_btn.setCheckable(True)
        self.run_btn.clicked.connect(self._toggle_run)
        self.single_btn = QtWidgets.QPushButton("Single")
        self.single_btn.clicked.connect(self._single)
        self.auto_btn = QtWidgets.QPushButton("Autoset")
        self.auto_btn.setToolTip("Find the signal and set gain, timebase and "
                                 "trigger automatically (A)")
        self.auto_btn.clicked.connect(self.autoset)
        for b in (self.run_btn, self.single_btn, self.auto_btn):
            row.addWidget(b)
        f.addRow(self._wrap(row))

        row2 = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Export CSV")
        self.save_btn.clicked.connect(self._export_csv)
        row2.addWidget(self.save_btn)
        f.addRow(self._wrap(row2))
        return g

    def _trigger_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Trigger")
        f = QtWidgets.QFormLayout(g)

        self.trg_mode = QtWidgets.QComboBox()
        self.trg_mode.addItems([trigger.AUTO, trigger.NORMAL, trigger.SINGLE])
        self.trg_mode.currentTextChanged.connect(self._trigger_changed)
        f.addRow("mode", self.trg_mode)

        self.trg_src = QtWidgets.QComboBox()
        self.trg_src.currentIndexChanged.connect(self._trigger_changed)
        f.addRow("source", self.trg_src)

        self.trg_slope = QtWidgets.QComboBox()
        self.trg_slope.addItems([trigger.RISING, trigger.FALLING, trigger.EITHER])
        self.trg_slope.currentTextChanged.connect(self._trigger_changed)
        f.addRow("slope", self.trg_slope)

        self.trg_level = QtWidgets.QDoubleSpinBox()
        self.trg_level.setRange(-1.0, 1.0)
        self.trg_level.setDecimals(4)
        self.trg_level.setSingleStep(0.005)
        self.trg_level.valueChanged.connect(self._trigger_changed)
        f.addRow("level (FS)", self.trg_level)

        self.trg_hyst = QtWidgets.QDoubleSpinBox()
        self.trg_hyst.setRange(0.0, 0.5)
        self.trg_hyst.setDecimals(4)
        self.trg_hyst.setSingleStep(0.002)
        self.trg_hyst.setValue(0.01)
        self.trg_hyst.valueChanged.connect(self._trigger_changed)
        f.addRow("hysteresis", self.trg_hyst)

        self.trg_hold = QtWidgets.QDoubleSpinBox()
        self.trg_hold.setRange(0.0, 1000.0)
        self.trg_hold.setDecimals(2)
        self.trg_hold.setSuffix(" ms")
        self.trg_hold.valueChanged.connect(self._trigger_changed)
        f.addRow("hold-off", self.trg_hold)

        row = QtWidgets.QHBoxLayout()
        half = QtWidgets.QPushButton("Level to 50%")
        half.setToolTip("Put the level at the midpoint of the source channel")
        half.clicked.connect(self.level_to_50)
        force = QtWidgets.QPushButton("Force trigger")
        force.clicked.connect(self._force)
        row.addWidget(half)
        row.addWidget(force)
        f.addRow(self._wrap(row))
        return g

    def _cursor_group(self) -> QtWidgets.QGroupBox:
        g = QtWidgets.QGroupBox("Cursors / markers")
        f = QtWidgets.QFormLayout(g)
        self.cur_t_on = QtWidgets.QCheckBox("time cursors (T1/T2)")
        self.cur_y_on = QtWidgets.QCheckBox("level cursors (Y1/Y2)")
        self.cur_t_on.toggled.connect(self._cursors_toggled)
        self.cur_y_on.toggled.connect(self._cursors_toggled)
        self.cur_ch = QtWidgets.QComboBox()
        self.cur_ch.currentIndexChanged.connect(self._update_cursor_readout)
        f.addRow(self.cur_t_on)
        f.addRow(self.cur_y_on)
        f.addRow("Y ref channel", self.cur_ch)
        return g

    def _build_status(self) -> None:
        self.status = self.statusBar()
        self.status_label = QtWidgets.QLabel("idle")
        self.status.addPermanentWidget(self.status_label)

    @staticmethod
    def _wrap(layout) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    # ------------------------------------------------------------- lifecycle
    def _refresh_devices(self) -> None:
        current = self.dev_combo.currentText()
        self.dev_combo.clear()
        devs = sources.list_alsa_devices()
        if not devs:
            devs = ["default"]
        self.dev_combo.addItems(devs)
        if current:
            self.dev_combo.setCurrentText(current)
        if sources.alsaaudio is None:
            self.sim_check.setChecked(True)
            self.status.showMessage(
                "pyalsaaudio not available - using the simulator", 8000)

    def _collect_config(self) -> SourceConfig:
        try:
            rate = int(float(self.rate_combo.currentText()))
        except ValueError:
            rate = 48000
        return SourceConfig(
            device=self.dev_combo.currentText().strip() or "default",
            rate=max(1000, rate),
            channels=self.chan_spin.value(),
            fmt=self.fmt_combo.currentText(),
            period=int(self.period_combo.currentData() or 1024),
            buffer_seconds=self.buf_spin.value(),
            simulate=self.sim_check.isChecked(),
            sim_specs=list(self.cfg.sim_specs),
        )

    def _apply_config(self, start: bool = True) -> None:
        self._stop_source()
        self.cfg = self._collect_config()
        self._rebuild_channels()
        if not start:
            return
        try:
            self.source = make_source(self.cfg)
            self.source.start()
        except SourceError as exc:
            self.source = None
            QtWidgets.QMessageBox.warning(self, "Capture error", str(exc))
            self.status.showMessage(str(exc), 10000)
            return
        except Exception as exc:  # pragma: no cover - driver specific
            self.source = None
            QtWidgets.QMessageBox.warning(self, "Capture error", repr(exc))
            return
        # The driver may have adjusted rate/channels; mirror that back to the UI.
        self.rate_combo.setCurrentText(str(self.cfg.rate))
        self.chan_spin.setValue(self.cfg.channels)
        self.engine.reset()
        self.running = True
        self.run_btn.setChecked(True)
        self.run_btn.setText("Stop")

    def _stop_source(self) -> None:
        self.running = False
        if self.source is not None:
            self.source.stop()
            self.source = None

    def closeEvent(self, event):  # noqa: N802 (Qt naming)
        self._stop_source()
        super().closeEvent(event)

    def _rebuild_channels(self) -> None:
        for strip in self.strips:
            strip.setParent(None)
        self.strips.clear()
        for curve in self.curves:
            self.pi.removeItem(curve)
        self.curves.clear()

        for ch in range(self.cfg.channels):
            strip = ChannelStrip(ch)
            strip.changed.connect(self._redraw)
            self.ch_layout.insertWidget(self.ch_layout.count() - 1, strip)
            self.strips.append(strip)
            self.curves.append(self.pi.plot(pen=pg.mkPen(strip.color, width=1)))

        names = ["CH%d" % (c + 1) for c in range(self.cfg.channels)]
        for combo in (self.trg_src, self.cur_ch):
            keep = combo.currentIndex()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            combo.setCurrentIndex(min(max(keep, 0), len(names) - 1))
            combo.blockSignals(False)
        self._trigger_changed()

    # --------------------------------------------------------------- control
    def _toggle_run(self, checked: bool) -> None:
        if checked:
            if self.source is None:
                self._apply_config(start=True)
            else:
                self.running = True
                self.engine.reset()
                self.run_btn.setText("Stop")
        else:
            self.running = False
            self.run_btn.setText("Run")

    def _single(self) -> None:
        self.trg_mode.setCurrentText(trigger.SINGLE)
        self.engine.reset()
        if self.source is None:
            self._apply_config(start=True)
        self.running = True
        self.run_btn.setChecked(True)
        self.run_btn.setText("Stop")

    def level_to_50(self) -> None:
        """Drop the trigger level onto the midpoint of the source channel."""
        src = self.source
        if src is None:
            return
        n = min(src.ring.available, int(self.cfg.rate * AUTOSET_WINDOW))
        if n < 2:
            return
        block, _ = src.ring.snapshot(n)
        ch = min(self.engine.cfg.source, block.shape[1] - 1)
        x = block[:, ch]
        lo, hi = float(x.min()), float(x.max())
        self.trg_level.setValue(min(max(0.5 * (lo + hi), -1.0), 1.0))
        self.trg_hyst.setValue(min(max(0.05 * (hi - lo), 1e-4), 0.5))
        self.engine.reset()
        self.status.showMessage("level set to CH%d midpoint (%s of %s..%s)"
                                % (ch + 1, eng(0.5 * (lo + hi), "FS"),
                                   eng(lo, "FS"), eng(hi, "FS")), 6000)

    def _force(self) -> None:
        """Show whatever is in the buffer right now, without waiting for an edge."""
        if self.source is None:
            return
        rate = self.cfg.rate
        n = self._record_len(rate)
        block, _ = self.source.ring.snapshot(n)
        if block.shape[0] < n:
            return
        pre = int(round(self.engine.cfg.position * (n - 1)))
        self.frame = TriggerEngine._frame(block, pre, pre, n, rate, False)
        self._redraw()

    # ----------------------------------------------------------- autoset
    def autoset(self) -> None:
        """Find the signal and configure gain, timebase and trigger for it."""
        if self.source is None:
            self._apply_config(start=True)
            if self.source is None:
                return
        self.running = True
        self.run_btn.setChecked(True)
        self.run_btn.setText("Stop")
        self.engine.reset()
        if not self._try_autoset():
            # Capture has only just started; retry from _tick once the ring
            # holds a long enough window to measure low frequencies.
            self._autoset_pending = True
            self.status.showMessage("autoset: filling the buffer...", 3000)

    def _try_autoset(self) -> bool:
        src = self.source
        if src is None:
            return False
        need = min(src.ring.capacity, int(self.cfg.rate * AUTOSET_WINDOW))
        if src.ring.available < need:
            return False
        block, _ = src.ring.snapshot(need)
        self._apply_plan(autoset.plan(block, self.cfg.rate))
        self._autoset_pending = False
        self._starved: tuple | None = None
        return True

    def _apply_plan(self, p: autoset.AutosetPlan) -> None:
        if not p.found:
            self.status.showMessage(
                "autoset: no signal found (every channel below %s Vpp)"
                % eng(autoset.SILENCE, "FS"), 6000)
            return
        widgets = [self.trg_mode, self.trg_src, self.trg_slope, self.trg_level,
                   self.trg_hyst, self.tb_combo, self.pos_slider]
        for w in widgets + self.strips:
            w.blockSignals(True)
        try:
            for cp, strip in zip(p.channels, self.strips):
                strip.enable.setChecked(cp.active)
                strip.vdiv.setCurrentIndex(VDIV_STEPS.index(cp.vdiv))
                strip.position.setValue(round(cp.position * 4) / 4)
            self.tb_combo.setCurrentIndex(TIMEBASE_STEPS.index(p.timebase))
            self.pos_slider.setValue(50)
            self.trg_mode.setCurrentText(trigger.AUTO)
            self.trg_src.setCurrentIndex(p.source)
            self.trg_slope.setCurrentText(trigger.RISING)
            self.trg_level.setValue(p.level)
            self.trg_hyst.setValue(p.hysteresis)
        finally:
            for w in widgets + self.strips:
                w.blockSignals(False)
        self.engine.cfg.position = 0.5
        self.pos_label.setText("trigger at 50%")
        self._trigger_changed()
        self.engine.reset()
        self._redraw()
        active = [c.index + 1 for c in p.channels if c.active]
        self.status.showMessage(
            "autoset: CH%s, trigger CH%d at %s, %s/div, %s"
            % ("+".join(str(a) for a in active), p.source + 1,
               eng(p.level, "FS"), eng(p.timebase, "s"),
               eng(p.channels[p.source].freq, "Hz")), 8000)

    def _pos_changed(self, value: int) -> None:
        self.pos_label.setText("trigger at %d%%" % value)
        self.engine.cfg.position = value / 100.0
        self._redraw()

    def _trigger_changed(self, *_args) -> None:
        cfg = self.engine.cfg
        cfg.mode = self.trg_mode.currentText()
        cfg.source = max(0, self.trg_src.currentIndex())
        cfg.slope = self.trg_slope.currentText()
        cfg.level = self.trg_level.value()
        cfg.hysteresis = self.trg_hyst.value()
        cfg.holdoff = self.trg_hold.value() / 1000.0
        if cfg.mode == trigger.SINGLE:
            self.engine.armed_single = True
        self._update_trigger_line()

    def _update_trigger_line(self) -> None:
        cfg = self.engine.cfg
        if not self.strips:
            return
        strip = self.strips[min(cfg.source, len(self.strips) - 1)]
        self.trig_line.blockSignals(True)
        self.trig_line.setPos(cfg.level / strip.scale + strip.position.value())
        self.trig_line.blockSignals(False)
        # Wear the source channel's colour: the line is drawn in that
        # channel's gain and position, so on a multi-channel screen it can
        # otherwise appear to sit on a trace it has nothing to do with.
        self.trig_line.setPen(pg.mkPen(strip.color, width=1, style=DASH_LINE))
        self.trig_line.setHoverPen(pg.mkPen(strip.color, width=2,
                                            style=DASH_LINE))
        self.trig_line.label.setColor(strip.color)
        self.trig_line.label.setFormat("TRIG CH%d %s %s"
                                       % (cfg.source + 1,
                                          "/" if cfg.slope == trigger.RISING
                                          else "\\" if cfg.slope == trigger.FALLING
                                          else "X", eng(cfg.level, "FS")))
        if not self.trig_marker.moving:
            self.trig_marker.blockSignals(True)
            self.trig_marker.setPos(0.0)
            self.trig_marker.blockSignals(False)

    def _trig_line_moved(self) -> None:
        """Dragging the red line sets the trigger level, live."""
        cfg = self.engine.cfg
        if not self.strips:
            return
        strip = self.strips[min(cfg.source, len(self.strips) - 1)]
        level = (self.trig_line.value() - strip.position.value()) * strip.scale
        self.trg_level.setValue(min(max(level, -1.0), 1.0))

    def _trig_marker_moved(self) -> None:
        """Dragging the T marker slides the trigger point along the record.

        The trigger always sits at t = 0, so moving the marker really changes
        how much of the record is pre-trigger; the slider is the source of
        truth and the marker snaps back to 0 on the next redraw.
        """
        lo, hi = self._time_span()
        if hi <= lo:
            return
        frac = (self.trig_marker.value() - lo) / (hi - lo)
        self.pos_slider.setValue(int(round(min(max(frac, 0.0), 1.0) * 100)))

    def _cursors_toggled(self) -> None:
        span = self._time_span()
        for i, line in enumerate(self.cur_t):
            line.setVisible(self.cur_t_on.isChecked())
            if self.cur_t_on.isChecked():
                line.setPos(span[0] + (0.3 + 0.4 * i) * (span[1] - span[0]))
        for i, line in enumerate(self.cur_y):
            line.setVisible(self.cur_y_on.isChecked())
            if self.cur_y_on.isChecked():
                line.setPos(-1.5 + 3.0 * i)
        self._update_cursor_readout()

    def _update_cursor_readout(self, *_args) -> None:
        parts: list[str] = []
        if self.cur_t_on.isChecked():
            t1, t2 = self.cur_t[0].value(), self.cur_t[1].value()
            dt = t2 - t1
            freq = 1.0 / dt if dt else float("nan")
            parts.append("T1 %s  T2 %s  dT %s  1/dT %s"
                         % (eng(t1, "s"), eng(t2, "s"), eng(dt, "s"),
                            eng(freq, "Hz")))
        if self.cur_y_on.isChecked() and self.strips:
            idx = min(max(self.cur_ch.currentIndex(), 0), len(self.strips) - 1)
            strip = self.strips[idx]
            y1 = (self.cur_y[0].value() - strip.position.value()) * strip.scale
            y2 = (self.cur_y[1].value() - strip.position.value()) * strip.scale
            parts.append("Y1 %s  Y2 %s  dY %s  (CH%d)"
                         % (eng(y1, "FS"), eng(y2, "FS"), eng(y2 - y1, "FS"),
                            idx + 1))
        self.cursor_label.setText("     ".join(parts))

    # ------------------------------------------------------------ acquisition
    def _timebase(self) -> float:
        return float(self.tb_combo.currentData())

    def _record_len(self, rate: int) -> int:
        n = int(round(self._timebase() * X_DIVS * rate))
        cap = max(4, self.source.ring.capacity // 2) if self.source else 1 << 20
        return max(2, min(n, cap))

    def _time_span(self) -> tuple[float, float]:
        total = self._timebase() * X_DIVS
        pre = self.engine.cfg.position * total
        return -pre, total - pre

    def _tick(self) -> None:
        src = self.source
        if src is None:
            return
        if src.error:
            self.status_label.setText("capture error: %s" % src.error)
            self._stop_source()
            return
        if self._autoset_pending:
            self._try_autoset()
        if self.running:
            rate = self.cfg.rate
            record = self._record_len(rate)
            want = min(src.ring.available, max(record * 3, record + rate // 10))
            block, start_global = src.ring.snapshot(want)
            frame = self.engine.acquire(block, start_global, rate, record)
            if frame is None and self.engine.cfg.mode != trigger.AUTO:
                # Record why nothing fired, so a level parked off the signal
                # is visible instead of just looking like a frozen screen.
                ch = min(self.engine.cfg.source, block.shape[1] - 1)
                x = block[:, ch] if block.shape[0] else None
                self._starved = ((ch, float(x.min()), float(x.max()))
                                 if x is not None and x.size else None)
            else:
                self._starved = None
            if frame is not None:
                self.frame = frame
                if (self.engine.cfg.mode == trigger.SINGLE and frame.triggered):
                    self.running = False
                    self.run_btn.setChecked(False)
                    self.run_btn.setText("Run")
                self._redraw()
        self._update_status()

    def _update_status(self) -> None:
        src = self.source
        if src is None:
            self.status_label.setText("stopped")
            return
        if self._starved is not None:
            ch, lo, hi = self._starved
            level = self.engine.cfg.level
            why = ("" if lo <= level <= hi
                   else " - level %s is outside that range" % eng(level, "FS"))
            trg = "NO TRIG (CH%d spans %s..%s%s)" % (ch + 1, eng(lo, "FS"),
                                                     eng(hi, "FS"), why)
        elif self.frame and self.frame.triggered:
            trg = "TRIG"
        else:
            trg = "auto"
        self.status_label.setText(
            "%s | %d Hz | %d ch | %s | blocks %d | overruns %d | %s"
            % ("SIM" if self.cfg.simulate else self.cfg.device, self.cfg.rate,
               self.cfg.channels, self.cfg.fmt, src.blocks, src.overruns,
               trg if self.running else "STOPPED"))

    # ----------------------------------------------------------------- draw
    def _redraw(self) -> None:
        self._update_trigger_line()
        lo, hi = self._time_span()
        self.pi.setXRange(lo, hi, padding=0)
        self.pi.setYRange(-HALF_Y, HALF_Y, padding=0)
        self._set_ticks(lo, hi)

        frame = self.frame
        if frame is None:
            return
        for ch, (strip, curve) in enumerate(zip(self.strips, self.curves)):
            if ch >= frame.data.shape[1] or not strip.on:
                curve.setData([], [])
                continue
            y = strip.apply(frame.data[:, ch].astype(np.float64))
            curve.setData(frame.t, y / strip.scale + strip.position.value())
        self._update_measurements(frame)
        self._update_cursor_readout()

    def _set_ticks(self, lo: float, hi: float) -> None:
        step = self._timebase()
        xticks = [(lo + i * step, "") for i in range(X_DIVS + 1)]
        self.pi.getAxis("bottom").setTicks(
            [[(v, "%.3g" % v) for v, _ in xticks], []])
        self.pi.getAxis("left").setTicks(
            [[(d, str(d)) for d in range(-int(HALF_Y), int(HALF_Y) + 1)], []])

    def _update_measurements(self, frame: trigger.Frame) -> None:
        rows = [ch for ch, s in enumerate(self.strips)
                if s.on and ch < frame.data.shape[1]]
        self.table.setRowCount(len(rows))
        for r, ch in enumerate(rows):
            strip = self.strips[ch]
            m = measure(strip.apply(frame.data[:, ch].astype(np.float64)),
                        frame.rate)
            cells = [
                "CH%d" % (ch + 1),
                eng(m["vpp"], "FS"), eng(m["vmax"], "FS"), eng(m["vmin"], "FS"),
                eng(m["mean"], "FS"), eng(m["rms"], "FS"),
                eng(m["freq"], "Hz"), eng(m["period"], "s"),
                "--" if not np.isfinite(m["duty"]) else "%.1f %%" % m["duty"],
                eng(m["rise"], "s"),
            ]
            for c, text in enumerate(cells):
                item = QtWidgets.QTableWidgetItem(text)
                if c == 0:
                    item.setForeground(QtGui.QColor(strip.color))
                self.table.setItem(r, c, item)

    def _export_csv(self) -> None:
        if self.frame is None:
            self.status.showMessage("nothing captured yet", 4000)
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export current record", "capture.csv", "CSV (*.csv)")
        if not path:
            return
        frame = self.frame
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["time_s"] + ["ch%d" % (c + 1)
                                     for c in range(frame.data.shape[1])])
            for i, t in enumerate(frame.t):
                w.writerow(["%.9g" % t] + ["%.6g" % v for v in frame.data[i]])
        self.status.showMessage("wrote %s" % path, 5000)

    # ------------------------------------------------------------- shortcuts
    def keyPressEvent(self, event):  # noqa: N802 (Qt naming)
        key = event.key()
        if key == KEY_SPACE:
            self.run_btn.toggle()
            self._toggle_run(self.run_btn.isChecked())
        elif key == KEY_S:
            self._single()
        elif key == KEY_F:
            self._force()
        elif key == KEY_A:
            self.autoset()
        else:
            super().keyPressEvent(event)
