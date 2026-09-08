"""Entry point: python -m pyscope [options]"""
from __future__ import annotations

import argparse
import sys

from .sources import FORMATS, SourceConfig, list_alsa_devices


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pyscope",
                                description="Configurable ALSA oscilloscope")
    p.add_argument("-d", "--device", default="default", help="ALSA capture PCM")
    p.add_argument("-r", "--rate", type=int, default=48000, help="sample rate (Hz)")
    p.add_argument("-c", "--channels", type=int, default=2, help="channel count")
    p.add_argument("-f", "--format", dest="fmt", default="S16_LE", choices=FORMATS)
    p.add_argument("-p", "--period", type=int, default=1024,
                   help="ALSA period size in frames")
    p.add_argument("-b", "--buffer", type=float, default=2.0,
                   help="ring buffer depth in seconds")
    p.add_argument("--simulate", action="store_true",
                   help="use the built-in generator instead of a sound card")
    p.add_argument("-l", "--list-devices", action="store_true",
                   help="print capture devices and exit")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.list_devices:
        devs = list_alsa_devices()
        if not devs:
            print("no ALSA capture devices found (is pyalsaaudio installed?)")
            return 1
        print("\n".join(devs))
        return 0

    cfg = SourceConfig(device=args.device, rate=args.rate, channels=args.channels,
                       fmt=args.fmt, period=args.period,
                       buffer_seconds=args.buffer, simulate=args.simulate)

    from pyqtgraph.Qt import QtWidgets  # imported late so --list-devices is cheap

    from .ui import ScopeWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = ScopeWindow(cfg)
    win.show()
    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
