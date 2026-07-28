#!/usr/bin/env python3
"""
acarsdec_v2.py - Standalone ACARS decoder (no acarsdec dependency).

Author : Boumediene Bahloul  -  LASSENA / ETS Montreal
Date   : July 13, 2026

Decodes classic ACARS (AM-MSK, 2400 baud, 1800 Hz subcarrier) from:
  - a raw IQ capture (rtl_sdr uint8, or complex64 from SoapySDR), or
  - a WAV of the AM-demodulated audio.

The MSK demodulator and ACARS framing state machine are ported from the acarsdec
f00b4r0 fork (msk.c / acars.c). Comments/identifiers in English.

Chain: IQ -> tune carrier to baseband -> resample to 12000 Hz -> AM envelope
detection -> MSK demod (VCO + matched filter + staggered I/Q) -> bits -> ACARS
frame (SYN SYN SOH ... ETX CRC) -> parity + CRC check -> message.

Usage:
  python3 acarsdec_v2.py capture.iq --format u8   --fs 1024000 --carrier 125000
  python3 acarsdec_v2.py capture.iq --format c64  --fs 1000000
  python3 acarsdec_v2.py audio.wav                                 # WAV of envelope
  python3 acarsdec_v2.py --freq 131.525 --gain 30                  # continuous RTL
"""

import sys
import os
import json
import math
import time
import select
import argparse
from datetime import datetime
import numpy as np

__version__ = "1.2"

# f00b4r0/acarsdec demod parameters (the fork that decodes our TX signal)
INTRATE = 12000
SUBCARRIER = 1800.0               # MSKFREQCNTR
MSKFREQSPACE = 1200.0
BITLEN = 10                       # CEILING(INTRATE, MSKFREQSPACE)
MFLTOVER = 240
MFLTLEN = BITLEN * MFLTOVER + 1   # 2401
PLLKi = 71e-7 / BITLEN
PLLKp = 60e-3 / BITLEN

SYN = 0x16
SOH = 0x01
STX = 0x02
ETX = 0x83
ETB = 0x97
DLE = 0x7f

# matched filter (half-sine), exactly as f00b4r0 msk.c
_H = np.array([np.sin(np.pi * MSKFREQSPACE * i / INTRATE / MFLTOVER)
               for i in range(MFLTLEN)])


def _crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if (c & 1) else (c >> 1)
        t.append(c & 0xFFFF)
    return t


_CRC_T = _crc_table()


def update_crc(crc, b):
    return ((crc >> 8) ^ _CRC_T[(crc ^ b) & 0xFF]) & 0xFFFF


class AcarsDemod:
    """MSK demodulator + ACARS framer. Feed AM-demodulated audio at INTRATE."""

    def __init__(self):
        self.MskClk = 0.0
        self.MskS = 0
        self.MskDf = 0.0
        self.MskDphi = 0.0
        self.MskPhi = 0.0    # VCO phase, persistent across feed() calls (streaming)
        self.idx = 0
        self.inb = np.zeros(BITLEN, dtype=np.complex128)
        self.outbits = 0
        self.nbits = 8
        self.state = "WSYN"
        self.txt = []
        self.crc = [0, 0]
        self.lvl_sum = 0.0    # signal level accumulation over the current block
        self.lvl_cnt = 0
        # Same quantity as lvl_* but never reset by a message, so live monitoring
        # can report the current level (i.e. the noise floor when nothing is on air)
        # on the very same dB scale as the L: shown on decoded messages.
        self.mon_sum = 0.0
        self.mon_cnt = 0
        self.messages = []   # list of dicts

    def monitor_level(self):
        """Mean level seen since the last call, in dB, on the same scale as the
        L: field of decoded messages. With nothing on air this is the noise
        floor, so a jump means a signal showed up. Resets the accumulator."""
        if not self.mon_cnt:
            return None
        lvl = 10.0 * math.log10(self.mon_sum / self.mon_cnt)
        self.mon_sum = 0.0
        self.mon_cnt = 0
        return lvl

    # --- ACARS byte-level state machine (acars.c) ---
    def _reset(self):
        self.state = "WSYN"
        self.MskDf = 0.0
        self.nbits = 1

    def _emit(self):
        crc = 0
        for b in self.txt:
            crc = update_crc(crc, b)
        crc = update_crc(crc, self.crc[0])
        crc = update_crc(crc, self.crc[1])
        perr = sum(1 for b in self.txt if bin(b).count("1") % 2 == 0)
        text = bytes(b & 0x7F for b in self.txt)
        level = 10.0 * math.log10(self.lvl_sum / self.lvl_cnt) if self.lvl_cnt else -99.0
        self.messages.append({
            "crc_ok": crc == 0,
            "parity_errors": perr,
            "text": text,
            "level": level,
            "time": datetime.now(),
        })

    def _decode_byte(self):
        r = self.outbits & 0xFF
        st = self.state
        if st == "WSYN":
            if r == SYN:
                self.state = "SYN2"; self.nbits = 8; return
            if r == (~SYN & 0xFF):
                self.MskS ^= 2; self.state = "SYN2"; self.nbits = 8; return
            self.nbits = 1; return
        if st == "SYN2":
            if r == SYN:
                self.state = "SOH1"; self.nbits = 8; return
            if r == (~SYN & 0xFF):
                self.MskS ^= 2; self.nbits = 8; return
            self._reset(); return
        if st == "SOH1":
            if r == SOH:
                self.state = "TXT"; self.txt = []; self.nbits = 8
                self.lvl_sum = 0.0; self.lvl_cnt = 0
                return
            self._reset(); return
        if st == "TXT":
            self.txt.append(r)
            if r == ETX or r == ETB:
                self.state = "CRC1"; self.nbits = 8; return
            if len(self.txt) > 240:
                self._reset(); return
            self.nbits = 8; return
        if st == "CRC1":
            self.crc[0] = r; self.state = "CRC2"; self.nbits = 8; return
        if st == "CRC2":
            self.crc[1] = r; self._emit()
            self.state = "END"; self.nbits = 8; return
        if st == "END":
            self._reset(); self.nbits = 8; return

    def _putbit(self, v):
        self.outbits = (self.outbits >> 1) | (0x80 if v > 0 else 0)
        self.nbits -= 1
        if self.nbits <= 0:
            self._decode_byte()

    # --- MSK demod (f00b4r0 msk.c) ---
    def feed(self, audio):
        p = self.MskPhi
        two_pi = 2.0 * np.pi
        threehalfpi = 3.0 * np.pi / 2.0
        for n in range(len(audio)):
            s = SUBCARRIER / INTRATE * two_pi + self.MskDphi

            self.MskClk += s
            if self.MskClk > threehalfpi:
                self.MskClk -= threehalfpi
                o = int(MFLTOVER * (self.MskClk / s))
                if o > MFLTOVER:
                    o = MFLTOVER
                v = 0j
                for j in range(BITLEN):
                    v += _H[o + j * MFLTOVER] * self.inb[(j + self.idx) % BITLEN]
                lvl = abs(v) + 1e-8
                v /= lvl
                self.lvl_sum += lvl * lvl
                self.lvl_cnt += 1
                self.mon_sum += lvl * lvl
                self.mon_cnt += 1
                if self.MskS & 1:
                    vo = v.imag
                    dphi = (-v.real) if vo >= 0 else v.real
                else:
                    vo = v.real
                    dphi = (v.imag) if vo >= 0 else -v.imag
                self._putbit(-vo if (self.MskS & 2) else vo)
                self.MskS += 1
                # PLL as a PI controller (always tracking here)
                self.MskDf += PLLKi * dphi
                self.MskDphi = self.MskDf + PLLKp * dphi

            # VCO + mixer
            p += s
            if p >= two_pi:
                p -= two_pi
            self.inb[self.idx] = audio[n] * np.exp(-1j * p)
            self.idx = (self.idx + 1) % BITLEN
        self.MskPhi = p


# ---------------------------------------------------------------------------
# Front-end: IQ capture -> AM envelope audio at INTRATE
# ---------------------------------------------------------------------------

def iq_to_audio(iq, fs, carrier_hz=None):
    """Tune the ACARS carrier to DC, resample the complex baseband down to
    INTRATE (the resampler's anti-alias rejects the LO leak / adjacent signals),
    then AM envelope-detect. Resampling the complex signal *before* enveloping is
    what keeps the demod happy (a wide low-pass before enveloping breaks it)."""
    from scipy.signal import resample_poly
    from math import gcd
    iq = np.asarray(iq, dtype=np.complex128)
    if len(iq) < 64:
        return np.zeros(0, dtype=np.float64)
    iq = iq - np.mean(iq)
    if carrier_hz is None:
        n = min(1 << 19, len(iq))
        seg = iq[:n] * np.hanning(n)
        S = np.abs(np.fft.fftshift(np.fft.fft(seg)))
        f = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
        mask = np.abs(f) > 25000          # skip the receiver DC spike
        carrier_hz = f[np.argmax(S * mask)]
        print("[rx] carrier auto-detected at %.1f kHz" % (carrier_hz / 1e3))
    t = np.arange(len(iq)) / fs
    bb = iq * np.exp(-2j * np.pi * carrier_hz * t)
    g = gcd(int(fs), INTRATE)
    bb = resample_poly(bb, INTRATE // g, int(fs) // g)   # complex -> INTRATE
    env = np.abs(bb)
    env = env - np.mean(env)
    return env.astype(np.float64)


def _with_leadin(audio, seconds=0.12):
    """The demod PLL needs silence before the signal to settle."""
    pad = np.zeros(int(INTRATE * seconds))
    return np.concatenate([pad, audio, pad])


def load_iq(path, fmt):
    if fmt == "u8":
        raw = np.fromfile(path, dtype=np.uint8).astype(np.float32)
        n = len(raw) // 2
        return (raw[0:2 * n:2] - 127.5) + 1j * (raw[1:2 * n:2] - 127.5)
    if fmt == "c64":
        return np.fromfile(path, dtype=np.complex64)
    raise ValueError("unknown format: %s" % fmt)


class LiveFrontend:
    """Continuous IQ -> AM-envelope audio at INTRATE, with state kept across
    chunks (mixer phase, anti-alias filter, DC blocker) so a persistent demod
    can be fed sample-by-sample forever."""

    def __init__(self, fs_in, offset_hz):
        from scipy.signal import firwin
        assert fs_in % INTRATE == 0, "fs_in must be a multiple of %d" % INTRATE
        self.fs_in = int(fs_in)
        self.decim = int(fs_in) // INTRATE
        self.offset = offset_hz
        self.taps = firwin(129, 6000.0 / (fs_in / 2))
        self.zi = np.zeros(len(self.taps) - 1, dtype=np.complex128)
        self.phase = 0.0
        self.w = 2.0 * np.pi * offset_hz / fs_in
        # DC blocker (one-pole high-pass) state, at INTRATE
        self.dc_a = 0.999
        self.dc_zi = np.zeros(1)

    def process(self, iq_chunk):
        from scipy.signal import lfilter
        n = len(iq_chunk)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        ph = self.phase + self.w * np.arange(n)
        self.phase = (self.phase + self.w * n) % (2.0 * np.pi)
        bb = iq_chunk * np.exp(-1j * ph)
        bb, self.zi = lfilter(self.taps, [1.0], bb, zi=self.zi)
        bb = bb[::self.decim]
        env = np.abs(bb)
        # DC blocker: y = x - x[-1] + a*y[-1]
        out, self.dc_zi = lfilter([1.0, -1.0], [1.0, -self.dc_a], env, zi=self.dc_zi)
        return out.astype(np.float64)


# RTL sample rates that are multiples of INTRATE (12000) and valid for the dongle
_RTL_RATES = [240000, 288000, 960000, 1200000, 1440000, 1920000, 2400000, 2880000]


def _choose_rtl_fs(max_offset_hz):
    need = 2.2 * max_offset_hz
    for r in _RTL_RATES:
        if r >= need:
            return r
    return _RTL_RATES[-1]


# Getting no data at all for this long means the RTL stopped feeding us. It
# usually stays alive while doing so, so a plain read() waits forever.
STALL_SECONDS = 30
MAX_RESTARTS = 5
# A stream that ran this long before dying counts as a fresh incident rather
# than one more failed retry, so an overnight capture keeps its full budget
# every time, while a dongle dying right after each restart still gives up.
HEALTHY_SECONDS = 30


def _note(text, logpath=None):
    """Timestamped operational note, on screen and in the --log. Without it an
    interrupted capture just stops, and nothing says it was not the end."""
    line = "[rx] %s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text)
    print(line)
    if logpath:
        try:
            with open(logpath, "a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


def _read_exact(fd, n, stall_after):
    """Read exactly n bytes from the RTL pipe.

    Returns the bytes, or b'' if the pipe closed (rtl_sdr exited), or None if
    nothing arrived for stall_after seconds (rtl_sdr still alive but no longer
    sending). A plain read() cannot tell those two apart: it just blocks.
    """
    buf = bytearray()
    last = time.monotonic()
    while len(buf) < n:
        ready, _, _ = select.select([fd], [], [], 1.0)
        if ready:
            data = os.read(fd, n - len(buf))
            if not data:
                return b""
            buf += data
            last = time.monotonic()
        elif time.monotonic() - last > stall_after:
            return None
    return bytes(buf)


def live(freqs_hz, gain, ppm=0, verbose=False, logpath=None, save=None,
         fmt="full", station=None, only_labels=None, skip_empty=False,
         downlink_only=False):
    """Continuous multi-channel ACARS listen on one RTL-SDR."""
    import subprocess
    freqs = sorted(set(int(round(f)) for f in freqs_hz))
    center = freqs[0] - 50000               # keep the carrier well clear of the RTL DC spike
    offsets = [f - center for f in freqs]
    fs_in = _choose_rtl_fs(max(offsets))
    chans = []
    for f, off in zip(freqs, offsets):
        fe = LiveFrontend(fs_in, off)
        dm = AcarsDemod()
        dm.feed(np.zeros(int(INTRATE * 0.15)))      # lead-in so the PLL settles
        chans.append((f, fe, dm))
    cmd = ["rtl_sdr", "-f", str(center), "-s", str(fs_in), "-g", str(gain)]
    if ppm:
        cmd += ["-p", str(ppm)]
    cmd += ["-"]
    print("acarsdecv2 v%s - ACARS decoder (LASSENA / ETS)  by Boumediene Bahloul" % __version__)
    print("[rx] listening on %s MHz  (RTL %.4f @ %d S/s, gain %s%s)"
          % (", ".join("%.3f" % (f / 1e6) for f in freqs), center / 1e6, fs_in,
             gain, ", ppm %d" % ppm if ppm else ""))
    print("[rx] Ctrl+C to stop. Waiting for messages...")
    import threading

    def _relay(pipe):                 # relay the RTL's own messages (device, tuner, errors)
        for line in iter(pipe.readline, b""):
            txt = line.decode("utf-8", "replace").rstrip()
            if txt:
                print("[rtl] " + txt)

    def _start():
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        threading.Thread(target=_relay, args=(proc.stderr,), daemon=True).start()
        return proc

    def _stop(proc):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    try:
        p = _start()
    except FileNotFoundError:
        print("[rx] 'rtl_sdr' not found. Install the rtl-sdr tools (see README).")
        return 1

    chunk_bytes = int(fs_in * 0.25) * 2
    fsave = open(save, "wb") if save else None
    count = 0
    chunks = 0
    rc = 0
    ever_data = False      # any data at all so far, i.e. the dongle does work
    consecutive = 0        # failed restarts that did not stay up long enough
    stream_since = None    # when the current rtl_sdr started delivering
    last_data = 0.0        # when it last actually delivered
    resumed = False        # a restart happened, announce the first data back
    try:
        while True:
            raw = _read_exact(p.stdout.fileno(), chunk_bytes, STALL_SECONDS)
            if raw is None or raw == b"":
                # Either the RTL went quiet while staying alive (None) or its
                # process is gone (b''). Both used to end the capture without a
                # word: read() blocked forever on the first, and the loop broke
                # silently on the second.
                why = ("the RTL stopped sending data (rtl_sdr still running)"
                       if raw is None else "rtl_sdr exited")
                if not ever_data:
                    p.wait()
                    print("[rx] No data from the RTL-SDR. Is it plugged in and free? "
                          "(check the [rtl] lines above)")
                    rc = 1
                    break
                # how long it actually delivered, not counting the silence we
                # just waited through, so a stream that dies at once is not
                # mistaken for a healthy one
                lasted = last_data - stream_since if stream_since else 0.0
                consecutive = 1 if lasted >= HEALTHY_SECONDS else consecutive + 1
                stream_since = None
                if consecutive > MAX_RESTARTS:
                    _note("%s. Gave up after %d attempts, %d message(s) received."
                          % (why, MAX_RESTARTS, count), logpath)
                    rc = 1
                    break
                _note("%s after %ds. Restarting it (%d/%d), %d message(s) so far."
                      % (why, lasted, consecutive, MAX_RESTARTS, count), logpath)
                _stop(p)
                time.sleep(2)          # let the USB settle before reopening
                try:
                    p = _start()
                except FileNotFoundError:
                    print("[rx] 'rtl_sdr' not found. Install the rtl-sdr tools "
                          "(see README).")
                    rc = 1
                    break
                resumed = True
                continue
            if resumed:
                _note("RTL back, capture continues.", logpath)
                resumed = False
            if stream_since is None:
                stream_since = time.monotonic()
            last_data = time.monotonic()
            ever_data = True
            if fsave:
                fsave.write(raw)
            b = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
            m = len(b) // 2
            iq = (b[0:2 * m:2] - 127.5) + 1j * (b[1:2 * m:2] - 127.5)
            for f, fe, dm in chans:
                audio = fe.process(iq)
                before = len(dm.messages)
                dm.feed(audio)
                for msg in dm.messages[before:]:
                    msg["freq"] = f
                    if keep_message(msg, only_labels, skip_empty, downlink_only):
                        count += 1
                        emit_message(msg, fmt=fmt, station=station, logpath=logpath)
            if verbose:
                chunks += 1
                if chunks % 16 == 0:        # ~ every 4 s
                    # Current level per channel, same dB scale as the L: of a
                    # decoded message. Flat value = noise floor (nothing on air);
                    # a jump means a signal is present.
                    lv = []
                    for f, fe, dm in chans:
                        db = dm.monitor_level()
                        lv.append("%.3f: %s" % (f / 1e6,
                                  "%+.1f dB" % db if db is not None else "n/a"))
                    print("[rx] %d message(s) | level %s" % (count, "  ".join(lv)))
    except KeyboardInterrupt:
        print("\n[rx] stopped. %d message(s) received." % count)
    finally:
        _stop(p)
        if fsave:
            fsave.close()
    return rc


def parse_acars(txt):
    """Split a decoded ACARS block (parity already stripped) into fields."""
    if len(txt) < 13:
        return None
    mode = chr(txt[0]) if 32 <= txt[0] < 127 else "?"
    addr = txt[1:8].decode("ascii", "replace").replace(".", "").strip()
    tak = txt[8]
    ack = {0x15: "NAK", 0x06: "ACK"}.get(tak, "0x%02x" % tak)
    label = txt[9:11].decode("ascii", "replace")
    blk = chr(txt[11]) if 32 <= txt[11] < 127 else "."
    body = txt[12:]
    if body[:1] == b"\x02":            # strip STX
        body = body[1:]
    if body[-1:] in (b"\x03", b"\x97"):  # strip ETX / ETB
        body = body[:-1]
    text = body.decode("ascii", "replace")
    return {"mode": mode, "addr": addr, "ack": ack, "label": label, "blk": blk, "text": text}


def acars_direction(f):
    """Best-effort uplink/downlink. Downlink (aircraft -> ground) blocks usually
    carry a 4-char message number + 6-char flight id at the start of the text."""
    t = f["text"]
    if len(t) >= 10 and t[0].isalnum() and t[4:10].strip():
        return "down"
    return "up"


def keep_message(m, only_labels=None, skip_empty=False, downlink_only=False):
    f = parse_acars(m["text"])
    if f is None:
        return not (only_labels or skip_empty or downlink_only)
    if only_labels and f["label"].strip() not in only_labels:
        return False
    if skip_empty and not f["text"].strip():
        return False
    if downlink_only and acars_direction(f) != "down":
        return False
    return True


def render_message(m, fmt="full", station=None):
    ts = m.get("time") or datetime.now()
    f = parse_acars(m["text"])
    freq = m.get("freq")
    lvl = m.get("level", -99.0)

    if fmt == "json":
        d = {"time": ts.strftime("%Y-%m-%dT%H:%M:%S"), "station": station,
             "freq_mhz": round(freq / 1e6, 3) if freq else None,
             "level": round(lvl, 1), "crc_ok": m["crc_ok"],
             "parity_errors": m["parity_errors"]}
        if f:
            d.update(mode=f["mode"], reg=f["addr"], label=f["label"],
                     block=f["blk"], ack=f["ack"],
                     direction=acars_direction(f), text=f["text"])
        else:
            d["raw"] = m["text"].decode("ascii", "replace")
        return json.dumps(d, ensure_ascii=False)

    if fmt == "line":
        fp = "%.3f " % (freq / 1e6) if freq else ""
        crc = "OK  " if m["crc_ok"] else "CRC!"
        if f:
            return "%s %s%s %s %-7s %-2s L:%+.0f  %s" % (
                ts.strftime("%H:%M:%S"), fp, crc, f["mode"], f["addr"],
                f["label"], lvl, f["text"])
        return "%s %s%s %r" % (ts.strftime("%H:%M:%S"), fp, crc,
                               m["text"].decode("ascii", "replace"))

    # full (default), acarsdec-style
    freq_s = "  %.3f MHz" % (freq / 1e6) if freq else ""
    st = "  [%s]" % station if station else ""
    crc = "" if m["crc_ok"] else "  [CRC ERROR]"
    lines = ["--------------------------------------------------",
             "%s%s  (L:%+.1f dB  err:%d)%s%s"
             % (ts.strftime("%Y-%m-%d %H:%M:%S"), freq_s, lvl,
                m["parity_errors"], crc, st)]
    if f:
        lines.append("Mode : %s   Label : %-2s   Id : %s   %s"
                     % (f["mode"], f["label"], f["blk"], f["ack"]))
        lines.append("Aircraft reg: %s" % f["addr"])
        lines.append("Text: %s" % f["text"])
    else:
        lines.append("Raw: %r" % m["text"].decode("ascii", "replace"))
    return "\n".join(lines)


def emit_message(m, fmt="full", station=None, logpath=None):
    print(render_message(m, fmt, station))
    if logpath:
        try:
            with open(logpath, "a") as fh:
                fh.write(render_message(m, fmt, station) + "\n")
        except OSError as exc:
            print("[rx] log warning: %s" % exc)


def print_messages(dm, logpath=None, fmt="full", station=None,
                   only_labels=None, skip_empty=False, downlink_only=False):
    shown = 0
    for m in dm.messages:
        if keep_message(m, only_labels, skip_empty, downlink_only):
            emit_message(m, fmt=fmt, station=station, logpath=logpath)
            shown += 1
    if shown == 0:
        print("[rx] no message decoded")


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Align help text, keep the epilog raw, and compact 'nargs=+' metavars."""
    def __init__(self, prog):
        super().__init__(prog, max_help_position=30, width=96)

    def _format_args(self, action, default_metavar):
        get = self._metavar_formatter(action, default_metavar)
        if action.nargs == "+":
            return "%s..." % get(1)
        return super()._format_args(action, default_metavar)


HELP_FR = """acarsdecv2 v{v} - Decodeur ACARS autonome (sans acarsdec, macOS / Linux)

UTILISATION
  acarsdec_v2 -f <MHz> [options]        ecoute en direct sur la RTL-SDR
  acarsdec_v2 <fichier> [options]       decode un fichier deja enregistre
  acarsdec_v2                           affiche l aide (anglais)
  acarsdec_v2 helpfr                    affiche cette aide (francais)

ECOUTE EN DIRECT (mode par defaut des qu on donne -f)
  -f, --freq <MHz> [...]   frequence(s) a ecouter, en MHz. Plusieurs frequences
                           possibles si elles sont proches (moins de ~2 MHz d ecart),
                           sinon elles sortent de la bande echantillonnee par la RTL.
  -g, --gain <dB>          gain du tuner. ~30 pour un signal fort (cable direct),
                           40 a 49.6 pour du trafic reel capte a l antenne.
      --ppm <n>            correction d horloge de la RTL, en ppm.
      --save <fichier.iq>  enregistre aussi les echantillons IQ bruts recus.

DECODAGE D UN FICHIER
  <fichier>                .wav (audio d enveloppe) ou .iq (echantillons bruts)
      --format u8|c64      format des echantillons du .iq (u8 = rtl_sdr, defaut)
      --fs <Hz>            frequence d echantillonnage du .iq
      --carrier <Hz>       position de la porteuse dans la capture (defaut : auto)

AFFICHAGE ET FILTRES
      --fmt full|line|json format de sortie (defaut : full)
  -b, --labels <A:B:...>   n afficher que ces labels ACARS
  -e, --skip-empty         masquer les messages sans texte
  -A, --downlink-only      ne garder que les liaisons descendantes (approximatif)
  -i, --station <nom>      identifiant de station affiche dans la sortie
  -v, --verbose            afficher periodiquement l etat de reception (niveau)

ENREGISTREMENT
      --log                DESACTIVE par defaut. Utilise seul, cree un fichier
                           horodate a cote du script : acars_AAAA-MM-JJ_HH-MM-SS.txt
      --log <fichier>      ecrit dans le fichier indique.

      Ou va le fichier : --log seul ecrit TOUJOURS dans le dossier du script
      (acarsdec_v2/), peu importe d ou tu lances la commande. Pour choisir
      l endroit, donne un chemin : --log ~/Bureau/toit.txt

      Important : --log n enregistre QUE les messages decodes. Pour capturer
      TOUT ce qui s affiche a l ecran (banniere, lignes [rtl], erreurs), utilise
      'tee' (voir la section suivante).

LIRE LE NIVEAU (L: et -v)
  Le niveau est en dB RELATIFS, pas en dBm : seules les comparaisons comptent.
  Mesure sur notre banc : +25 dB fort, +10 dB decode encore proprement,
  +3 dB le CRC commence a casser, -14 dB c est du bruit pur.
  Avec -v, ce qui compte c est le SAUT : une valeur qui ne bouge jamais veut
  dire que tu ne recois rien (mauvaise frequence, antenne ou gain).

A PROPOS DE 'tee'
  'tee' est une commande DU SHELL, pas une option de cet outil. Elle affiche a
  l ecran ET ecrit dans un fichier en meme temps. Il lui faut DEUX choses :
      1. le tube '|' avant elle : c est lui qui lui envoie la sortie ;
      2. un NOM DE FICHIER apres elle.
  'tee' tout seul, sans nom de fichier, n enregistre RIEN : il se contente de
  recopier a l ecran. Exemples :
      acarsdecv2 -f 131.550 | tee sortie.txt        ecran + fichier
      acarsdecv2 -f 131.550 | tee -a sortie.txt     ajoute au lieu d ecraser
      acarsdecv2 -f 131.550 2>&1 | tee sortie.txt   capture aussi les erreurs
  Attention : sans '-a', 'tee' ECRASE le fichier a chaque lancement.
  Difference avec --log : --log ne garde que les messages ACARS decodes,
  'tee' garde tout ce que tu vois a l ecran.

FREQUENCES ACARS
  Amerique du Nord (Montreal) : 131.550 (principale), 130.025, 130.450, 129.125
  Europe                      : 131.725, 131.525
  Banc de test RFSoC          : celle reglee dans la GUI (131.525 ou 136.950)
  Astuce : plusieurs frequences a la fois seulement si elles sont proches
  (moins de ~2 MHz d ecart), sinon elles sortent de la bande de la RTL.

SI LA RTL LACHE EN COURS DE CAPTURE
  Deux pannes possibles : le processus rtl_sdr se termine, ou il reste vivant
  mais n envoie plus rien (blocage USB). Les deux sont detectees, annoncees
  avec l heure a l ecran ET dans le --log, et la RTL est relancee toute seule :
      [rx] 2026-07-28 10:09:37  the RTL stopped sending data ... Restarting it (1/5)
      [rx] 2026-07-28 10:09:39  RTL back, capture continues.
  Abandon apres 5 echecs de suite, avec un code de retour 1 au lieu de 0. Un
  flux qui a tenu au moins 30 s compte comme un incident neuf, donc un simple
  hoquet USB ne consomme pas le quota.

SI L AFFICHAGE SE FIGE MAIS QUE LE PROGRAMME TOURNE
  Si les lignes [rx] ... level s arretent net alors que tout va bien par
  ailleurs, c est le TERMINAL qui bloque, pas le decodeur. Son tampon ne fait
  que 1 Ko sur macOS : des qu il cesse d etre vide (un Ctrl+S parti tout seul
  est la cause habituelle), le decodeur se bloque en moins d une minute.
  Appuie sur Ctrl+Q : tout redefile d un coup, rien n est perdu.
  Pour l eviter, garde le decodeur hors du terminal :
      acarsdecv2 -f 131.550 -g 40 -v --log > ~/Bureau/sortie.txt 2>&1 &
      tail -f ~/Bureau/sortie.txt
  Seul le tail peut se figer, la capture continue.

EXEMPLES
  Ecoute en direct
    acarsdecv2 -f 131.550 -g 49.6              vrais avions (Montreal)
    acarsdecv2 -f 131.525 -g 30                banc RFSoC (cable direct)
    acarsdecv2 -f 130.025 130.450 131.550      plusieurs canaux a la fois
    acarsdecv2 -f 131.550 -v                   afficher l etat de reception
  Enregistrement
    acarsdecv2 -f 131.550 --log                fichier horodate dans acarsdec_v2/
    acarsdecv2 -f 131.550 --log ~/Bureau/toit.txt       choisir le fichier
    acarsdecv2 -f 131.550 --log /tmp/logs/essai1.txt    n importe quel chemin
    acarsdecv2 -f 131.550 | tee tout.txt       toute la sortie ecran (tee = shell)
    acarsdecv2 -f 131.550 --save capture.iq    enregistrer aussi l IQ brut
  Format et filtres
    acarsdecv2 -f 131.550 --fmt line           une ligne par message
    acarsdecv2 -f 131.550 --fmt json -i LASSENA1
    acarsdecv2 -f 131.550 -b 14:H1 -e          seulement labels 14/H1, sans les vides
  Decodage d un fichier
    acarsdecv2 capture.iq --format u8 --fs 1050000
    acarsdecv2 enregistrement.wav

COMPRENDRE UNE LIGNE DE RESULTAT
  2026-07-23 16:00:36  136.950 MHz  (L:+29.4 dB  err:0)
    L    = niveau du signal. Positif et eleve = bon. Negatif = bruit.
    err  = nombre d erreurs de parite. 0 = propre.
    [CRC ERROR] = trame rejetee par le CRC : ce n est PAS un vrai message.

Auteur : Boumediene Bahloul - LASSENA / ETS Montreal
""".format(v=__version__)


def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("helpfr", "--helpfr", "-helpfr", "aide"):
        print(HELP_FR)
        return
    p = argparse.ArgumentParser(
        # follow whichever name it was invoked as: acarsdec, acarsdec_v2, ...
        prog=os.path.basename(sys.argv[0]) or "acarsdec",
        description="Standalone ACARS decoder %s (no acarsdec, Mac/Linux).\n"
                    "Listens live on an RTL-SDR, or decodes an IQ capture / a WAV." % __version__,
        formatter_class=_HelpFormatter,
        epilog="EXAMPLES\n"
               "  Live listening\n"
               "    acarsdecv2 -f 131.550 -g 49.6              real aircraft (North America)\n"
               "    acarsdecv2 -f 131.525 -g 30                RFSoC bench (direct cable)\n"
               "    acarsdecv2 -f 130.025 130.450 131.550      several channels at once\n"
               "    acarsdecv2 -f 131.550 -v                   show reception status\n"
               "  Saving\n"
               "    acarsdecv2 -f 131.550 --log                timestamped file next to the script\n"
               "    acarsdecv2 -f 131.550 --log ~/Desktop/roof.txt      choose the file/folder\n"
               "    acarsdecv2 -f 131.550 --log /tmp/logs/run1.txt      any path works\n"
               "    acarsdecv2 -f 131.550 | tee all.txt        everything on screen (see note)\n"
               "    acarsdecv2 -f 131.550 | tee -a all.txt     append instead of overwriting\n"
               "    acarsdecv2 -f 131.550 2>&1 | tee all.txt   capture errors too\n"
               "    acarsdecv2 -f 131.550 --save capture.iq    also record the raw IQ\n"
               "  Output format and filters\n"
               "    acarsdecv2 -f 131.550 --fmt line           one line per message\n"
               "    acarsdecv2 -f 131.550 --fmt json -i LASSENA1\n"
               "    acarsdecv2 -f 131.550 -b 14:H1 -e          only labels 14/H1, hide empty\n"
               "  Decoding a file\n"
               "    acarsdecv2 capture.iq --format u8 --fs 1050000\n"
               "    acarsdecv2 recording.wav\n"
               "  Help\n"
               "    acarsdecv2 helpfr                          full help in French\n"
               "\nREADING THE LEVEL (L: and -v)\n"
               "  Relative dB, not dBm: only comparisons matter. As measured on this\n"
               "  setup: +25 dB strong, +10 dB still decodes cleanly, +3 dB the CRC\n"
               "  starts failing, -14 dB is pure noise. With -v, watch for the JUMP:\n"
               "  a value that never moves means nothing is being received.\n"
               "\nABOUT tee\n"
               "  tee is a shell command, not an option of this tool. It needs BOTH:\n"
               "    - the pipe '|' before it (that is what feeds it the output), and\n"
               "    - a file name after it. 'tee' alone saves nothing, it just echoes.\n"
               "  It overwrites by default; use 'tee -a' to append. Put '2>&1' before\n"
               "  the pipe to capture error messages as well.\n"
               "  Difference with --log: --log stores only decoded ACARS messages,\n"
               "  tee stores everything you see on screen (banner, [rtl] lines, errors).\n"
               "\nACARS CHANNELS\n"
               "  North America (Montreal) : 131.550 (main), 130.025, 130.450, 129.125\n"
               "  Europe                   : 131.725, 131.525\n"
               "  RFSoC test bench         : whatever the GUI is set to (131.525 / 136.950)\n"
               "\nGive -f <MHz> to listen live on the RTL; a bare command shows this help.\n"
               "-f and --freq are equivalent. Logging is OFF unless you pass --log.\n")
    p.add_argument("input", nargs="?", help="IQ capture (.iq) or envelope WAV (.wav)")
    # live listening (default when no file; RTL via rtl_sdr)
    g_live = p.add_argument_group("live listening (default when no file)")
    g_live.add_argument("--live", action="store_true",
                        help="force live listening (already the default without a file)")
    g_live.add_argument("-f", "--freq", type=float, nargs="+", default=[131.550], metavar="MHz",
                        help="listening frequency in MHz, several allowed (default 131.550)")
    g_live.add_argument("-g", "--gain", default="30", help="RTL gain in dB (default 30)")
    g_live.add_argument("--ppm", type=int, default=0,
                        help="RTL frequency correction in ppm (default 0)")
    g_live.add_argument("--save", default=None, help="also save the raw received IQ to this file")
    # file mode (IQ capture or WAV)
    g_file = p.add_argument_group("file decoding")
    g_file.add_argument("--format", choices=["u8", "c64"], default="u8",
                        help="IQ capture format: u8 (rtl_sdr) or c64 (SoapySDR)")
    g_file.add_argument("--fs", type=float, default=1024000.0,
                        help="IQ capture sample rate (default 1024000)")
    g_file.add_argument("--carrier", type=float, default=None,
                        help="carrier offset in Hz within the capture (default: auto)")
    # output and filters
    g_out = p.add_argument_group("output and filters")
    g_out.add_argument("--fmt", choices=["full", "line", "json"], default="full",
                       help="output format (default full)")
    g_out.add_argument("-b", "--labels", default=None, metavar="L1,L2",
                       help="keep only these labels (e.g. H1,Q0)")
    g_out.add_argument("-e", "--skip-empty", action="store_true",
                       help="hide messages with no text")
    g_out.add_argument("-A", "--downlink-only", action="store_true",
                       help="keep only aircraft-to-ground messages (approx.)")
    g_out.add_argument("-i", "--station", default=None,
                       help="station id (shown in full/json)")
    # common
    p.add_argument("-v", "--verbose", action="store_true",
                   help="every ~4 s, print the current signal level per channel, on the same dB scale as the L: of a decoded message. Flat value = noise floor (nothing on air); a jump = a signal is present. Relative dB, not dBm: compare values, not absolutes.")
    p.add_argument("--log", nargs="?", const="AUTO", default=None, metavar="FILE",
                   help="save decoded messages to a file. OFF by default. "
                        "Bare --log creates acars_<YYYY-MM-DD_HH-MM-SS>.txt next to "
                        "the script, wherever you run the command from; --log FILE "
                        "writes to FILE (any path). Saves decoded messages only: to "
                        "capture everything printed on screen, pipe through 'tee' "
                        "(see the tee note under EXAMPLES).")
    p.add_argument("--bovmii", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args()

    if len(sys.argv) == 1:      # bare command -> show the help
        p.print_help()
        return

    if getattr(args, "bovmii", False):
        print("bovmii // ACARS decoder handcrafted by Boumediene Bahloul (LASSENA / ETS)")
        return

    logpath = args.log
    if logpath == "AUTO":        # bare --log : timestamped file next to the script
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        # realpath, not abspath: the command is usually reached through a symlink
        # in the PATH, and abspath would drop the log next to that symlink.
        logpath = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                               "acars_%s.txt" % stamp)
        print("[rx] logging messages to %s" % logpath)
    labels = None
    if args.labels:
        labels = set(x for x in args.labels.replace(",", ":").split(":") if x)
    filt = dict(only_labels=labels, skip_empty=args.skip_empty,
                downlink_only=args.downlink_only)

    # live listening is the default whenever no file is given
    if args.live or not args.input:
        return live([f * 1e6 for f in args.freq], args.gain, ppm=args.ppm,
                    verbose=args.verbose, logpath=logpath, save=args.save,
                    fmt=args.fmt, station=args.station, **filt)

    if args.input.lower().endswith(".wav"):
        from scipy.io import wavfile
        from scipy.signal import resample_poly
        from math import gcd
        rate, data = wavfile.read(args.input)
        channels = [data] if data.ndim == 1 else [data[:, c] for c in range(data.shape[1])]
        # try every channel; ACARS audio may be on any of them
        for ci, ch in enumerate(channels):
            audio = ch.astype(np.float64)
            audio = audio - np.mean(audio)
            if rate != INTRATE:
                g = gcd(int(rate), INTRATE)
                audio = resample_poly(audio, INTRATE // g, int(rate) // g)
            dm = AcarsDemod()
            dm.feed(_with_leadin(audio))
            if dm.messages:
                if len(channels) > 1:
                    print("[rx] channel %d:" % ci)
                print_messages(dm, logpath, fmt=args.fmt, station=args.station, **filt)
                return
        print("[rx] no message decoded (across %d channel(s))" % len(channels))
    else:
        iq = load_iq(args.input, args.format)
        audio = iq_to_audio(iq, args.fs, args.carrier)
        dm = AcarsDemod()
        dm.feed(_with_leadin(audio))
        print_messages(dm, logpath, fmt=args.fmt, station=args.station, **filt)


if __name__ == "__main__":
    sys.exit(main())
