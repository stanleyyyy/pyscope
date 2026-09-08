"""Rotary knobs, the control a scope's front panel actually uses.

Drag up/down (or scroll) to turn, shift for fine steps on continuous knobs,
double-click to return to the default, arrow keys when focused.
"""
from __future__ import annotations

import math

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .measure import parse_eng
from .qtcompat import (ALIGN_CENTER, ANTIALIASING, FLAT_CAP, LEFT_BUTTON,
                       ELIDE_RIGHT, ROUND_CAP, SHIFT_MODIFIER, SIZE_VER_CURSOR,
                       SOLID_LINE, STRONG_FOCUS, WINDOW_TEXT, KEY_DOWN,
                       KEY_LEFT, KEY_RIGHT, KEY_UP, event_pos)

SWEEP = 270.0        # degrees of travel, 7 o'clock round to 5 o'clock
START = 225.0        # pointer angle at minimum, measured like Qt (0 = 3 o'clock)
TITLE_H = 14         # caption band, kept clear of the arc below it
PIXELS_PER_TURN = 200.0   # drag distance covering a continuous knob's range


class Knob(QtWidgets.QWidget):
    """Base knob: subclasses map between a value and a 0..1 position."""

    valueChanged = QtCore.Signal(object)

    def __init__(self, title: str = "", color: str = "#7fd0ff",
                 diameter: int = 46, editable: bool = True, parent=None):
        super().__init__(parent)
        self.title = title
        self.color = color
        self.diameter = diameter
        self._drag_y: float | None = None
        self._drag_frac = 0.0
        self.setFocusPolicy(STRONG_FOCUS)
        self.setCursor(SIZE_VER_CURSOR)
        self.setFixedSize(diameter + 30, diameter + TITLE_H + 30)

        # The dial gives you the gesture; the field gives you the exact number
        # and lets you type one in ("500 us", "20 mFS", "-0.0005").
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setAlignment(ALIGN_CENTER)
        self.edit.setFrame(False)
        self.edit.setFixedHeight(17)
        self.edit.setStyleSheet(
            "QLineEdit { background:#1b2229; color:#e8edf2; border:1px solid "
            "#39424b; border-radius:3px; padding:0px; }"
            "QLineEdit:focus { border:1px solid %s; }" % color)
        f = self.edit.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 0.5))
        self.edit.setFont(f)
        self.edit.editingFinished.connect(self._edit_committed)
        self.edit.setVisible(editable)
        self.sync_text()

    # -- subclass interface ------------------------------------------------
    def value(self):
        raise NotImplementedError

    def setValue(self, value, notify: bool = True) -> None:
        raise NotImplementedError

    def _frac(self) -> float:
        raise NotImplementedError

    def _set_frac(self, frac: float) -> None:
        raise NotImplementedError

    def _nudge(self, steps: int, fine: bool = False) -> None:
        raise NotImplementedError

    def text(self) -> str:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError

    # -- value field -------------------------------------------------------
    def resizeEvent(self, event):  # noqa: N802
        self.edit.setGeometry(2, self.height() - 18, self.width() - 4, 17)
        super().resizeEvent(event)

    def sync_text(self) -> None:
        """Refresh the field unless the user is part-way through typing."""
        if not self.edit.hasFocus():
            self.edit.setText(self.text())

    def _edit_committed(self) -> None:
        value = parse_eng(self.edit.text())
        if value is None:
            self.sync_text()          # unparseable: put the real value back
            return
        self.setValue(value)
        self.sync_text()

    # -- painting ----------------------------------------------------------
    def paintEvent(self, _event):  # noqa: N802 (Qt naming)
        p = QtGui.QPainter(self)
        p.setRenderHint(ANTIALIASING, True)
        w = self.width()
        d = self.diameter
        # The arc sits 5 px outside the body, so the body starts a clear 5 px
        # below the caption band instead of the arc running through the text.
        cx, cy = w / 2.0, TITLE_H + 5 + d / 2.0
        rect = QtCore.QRectF(cx - d / 2.0, cy - d / 2.0, d, d)
        frac = min(max(self._frac(), 0.0), 1.0)

        if self.title:
            # Palette colour: a hard-coded light grey disappeared on a light
            # desktop theme.
            p.setPen(self.palette().color(WINDOW_TEXT))
            f = p.font()
            f.setPointSizeF(max(7.5, f.pointSizeF() - 0.5))
            p.setFont(f)
            title = QtGui.QFontMetrics(f).elidedText(self.title, ELIDE_RIGHT, w)
            p.drawText(QtCore.QRectF(0, 0, w, TITLE_H), ALIGN_CENTER, title)

        # Track, then the travelled arc in the knob's accent colour.
        track = QtCore.QRectF(rect.adjusted(-5, -5, 5, 5))
        p.setPen(QtGui.QPen(QtGui.QColor("#39424b"), 3, SOLID_LINE, FLAT_CAP))
        p.drawArc(track, int(START * 16), int(-SWEEP * 16))
        p.setPen(QtGui.QPen(QtGui.QColor(self.color), 3, SOLID_LINE, FLAT_CAP))
        p.drawArc(track, int(START * 16), int(-SWEEP * frac * 16))

        # Body and pointer.
        p.setPen(QtGui.QPen(QtGui.QColor("#5a646e"), 1))
        p.setBrush(QtGui.QBrush(QtGui.QColor("#242c34")))
        p.drawEllipse(rect)
        angle = math.radians(START - SWEEP * frac)
        r0, r1 = d * 0.16, d * 0.44
        p.setPen(QtGui.QPen(QtGui.QColor(self.color), 2.5, SOLID_LINE, ROUND_CAP))
        p.drawLine(QtCore.QPointF(cx + r0 * math.cos(angle),
                                  cy - r0 * math.sin(angle)),
                   QtCore.QPointF(cx + r1 * math.cos(angle),
                                  cy - r1 * math.sin(angle)))
        if self.hasFocus():
            p.setPen(QtGui.QPen(QtGui.QColor(self.color), 1))
            p.setBrush(QtGui.QBrush())
            p.drawEllipse(rect.adjusted(-7, -7, 7, 7))

        p.end()

    # -- interaction -------------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == LEFT_BUTTON:
            self._drag_y = event_pos(event)[1]
            self._drag_frac = self._frac()
            self.setFocus()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_y is None:
            return
        dy = self._drag_y - event_pos(event)[1]
        fine = bool(event.modifiers() & SHIFT_MODIFIER)
        self._drag_apply(dy / (PIXELS_PER_TURN * (5.0 if fine else 1.0)))

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_y = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.reset()

    def wheelEvent(self, event):  # noqa: N802
        steps = int(event.angleDelta().y() / 120) or (
            1 if event.angleDelta().y() > 0 else -1)
        self._nudge(steps, bool(event.modifiers() & SHIFT_MODIFIER))
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        fine = bool(event.modifiers() & SHIFT_MODIFIER)
        if key in (KEY_UP, KEY_RIGHT):
            self._nudge(1, fine)
        elif key in (KEY_DOWN, KEY_LEFT):
            self._nudge(-1, fine)
        else:
            super().keyPressEvent(event)

    def _drag_apply(self, dfrac: float) -> None:
        self._set_frac(min(max(self._drag_frac + dfrac, 0.0), 1.0))


class StepKnob(Knob):
    """Knob over a fixed list of values, e.g. the 1-2-5 V/div sequence."""

    def __init__(self, values, fmt=str, title: str = "", color: str = "#7fd0ff",
                 default=None, **kwargs):
        self.values = list(values)
        self.fmt = fmt
        self._index = (self.values.index(default) if default in self.values
                       else len(self.values) // 2)
        self._default_index = self._index
        super().__init__(title=title, color=color, **kwargs)

    def value(self):
        return self.values[self._index]

    def index(self) -> int:
        return self._index

    def setValue(self, value, notify: bool = True) -> None:
        # Nearest listed value, so a computed suggestion can be handed straight in.
        idx = min(range(len(self.values)),
                  key=lambda i: abs(self.values[i] - value))
        self.setIndex(idx, notify)

    def setIndex(self, index: int, notify: bool = True) -> None:
        index = min(max(int(index), 0), len(self.values) - 1)
        if index == self._index:
            self.sync_text()
            return
        self._index = index
        self.update()
        self.sync_text()
        if notify:
            self.valueChanged.emit(self.value())

    def text(self) -> str:
        return self.fmt(self.value())

    def reset(self) -> None:
        self.setIndex(self._default_index)

    def _frac(self) -> float:
        n = len(self.values) - 1
        return self._index / n if n else 0.0

    def _set_frac(self, frac: float) -> None:
        self.setIndex(int(round(frac * (len(self.values) - 1))))

    def _nudge(self, steps: int, fine: bool = False) -> None:
        self.setIndex(self._index + steps)


class RangeKnob(Knob):
    """Knob over a continuous range with a coarse step for wheel/keys."""

    def __init__(self, lo: float, hi: float, step: float, fmt=str,
                 title: str = "", color: str = "#7fd0ff", default=None,
                 snap: bool = True, **kwargs):
        self.lo, self.hi, self.step = float(lo), float(hi), float(step)
        self.snap = snap
        self.fmt = fmt
        self._value = float(default if default is not None else lo)
        self._default = self._value
        super().__init__(title=title, color=color, **kwargs)

    def value(self) -> float:
        return self._value

    def setValue(self, value, notify: bool = True) -> None:
        value = min(max(float(value), self.lo), self.hi)
        if self.snap:
            # Snap to the step grid so displayed and stored values agree.
            value = round(value / self.step) * self.step
            value = min(max(value, self.lo), self.hi)
        if abs(value - self._value) < self.step / 1e6:
            self.sync_text()
            return
        self._value = value
        self.update()
        self.sync_text()
        if notify:
            self.valueChanged.emit(value)

    def text(self) -> str:
        return self.fmt(self._value)

    def reset(self) -> None:
        self.setValue(self._default)

    def _frac(self) -> float:
        span = self.hi - self.lo
        return (self._value - self.lo) / span if span else 0.0

    def _set_frac(self, frac: float) -> None:
        self.setValue(self.lo + frac * (self.hi - self.lo))

    def _nudge(self, steps: int, fine: bool = False) -> None:
        self.setValue(self._value + steps * self.step * (0.2 if fine else 1.0))
