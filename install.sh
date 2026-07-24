#!/usr/bin/env bash
# Installer for acarsdec_v2 - macOS and Linux.
# Installs the dependencies (rtl-sdr, numpy, scipy) and makes the
# 'acarsdec_v2' command available system-wide.
# Manual steps are documented in README.md / README_ACARS_RX_FR.md for those who prefer.

DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$DIR/acarsdec_v2.py"
OS="$(uname -s)"
SUDO=""

echo "=== acarsdec_v2 installer ==="
echo "[*] Folder : $DIR"

if [ "$OS" = "Darwin" ]; then
    echo "[*] macOS detected."
    if ! command -v brew >/dev/null 2>&1; then
        echo "[!] Homebrew not found. Install it from https://brew.sh then re-run."
        exit 1
    fi
    echo "[*] Installing rtl-sdr tools (librtlsdr)..."
    brew list librtlsdr >/dev/null 2>&1 || brew install librtlsdr
    # Same as on Linux: skip when already importable, and stay verbose otherwise,
    # because a silenced pip looks exactly like a frozen script.
    if python3 -c "import numpy, scipy" 2>/dev/null; then
        echo "[OK] numpy and scipy already available for $(command -v python3)"
    else
        echo "[*] Installing numpy and scipy for $(command -v python3) ..."
        echo "    (pip output is shown on purpose: this step can take a few minutes)"
        python3 -m pip install numpy scipy \
            || python3 -m pip install --break-system-packages numpy scipy
    fi
    BINDIR="$(brew --prefix)/bin"
elif [ "$OS" = "Linux" ]; then
    echo "[*] Linux detected."
    if command -v apt >/dev/null 2>&1; then
        echo "[*] Installing rtl-sdr via apt. sudo will ask for your password."
        echo "    (apt can take a minute, it is not frozen)"
        sudo apt-get update
        sudo apt-get install -y rtl-sdr python3-numpy python3-scipy
    else
        echo "[!] 'apt' not found. Install rtl-sdr with your package manager,"
        echo "    then re-run this script."
    fi
    # numpy/scipy must exist for the ACTIVE python3 (conda, venv or system), because
    # the acarsdecv2 shebang is '#!/usr/bin/env python3'. Skip entirely when they are
    # already importable: pip is slow and, when silenced, looks like a freeze.
    if python3 -c "import numpy, scipy" 2>/dev/null; then
        echo "[OK] numpy and scipy already available for $(command -v python3)"
    else
        echo "[*] Installing numpy and scipy for $(command -v python3) ..."
        echo "    (pip output is shown on purpose: this step can take a few minutes)"
        python3 -m pip install numpy scipy \
            || python3 -m pip install --break-system-packages numpy scipy \
            || echo "[i] pip step failed; the apt python3-numpy/scipy may already cover you."
    fi
    # RTL-SDR runtime: free the dongle from the DVB kernel driver (and readsb)
    echo "[*] Setting up the RTL-SDR (freeing it from the DVB kernel driver)..."
    sudo systemctl stop readsb 2>/dev/null || true
    sudo modprobe -r dvb_usb_rtl28xxu rtl2832_sdr 2>/dev/null || true
    BLACKLIST="/etc/modprobe.d/blacklist-rtlsdr.conf"
    if [ ! -f "$BLACKLIST" ]; then
        echo "blacklist dvb_usb_rtl28xxu" | sudo tee "$BLACKLIST" >/dev/null 2>&1 \
            && echo "[OK] DVB driver blacklisted ($BLACKLIST). Replug the dongle." \
            || echo "[i] Could not write the blacklist (skipped); rmmod above still frees it for now."
    else
        echo "[i] DVB blacklist already present ($BLACKLIST)."
    fi
    BINDIR="/usr/local/bin"
    SUDO="sudo"
else
    echo "[!] Unsupported OS: $OS. See the manual steps in the README."
    exit 1
fi

echo "[*] Making the script executable..."
chmod +x "$SCRIPT"

echo "[*] Installing the 'acarsdecv2' command in $BINDIR ..."
# Deliberately NOT 'acarsdec': that name belongs to the reference decoder and
# would clash with it on machines where it is installed.
$SUDO ln -sf "$SCRIPT" "$BINDIR/acarsdecv2"
$SUDO ln -sf "$SCRIPT" "$BINDIR/acarsdec_v2"
$SUDO ln -sf "$SCRIPT" "$BINDIR/acarsdec_v2.py"

echo ""
echo "[OK] Installed. Try:"
echo "    acarsdecv2 --help"
echo "    acarsdecv2 helpfr               # help in French"
echo "    acarsdecv2 -f 131.525           # live listening on the RTL"
echo "    acarsdecv2 test.wav             # decode the sample (from this folder)"
echo "(zsh users: run 'rehash' or open a new terminal so the command is found)"
