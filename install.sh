#!/usr/bin/env bash
# ===========================================================================
# install.sh  -  set up pyscope on Linux / macOS for the current user
#   * installs the app into its own environment via pipx (or a venv)
#   * links the `pyscope` command into ~/.local/bin
#   * (Linux) creates a .desktop launcher
#   * points out the one system library PortAudio needs on Linux
# Run:  ./install.sh              no root needed
#       ./install.sh --alsa       also build the direct-ALSA backend (Linux)
# ===========================================================================
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bindir="${HOME}/.local/bin"
extra=""
[ "${1:-}" = "--alsa" ] && extra="[alsa]"

# --- Python ---------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 not found. Install it with your package manager, e.g.:"
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv pipx"
    echo "  Fedora:         sudo dnf install python3 pipx"
    echo "  Arch:           sudo pacman -S python python-pipx"
    exit 1
fi

# --- PortAudio runtime (Linux only; the wheel bundles it elsewhere) -------
if [ "$(uname -s)" = "Linux" ] && ! ldconfig -p 2>/dev/null | grep -q libportaudio; then
    echo "libportaudio not found. Install it first, e.g.:"
    echo "  Debian/Ubuntu:  sudo apt install libportaudio2"
    echo "  Fedora:         sudo dnf install portaudio"
    echo "  Arch:           sudo pacman -S portaudio"
    echo "...then re-run this script."
    exit 1
fi

if [ -n "${extra}" ] && [ "$(uname -s)" = "Linux" ] && [ ! -f /usr/include/alsa/asoundlib.h ]; then
    echo "--alsa needs the ALSA headers and a compiler, e.g.:"
    echo "  Debian/Ubuntu:  sudo apt install libasound2-dev python3-dev build-essential"
    echo "  Fedora:         sudo dnf install alsa-lib-devel python3-devel gcc"
    exit 1
fi

# --- install: pipx if present, else a private venv ------------------------
mkdir -p "${bindir}"
if command -v pipx >/dev/null 2>&1; then
    echo "Installing with pipx..."
    pipx install --force "${here}${extra}"
    installed_cmd="${bindir}/pyscope"
    [ -x "${installed_cmd}" ] || installed_cmd="$(command -v pyscope || true)"
else
    venv="${HOME}/.local/share/pyscope/venv"
    echo "pipx not found; installing into ${venv}..."
    python3 -m venv "${venv}"
    "${venv}/bin/pip" install --upgrade pip >/dev/null
    "${venv}/bin/pip" install --upgrade "${here}${extra}"
    ln -sf "${venv}/bin/pyscope" "${bindir}/pyscope"
    installed_cmd="${bindir}/pyscope"
fi
echo "installed: ${installed_cmd}"

case ":${PATH}:" in
    *":${bindir}:"*) : ;;
    *) echo "note: ${bindir} is not on your PATH -- add to ~/.bashrc:"
       echo "      export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

# --- desktop launcher (Linux) --------------------------------------------
if [ "$(uname -s)" = "Linux" ]; then
    icondir="${HOME}/.local/share/icons/hicolor/256x256/apps"
    mkdir -p "${icondir}"
    install -m 0644 "${here}/pyscope/assets/pyscope.png" "${icondir}/pyscope.png"
    appdir="${HOME}/.local/share/applications"
    mkdir -p "${appdir}"
    cat > "${appdir}/pyscope.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=pyscope
Comment=Audio-input oscilloscope
Exec=${installed_cmd}
Icon=pyscope
Terminal=false
Categories=AudioVideo;Audio;Science;Electronics;
Keywords=oscilloscope;scope;audio;alsa;
EOF
    echo "installed: ${appdir}/pyscope.desktop"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${appdir}" 2>/dev/null || true
fi

echo
echo "Done. Run:  pyscope --list-devices"
echo "            pyscope --simulate        (no hardware needed)"
