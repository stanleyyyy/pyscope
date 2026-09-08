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
NO_EDIT = qt_enum(QtWidgets.QAbstractItemView, "EditTrigger", "NoEditTriggers")
STRETCH = qt_enum(QtWidgets.QHeaderView, "ResizeMode", "Stretch")


def event_pos(event) -> tuple[float, float]:
    """Mouse position from a QMouseEvent on either Qt generation."""
    getter = getattr(event, "position", None) or getattr(event, "pos")
    p = getter()
    return float(p.x()), float(p.y())
