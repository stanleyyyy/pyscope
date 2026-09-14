# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for pyscope.

Builds a one-directory bundle (dist/pyscope/) holding two launchers over one
shared set of libraries:

  pyscope        windowed - what shortcuts and the installer point at
  pyscope-cli    console  - so --list-devices / --list-presets can print

One-file was rejected on purpose: a Qt app that way unpacks ~150 MB to a temp
directory on every launch.

Build:  pyinstaller pyscope.spec
"""
import ctypes.util
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

WINDOWS = sys.platform.startswith("win")
LINUX = sys.platform.startswith("linux")

# Only the Qt modules the app touches; everything else PySide6 ships (WebEngine,
# 3D, Multimedia...) would otherwise be dragged in and triple the size.
QT_KEEP = {"QtCore", "QtGui", "QtWidgets", "QtOpenGL", "QtOpenGLWidgets", "QtSvg"}
QT_DROP = [
    "PySide6." + m for m in (
        "Qt3DAnimation", "Qt3DCore", "Qt3DExtras", "Qt3DInput", "Qt3DLogic",
        "Qt3DRender", "QtBluetooth", "QtCharts", "QtConcurrent", "QtDataVisualization",
        "QtDBus", "QtDesigner", "QtGraphs", "QtHelp", "QtHttpServer", "QtLocation",
        "QtMultimedia", "QtMultimediaWidgets", "QtNetwork", "QtNetworkAuth", "QtNfc",
        "QtPdf", "QtPdfWidgets", "QtPositioning", "QtPrintSupport", "QtQml",
        "QtQuick", "QtQuick3D", "QtQuickControls2", "QtQuickWidgets",
        "QtRemoteObjects", "QtScxml", "QtSensors", "QtSerialBus", "QtSerialPort",
        "QtSpatialAudio", "QtSql", "QtStateMachine", "QtSvgWidgets", "QtTest",
        "QtTextToSpeech", "QtUiTools", "QtWebChannel", "QtWebEngineCore",
        "QtWebEngineQuick", "QtWebEngineWidgets", "QtWebSockets", "QtWebView",
        "QtXml",
    )
]

hidden = ["sounddevice", "_sounddevice_data"]
hidden += collect_submodules("pyqtgraph.graphicsItems")
hidden += collect_submodules("pyqtgraph.widgets")

binaries = []
if LINUX:
    # The manylinux sounddevice wheel does not bundle PortAudio; carry the
    # system library so the tarball runs on a machine without libportaudio2.
    lib = ctypes.util.find_library("portaudio")
    if lib:
        for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib",
                  "/usr/local/lib"):
            path = os.path.join(d, lib)
            if os.path.exists(path):
                binaries.append((path, "."))
                break

ICON = os.path.join("pyscope", "assets", "pyscope.ico")

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=[(os.path.join("pyscope", "assets"), os.path.join("pyscope", "assets"))],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=QT_DROP + ["tkinter", "matplotlib", "scipy", "pandas", "IPython",
                        "jupyter", "PyQt5", "PyQt6", "PySide2", "pytest"],
    noarchive=False,
    optimize=1,
)

# PySide6's hook copies every Qt library next to the ones we import. Drop the
# stacks this app never loads; the size roughly halves and nothing changes.
# pyqtgraph imports QtOpenGL and QtSvg at load time, so those two stay.
DROP_FRAGMENTS = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6Network",
                  "Qt6VirtualKeyboard", "Qt6LabsAnimation", "Qt6ShaderTools",
                  os.path.join("PySide6", "translations"),
                  os.path.join("PySide6", "qml"))


def _keep(entry):
    return not any(frag in entry[0] for frag in DROP_FRAGMENTS)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)

common = dict(
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX corrupts Qt DLLs often enough not to be worth it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="pyscope",
          console=False, icon=ICON, **common)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="pyscope-cli",
          console=True, icon=ICON, **common)

coll = COLLECT(gui, cli, a.binaries, a.datas, name="pyscope")
