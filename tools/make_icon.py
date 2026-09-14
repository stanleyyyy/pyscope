"""Draw the program icon and write pyscope/assets/pyscope.{png,ico}.

A dark rounded tile with a faint graticule and two traces - a yellow sine and
a cyan square - the same colours as CH1 and CH2 on screen. Rendered with Qt so
there is no extra dependency; the .ico is written by hand since it is just a
header over PNG blobs.

    python tools/make_icon.py
"""
from __future__ import annotations

import math
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pyscope.qtcompat import ANTIALIASING, ROUND_CAP, SOLID_LINE, qt_enum  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "pyscope", "assets")
SIZES = (16, 24, 32, 48, 64, 128, 256)
TRANSPARENT = qt_enum(QtCore.Qt, "GlobalColor", "transparent")
FORMAT_ARGB = qt_enum(QtGui.QImage, "Format", "Format_ARGB32_Premultiplied")
FLAT_CAP = qt_enum(QtCore.Qt, "PenCapStyle", "FlatCap")
ROUND_JOIN = qt_enum(QtCore.Qt, "PenJoinStyle", "RoundJoin")


def render(size: int) -> QtGui.QImage:
    img = QtGui.QImage(size, size, FORMAT_ARGB)
    img.fill(TRANSPARENT)
    p = QtGui.QPainter(img)
    p.setRenderHint(ANTIALIASING, True)
    s = float(size)

    # Tile.
    radius = s * 0.2
    p.setPen(QtGui.QPen(QtGui.QColor("#39424b"), max(1.0, s / 64)))
    p.setBrush(QtGui.QBrush(QtGui.QColor("#101418")))
    p.drawRoundedRect(QtCore.QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94),
                      radius, radius)

    # Graticule: only worth drawing once there is room for it.
    inset = s * 0.14
    if size >= 32:
        p.setPen(QtGui.QPen(QtGui.QColor(90, 100, 110, 110), max(1.0, s / 128)))
        for i in range(1, 4):
            x = inset + (s - 2 * inset) * i / 4
            p.drawLine(QtCore.QPointF(x, inset), QtCore.QPointF(x, s - inset))
            p.drawLine(QtCore.QPointF(inset, x), QtCore.QPointF(s - inset, x))

    width = max(1.5, s / 14)
    left, right = inset, s - inset

    # CH2: cyan square, lower half.
    y_hi, y_lo = s * 0.56, s * 0.78
    pts = [QtCore.QPointF(left, y_lo), QtCore.QPointF(s * 0.32, y_lo),
           QtCore.QPointF(s * 0.32, y_hi), QtCore.QPointF(s * 0.58, y_hi),
           QtCore.QPointF(s * 0.58, y_lo), QtCore.QPointF(right, y_lo)]
    p.setPen(QtGui.QPen(QtGui.QColor("#00d0ff"), width, SOLID_LINE, ROUND_CAP,
                        ROUND_JOIN))
    p.setBrush(QtGui.QBrush())
    p.drawPolyline(QtGui.QPolygonF(pts))

    # CH1: yellow sine, upper half.
    path = QtGui.QPainterPath()
    mid, amp = s * 0.33, s * 0.15
    n = max(24, size)
    for i in range(n + 1):
        x = left + (right - left) * i / n
        y = mid - amp * math.sin(2 * math.pi * 1.5 * i / n)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    p.setPen(QtGui.QPen(QtGui.QColor("#ffd400"), width, SOLID_LINE, ROUND_CAP,
                        ROUND_JOIN))
    p.drawPath(path)
    p.end()
    return img


def png_bytes(img: QtGui.QImage) -> bytes:
    buf = QtCore.QBuffer()
    buf.open(qt_enum(QtCore.QIODevice, "OpenModeFlag", "WriteOnly"))
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: str, images: list[tuple[int, bytes]]) -> None:
    """ICO container with PNG-compressed entries (Vista+; all we target)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in images:
        dim = 0 if size >= 256 else size      # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    with open(path, "wb") as fh:
        fh.write(header + entries + blobs)


def main() -> None:
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    os.makedirs(ASSETS, exist_ok=True)
    images = [(size, png_bytes(render(size))) for size in SIZES]
    with open(os.path.join(ASSETS, "pyscope.png"), "wb") as fh:
        fh.write(images[-1][1])
    write_ico(os.path.join(ASSETS, "pyscope.ico"), images)
    for size, blob in images:
        print("%4d px  %6d bytes" % (size, len(blob)))
    print("wrote", os.path.join(ASSETS, "pyscope.png"), "and pyscope.ico")


if __name__ == "__main__":
    main()
