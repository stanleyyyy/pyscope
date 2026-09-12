"""Entry point: python -m pyscope [options]"""
from __future__ import annotations

import argparse
import sys

from . import settings
from .sources import BACKENDS, FORMATS, list_devices


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pyscope",
                                description="Configurable audio-input oscilloscope")
    # Defaults are None so an unset option can fall through to the stored
    # session; the built-in defaults live in settings.default_state().
    p.add_argument("-d", "--device",
               help="capture device: an ALSA PCM name (hw:2,0), a PortAudio "
                    "index or name substring, or default")
    p.add_argument("-r", "--rate", type=int, help="sample rate (Hz)")
    p.add_argument("-c", "--channels", type=int, help="channel count")
    p.add_argument("-f", "--format", dest="fmt", choices=FORMATS)
    p.add_argument("-p", "--period", type=int,
                   help="block size in frames")
    p.add_argument("-b", "--buffer", type=float,
                   help="ring buffer depth in seconds")
    p.add_argument("--backend", choices=BACKENDS,
                   help="auto picks ALSA for ALSA names when available, else "
                        "PortAudio (Windows, macOS, Linux)")
    p.add_argument("--simulate", action="store_true", default=None,
                   help="use the built-in generator (same as --backend sim)")
    p.add_argument("--preset", help="start from a saved preset")
    p.add_argument("--no-restore", action="store_true",
                   help="ignore the stored session and preset")
    p.add_argument("-l", "--list-devices", action="store_true",
                   help="print capture devices and exit")
    p.add_argument("--list-presets", action="store_true",
                   help="print saved preset names and exit")
    return p.parse_args(argv)


def resolve_state(args: argparse.Namespace) -> dict:
    """Built-in defaults, then the stored session or preset, then the CLI."""
    state = settings.default_state()
    if not args.no_restore:
        store = settings.load_store()
        stored = (store["presets"].get(args.preset) if args.preset
                  else store["last"])
        if stored:
            state = settings.merge(state, stored)
    overrides = {"device": args.device, "rate": args.rate,
                 "channels": args.channels, "fmt": args.fmt,
                 "period": args.period, "buffer_seconds": args.buffer,
                 "simulate": args.simulate,
                 "backend": "sim" if args.simulate else args.backend}
    state = settings.merge(state, {"input": overrides})
    if args.channels is not None:
        # A different channel count invalidates the stored per-channel list.
        state["input"]["channels"] = args.channels
    return settings.normalise(state)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.list_devices:
        devs = list_devices()
        if not devs:
            print("no capture devices found (is sounddevice or pyalsaaudio "
                  "installed?)")
            return 1
        width = max(len(b) for b, _ in devs)
        for backend, name in devs:
            print("%-*s  %s" % (width, backend, name))
        return 0
    if args.list_presets:
        names = sorted(settings.load_store()["presets"])
        print("\n".join(names) if names else
              "no presets saved yet (%s)" % settings.store_path())
        return 0
    if args.preset and args.preset not in settings.load_store()["presets"]:
        print("no preset named %r in %s" % (args.preset, settings.store_path()),
              file=sys.stderr)
        return 1

    state = resolve_state(args)
    cfg = settings.state_to_config(state)

    from pyqtgraph.Qt import QtWidgets  # imported late so --list-* stays cheap

    from .ui import ScopeWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = ScopeWindow(cfg, restore=state)
    win.show()
    return app.exec() if hasattr(app, "exec") else app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
