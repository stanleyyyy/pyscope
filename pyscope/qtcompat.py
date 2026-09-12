"""Enum and event access that works across Qt bindings.

pyqtgraph may bind to PyQt5, PyQt6, PySide2 or PySide6. Qt6 bindings only
expose enum members through their scope (`Qt.PenStyle.DashLine`), Qt5 bindings
expose them unscoped, and a few members exist in only one form. Everything the
UI needs is resolved here once.
"""
from __future__ import annotations

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets


def qt_enum(owner, scope: str, name: str):
    """Fetch an enum member, trying the Qt6 scoped spelling first."""
    holder = getattr(owner, scope, None)
    if holder is not None and hasattr(holder, name):
        return getattr(holder, name)
    return getattr(owner, name)


DASH_LINE = qt_enum(QtCore.Qt, "PenStyle", "DashLine")
DOT_LINE = qt_enum(QtCore.Qt, "PenStyle", "DotLine")
DASH_DOT_LINE = qt_enum(QtCore.Qt, "PenStyle", "DashDotLine")
SOLID_LINE = qt_enum(QtCore.Qt, "PenStyle", "SolidLine")
NO_PEN = qt_enum(QtCore.Qt, "PenStyle", "NoPen")
ROUND_CAP = qt_enum(QtCore.Qt, "PenCapStyle", "RoundCap")
FLAT_CAP = qt_enum(QtCore.Qt, "PenCapStyle", "FlatCap")

HORIZONTAL = qt_enum(QtCore.Qt, "Orientation", "Horizontal")
ALIGN_CENTER = qt_enum(QtCore.Qt, "AlignmentFlag", "AlignCenter")
ALIGN_HCENTER = qt_enum(QtCore.Qt, "AlignmentFlag", "AlignHCenter")
STRONG_FOCUS = qt_enum(QtCore.Qt, "FocusPolicy", "StrongFocus")
LEFT_BUTTON = qt_enum(QtCore.Qt, "MouseButton", "LeftButton")
SHIFT_MODIFIER = qt_enum(QtCore.Qt, "KeyboardModifier", "ShiftModifier")
POINTING_CURSOR = qt_enum(QtCore.Qt, "CursorShape", "PointingHandCursor")
SIZE_VER_CURSOR = qt_enum(QtCore.Qt, "CursorShape", "SizeVerCursor")

KEY_SPACE = qt_enum(QtCore.Qt, "Key", "Key_Space")
KEY_S = qt_enum(QtCore.Qt, "Key", "Key_S")
KEY_F = qt_enum(QtCore.Qt, "Key", "Key_F")
KEY_A = qt_enum(QtCore.Qt, "Key", "Key_A")
KEY_UP = qt_enum(QtCore.Qt, "Key", "Key_Up")
KEY_DOWN = qt_enum(QtCore.Qt, "Key", "Key_Down")
KEY_LEFT = qt_enum(QtCore.Qt, "Key", "Key_Left")
KEY_RIGHT = qt_enum(QtCore.Qt, "Key", "Key_Right")

ANTIALIASING = qt_enum(QtGui.QPainter, "RenderHint", "Antialiasing")
WINDOW_TEXT = qt_enum(QtGui.QPalette, "ColorRole", "WindowText")
WINDOW = qt_enum(QtGui.QPalette, "ColorRole", "Window")
ELIDE_RIGHT = qt_enum(QtCore.Qt, "TextElideMode", "ElideRight")
NO_EDIT = qt_enum(QtWidgets.QAbstractItemView, "EditTrigger", "NoEditTriggers")
STRETCH = qt_enum(QtWidgets.QHeaderView, "ResizeMode", "Stretch")
SCROLLBAR_OFF = qt_enum(QtCore.Qt, "ScrollBarPolicy",
                        "ScrollBarAlwaysOff")
NO_FRAME = qt_enum(QtWidgets.QFrame, "Shape", "NoFrame")
TOOLTIP_ROLE = qt_enum(QtCore.Qt, "ItemDataRole", "ToolTipRole")


def event_pos(event) -> tuple[float, float]:
    """Mouse position from a QMouseEvent on either Qt generation."""
    getter = getattr(event, "position", None) or getattr(event, "pos")
    p = getter()
    return float(p.x()), float(p.y())


def _luminance(c: QtGui.QColor) -> float:
    def channel(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(c.red()) + 0.7152 * channel(c.green())
            + 0.0722 * channel(c.blue()))


def contrast(a: QtGui.QColor, b: QtGui.QColor) -> float:
    """WCAG contrast ratio, 1 (identical) to 21 (black on white)."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable(color, background, target: float = 4.5) -> str:
    """Darken or lighten `color` until it reads against `background`.

    The channel colours are chosen for a black graticule; on a light desktop
    theme the same yellow on a grey panel is nearly invisible. Keeping the hue
    and moving only the lightness preserves the channel's identity.
    """
    c = QtGui.QColor(color)
    bg = QtGui.QColor(background)
    if contrast(c, bg) >= target:
        return c.name()
    h, sat, light, alpha = c.getHslF()
    step = -0.02 if _luminance(bg) > 0.5 else 0.02
    for _ in range(60):
        light = min(max(light + step, 0.0), 1.0)
        c = QtGui.QColor.fromHslF(h, sat, light, alpha)
        if contrast(c, bg) >= target:
            break
        if light in (0.0, 1.0):
            break
    return c.name()
