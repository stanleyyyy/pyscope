# pyscope — a configurable audio-input oscilloscope

A soft-scope for sound-card inputs on Linux, Windows and macOS. Everything
about the capture is configurable (backend, device, rate, channel count,
sample format, block size, ring depth), and the display behaves like a bench
scope: 10 × 8 divisions,
per-channel gain/position/coupling, auto/normal/single edge triggering with
hysteresis and hold-off, draggable cursors, and automatic measurements.

A built-in signal generator (`--simulate`) drives the whole pipeline without a
sound card, so the UI can be developed and tested anywhere.

## Install

pyscope is a normal Python package with a `pyscope` command. The recommended
way to install a Python application system-wide is [pipx](https://pipx.pypa.io),
which puts it in its own isolated environment and links the command onto your
`PATH` — it works the same on any Linux distribution, macOS and Windows, and
never touches the interpreter your operating system depends on.

```bash
pipx install git+https://github.com/stanleyyyy/pyscope
```

or from a clone:

```bash
pipx install .
```

Then, from anywhere:

```bash
pyscope --list-devices
```

Upgrade later with `pipx upgrade pyscope`, remove with `pipx uninstall pyscope`.
[uv](https://docs.astral.sh/uv/) users can do the same with `uv tool install .`.

### Prerequisites

Nothing is compiled during installation: every dependency ships as a binary
wheel. Two things still come from the operating system:

- **PortAudio** (Linux only) — the `sounddevice` wheel bundles PortAudio on
  Windows and macOS but not on Linux, where it is a small runtime library:
  `libportaudio2` on Debian/Ubuntu, `portaudio` on Fedora/Arch. No headers, no
  compiler.
- **Qt's platform libraries** — the PySide6 wheel bundles Qt itself, but needs
  the usual X11/Wayland client libraries. Most desktops already have them; the
  one commonly missing is `libxcb-cursor0` (Ubuntu 24.04 and later). If the
  window never appears and the terminal mentions a "platform plugin", that is
  the missing piece.

Without any input device — a headless box, or WSL, which has no sound
hardware — `pyscope --simulate` still runs the whole application on the
built-in signal generator.

**Direct ALSA access** is an optional extra for Linux, for when you want the
hardware sample format (`S24_3LE`, `S32_LE`) or a raw `hw:` device without
PortAudio in between. It compiles a small C binding against the ALSA headers,
so it needs `libasound2-dev` (Debian/Ubuntu), `alsa-lib-devel` (Fedora/RHEL)
or `alsa-lib` (Arch), plus `python3-dev` and a compiler:

```bash
pipx install 'git+https://github.com/stanleyyyy/pyscope#egg=pyscope[alsa]'
```

or `pipx install '.[alsa]'` from a clone. Without it, ALSA devices are still
reachable through PortAudio's ALSA host — they appear in the device list under
their card name.

Do not `pip install` straight into the system interpreter: most current
distributions mark it as externally managed and refuse, and those that do not
will still let you break tools the OS depends on. pipx, uv or a virtualenv are
the right tools for that job.

### Alternatives

A virtualenv works everywhere pipx does and is what you want for development:

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e .[dev]
```

`-e` makes it an editable install, so code changes take effect without
reinstalling; `[dev]` pulls in pytest.

If you would rather have every dependency come from your distribution, install
its packages for numpy, pyqtgraph, a Qt binding and sounddevice or pyalsaaudio
(on Debian and Ubuntu: `python3-numpy python3-pyqtgraph python3-pyqt5
python3-sounddevice python3-alsaaudio`) and run `python3 -m pyscope` from a
clone — nothing needs building in that case.
Any of PyQt5, PyQt6, PySide2 or PySide6 works: pyqtgraph picks up whichever is
installed, and the UI handles both the Qt5 and Qt6 enum conventions. Check
which one was picked with
`python3 -c "from pyqtgraph.Qt import QT_LIB; print(QT_LIB)"`.

## Run

```bash
pyscope --list-devices
```

```bash
pyscope -d hw:1,0 -r 96000 -c 4 -f S32_LE -p 512
```

```bash
pyscope --simulate
```

`python -m pyscope` is equivalent from a clone. Capture starts as soon as the
window opens.

Options: `-d/--device`, `-r/--rate`, `-c/--channels`, `-f/--format`
(`S16_LE`, `S24_3LE`, `S32_LE`, `FLOAT_LE`; ALSA backend only), `-p/--period`
(block size in frames), `-b/--buffer` (ring depth in seconds), `--backend`
(`auto`, `alsa`, `portaudio`, `sim`), `--simulate`, `--preset NAME`,
`--no-restore`, `-l/--list-devices`, `--list-presets`. Everything is also editable live in the
**Input** panel; **Apply / restart capture** reopens the PCM. If the driver
grants different parameters than requested (common with `plughw:`), the panel
is updated to what was actually granted.

## Backends

`--list-devices` prints every input the installed backends can see, prefixed
with the backend that owns it:

```
alsa       hw:2,0
alsa       plughw:2,0
portaudio  3: Line In (2- Realtek USB Audio)
```

- **portaudio** — `sounddevice` over PortAudio: WASAPI/DirectSound on Windows,
  CoreAudio on macOS, ALSA or PulseAudio on Linux. Devices are addressed by
  index (`-d 3`), by the listing's `3: Line In` form, by a name substring
  (`-d "Line In"`), or `default`. Samples arrive as float32, so the format
  setting does not apply and is greyed out.
- **alsa** — direct ALSA via `pyalsaaudio` (the `[alsa]` extra, Linux only).
  Addressed by PCM name: `hw:2,0`, `plughw:2,0`, `default`, `sysdefault:CARD=…`.
  Gives you the hardware sample format and the raw stream with no resampling.
- **sim** — the built-in generator; `--simulate` is shorthand.
- **auto** (the default) sends ALSA-style names to ALSA when it is installed
  and everything else to PortAudio, so `-d hw:2,0` and `-d 3` both just work.

## Settings and presets

Settings live in `$XDG_CONFIG_HOME/pyscope/settings.json` (`~/.config/pyscope`
by default; `PYSCOPE_CONFIG_DIR` overrides it). The file holds the last session
and any named presets, and is written atomically — a corrupt or hand-mangled
file is ignored rather than crashing the app, and missing or nonsensical fields
fall back to defaults.

The **Presets** panel saves every setting under a name — device, rate, channel
count, format, per-channel gain/position/coupling, timebase, trigger and
cursors — and loads it back, restarting capture if the input changed. Closing
the window stores the session, and the next launch restores it.

Precedence at startup is **built-in defaults → stored session (or `--preset`)
→ command line**, so

```bash
pyscope -d hw:2,0 -c 4 -r 96000 -f S32_LE
```

uses those four values and keeps your saved timebase, trigger and cursors.
`--no-restore` starts from the built-in defaults instead.

**Reset UI to defaults** returns channels, timebase, trigger and cursors to
their defaults while leaving the capture settings and the running stream
alone.

## Using it

Channel colours are chosen for the black graticule; captions on the control
panels are darkened or lightened until they reach a WCAG contrast of 4.5
against whatever your desktop theme paints behind them, keeping the hue so a
channel is still identifiable. The traces themselves always keep the bright
colour.

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
which looks exactly like a broken trigger. In `auto` mode the scope is finding
the signal for you, so it tracks 5 % of the source channel's amplitude there
and hands the measured value over when you switch to `normal` or `single` —
where the knob is yours to set.

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
| `pyscope/sources.py` | ALSA and PortAudio capture, PCM decoding, signal simulator |
| `pyscope/trigger.py` | edge search, hold-off, record extraction |
| `pyscope/measure.py` | automatic measurements, engineering formatting |
| `pyscope/settings.py` | the settings schema, presets and their JSON store |
| `pyscope/autoset.py` | picks gain, position, timebase and trigger from data |
| `pyscope/knobs.py` | rotary knob widgets |
| `pyscope/qtcompat.py` | enum, event and colour-contrast helpers across bindings |
| `pyscope/ui.py` | Qt/pyqtgraph front end |

Capture runs in its own thread and only ever appends to the ring buffer; the UI
timer (40 Hz) takes a snapshot, searches it for a trigger and redraws. The two
never block each other, so a slow repaint costs frames but never samples.

## Tests

```bash
pip install -e .[dev] && python -m pytest -q
```

95 headless tests cover the ring buffer (wrap-around, oversized writes, global
indices), PCM decoding for all four formats, the trigger engine (slopes,
hysteresis, arming, hold-off, auto/normal/single, pre-trigger placement), the
measurements, the engineering-notation parser behind the knob fields, the
autoset planner (gain fitting, offset handling, stacking within the graticule,
silence detection), the settings layer (preset round-trips, corrupt files,
partial states, command-line precedence), and the backends (ALSA-name
detection, auto selection, PortAudio device resolution and a stubbed
PortAudio stream feeding the ring).

The UI has its own offscreen smoke test — it builds the window, runs the
simulator, drags both trigger handles, runs autoset and checks it finds the
signal, types into the knob fields, round-trips a preset through the real widgets,
and — when the host has an input device — captures live audio through
PortAudio, then saves a screenshot:

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
- With the ALSA backend, `hw:` devices give you the raw hardware format;
  `plughw:`/`default` let ALSA convert, which is more forgiving but may
  resample. PortAudio always converts to float32 and may resample too.
- On Windows, WASAPI shared mode resamples to the mixer rate; if the rate you
  ask for is refused, use the one Windows shows for the device in Sound
  settings, or a different host API's copy of the same device in the list.
