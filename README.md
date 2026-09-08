# pyscope — a configurable ALSA oscilloscope

A soft-scope for Linux audio inputs. Everything about the capture is
configurable (device, rate, channel count, sample format, period size, ring
depth), and the display behaves like a bench scope: 10 × 8 divisions,
per-channel gain/position/coupling, auto/normal/single edge triggering with
hysteresis and hold-off, draggable cursors, and automatic measurements.

A built-in signal generator (`--simulate`) drives the whole pipeline without a
sound card, so the UI can be developed and tested anywhere.

## Install

On Debian/Ubuntu-based distributions the system Python is PEP 668 managed, so
`pip install` into it will refuse. Use the distro packages:

```bash
sudo apt install -y python3-numpy python3-pyqtgraph python3-pyqt5 python3-alsaaudio
```

Or, for current upstream versions, a virtualenv:

```bash
sudo apt install -y python3-venv python3-dev build-essential libasound2-dev libxcb-cursor0
python3 -m venv .venv && .venv/bin/pip install numpy pyqtgraph PySide6 pyalsaaudio
```

`pyalsaaudio` compiles against `libasound2-dev`; `libxcb-cursor0` is the Qt6
runtime dependency PySide6 needs on Ubuntu 24.04 and later. Any of PyQt5,
PyQt6, PySide2 or PySide6 works — pyqtgraph picks up whichever is installed,
and the UI handles both the Qt5 and Qt6 enum conventions. Check which one was
picked with `python3 -c "from pyqtgraph.Qt import QT_LIB; print(QT_LIB)"`.

Run from the repository root — `python -m pyscope` needs the package on the
path. There is nothing to build or install.

## Run

```bash
python -m pyscope --list-devices
```

```bash
python -m pyscope -d hw:1,0 -r 96000 -c 4 -f S32_LE -p 512
```

```bash
python -m pyscope --simulate
```

Options: `-d/--device`, `-r/--rate`, `-c/--channels`, `-f/--format`
(`S16_LE`, `S24_3LE`, `S32_LE`, `FLOAT_LE`), `-p/--period`, `-b/--buffer`
(ring depth in seconds), `--simulate`, `-l/--list-devices`. Everything is also
editable live in the **Input** panel; **Apply / restart capture** reopens the
PCM. If the driver grants different parameters than requested (common with
`plughw:`), the panel is updated to what was actually granted.

## Using it

**Knobs** — V/div, position, time/div, trigger position, level, hysteresis and
hold-off are rotary knobs in the channel's own colour, each with an editable
field underneath. Drag up/down or scroll to turn, hold shift for fine steps on
the continuous ones, double-click to return to the default, arrow keys when
focused — or type the value straight into the field. The field accepts
engineering notation the same way the display writes it: `500 us`, `20 mFS`,
`1.5k`, `-0.0005`; the unit is ignored and only the SI prefix scales the
number. Stepped knobs (V/div, time/div) snap to the 1‑2‑5 sequence, so both a
typed value and one handed over by autoset land on a real detent.

**Vertical** — one strip per channel under the plot: enable, V/div, position in
divisions, DC/AC coupling, invert. Disabled channels are
still captured, just not drawn or measured. Amplitudes are in full-scale units:
±1.0 FS is the converter's clipping point, so 0.5 FS/div shows a full-scale
signal as 4 divisions.

**Horizontal** — time/div (1 µs … 1 s), and a trigger-position slider that sets
how much of the record is pre-trigger (0 % = trigger at the left edge, 50 % =
centred). Record length is `time/div × 10 × rate` samples, taken from the ring
buffer, so the pre-trigger history is real captured data.

**Autoset** — the `Autoset` button (or `a`) looks at a quarter second of the
live buffer and configures everything for what it finds: it enables the
channels carrying signal, picks a gain so each fills its share of the screen,
stacks them so they do not overlap, centres each on its own DC level, triggers
on the strongest channel at its waveform midpoint, and sets the timebase to
show a few cycles. It starts capture first if the scope is idle, and waits for
the buffer to fill before deciding. If every channel is below −54 dBFS it says
so and changes nothing.

**Trigger** — drag the dashed level line to set the level and the `T` marker to
slide the trigger point along the record; both update live while dragging and
the level line is labelled with its channel, slope and value. The same values
are in the Trigger panel: source channel, rising/falling/either slope, level in FS,
hysteresis, and hold-off in ms. Modes:

- `auto` — free-runs when no edge is found, so you always see something
- `normal` — only updates on a real edge
- `single` — arms once, captures one record, then stops

The level line is drawn in the source channel's gain and position, and wears
that channel's colour — on a multi-channel screen it can otherwise look like it
sits on a trace it has nothing to do with. **Level to 50 %** drops it onto the
midpoint of the source channel's current signal, which is the quickest way to
get a stable trigger.

The trigger always sits at t = 0, so dragging the `T` marker really changes how
much of the record is pre-trigger — the marker snaps back to the trigger point
and the trace shifts under it.

**Hysteresis** is the band an edge must cross cleanly: the signal has to arm
below `level − hyst` before a rising edge counts, which stops noise on the
threshold from retriggering. A band wider than the signal blocks *every* edge,
which looks exactly like a broken trigger — so **auto hysteresis** (on by
default) tracks 5 % of the source channel's amplitude. Turn it off to set the
band by hand.

When `normal` or `single` finds no edge the status bar says why, e.g.
`NO TRIG (CH1 spans -60 mFS..60 mFS - level -80 mFS is outside that range)` or
`... - hysteresis 10 mFS is wider than the signal`, rather than leaving an
apparently frozen screen.

**Cursors** — T1/T2 give Δt and 1/Δt; Y1/Y2 give Δ in the units of the channel
named in **Y1/Y2 measured in** (they follow that channel's V/div and position).
That picker only affects the cursor readout — the trigger's channel is the
separate **trigger on** picker, and the Trigger panel's title names it, e.g.
`Trigger - watching CH2`, in that channel's colour. Readout sits under the plot.

**Measurements** — per enabled channel: Vpp, Vmax, Vmin, mean, RMS, frequency,
period, duty cycle, 10‑90 % rise time. Frequency comes from hysteresis-qualified
mid-level crossings, falling back to a parabolically-interpolated FFT peak when
the record holds less than two cycles.

**Keys** — `space` run/stop, `s` single, `f` force trigger, `a` autoset. **Export CSV**
writes the record currently on screen (time column plus one column per channel).

## Layout

| file | role |
| --- | --- |
| `pyscope/ring.py` | lock-protected ring buffer with a global sample counter |
| `pyscope/sources.py` | ALSA capture thread, PCM decoding, signal simulator |
| `pyscope/trigger.py` | edge search, hold-off, record extraction |
| `pyscope/measure.py` | automatic measurements, engineering formatting |
| `pyscope/autoset.py` | picks gain, position, timebase and trigger from data |
| `pyscope/knobs.py` | rotary knob widgets |
| `pyscope/qtcompat.py` | enum and event access across the four Qt bindings |
| `pyscope/ui.py` | Qt/pyqtgraph front end |

Capture runs in its own thread and only ever appends to the ring buffer; the UI
timer (40 Hz) takes a snapshot, searches it for a trigger and redraws. The two
never block each other, so a slow repaint costs frames but never samples.

## Tests

```bash
python -m pytest -q
```

56 headless tests cover the ring buffer (wrap-around, oversized writes, global
indices), PCM decoding for all four formats, the trigger engine (slopes,
hysteresis, arming, hold-off, auto/normal/single, pre-trigger placement), the
measurements, the engineering-notation parser behind the knob fields, and the
autoset planner (gain fitting, offset handling, stacking within the graticule,
silence detection).

The UI has its own offscreen smoke test — it builds the window, runs the
simulator, drags both trigger handles, runs autoset and checks it finds the
signal, then saves a screenshot:

```bash
QT_QPA_PLATFORM=offscreen python tests/smoke_ui.py smoke.png
```

## Notes and limits

- Amplitudes are full-scale, not volts. For real voltage readings, multiply by
  your interface's input sensitivity — a fixed scale factor per channel would be
  the natural next feature.
- Audio interfaces are AC-coupled and band-limited: DC and very low frequencies
  are attenuated, so square waves will droop. That is the hardware, not the app.
- Overruns are counted in the status bar. If they climb, raise the period size
  or lower the rate.
- `hw:` devices give you the raw hardware format; `plughw:`/`default` let ALSA
  convert, which is more forgiving but may resample.
