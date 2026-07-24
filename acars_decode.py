#!/usr/bin/env python3
"""
acars_decode.py - decodeur ACARS autonome (terminal, sans interface).

Recoit avec un RTL-SDR ou un bladeRF (auto-detection via SoapySDR), demodule
l'AM-MSK 2400 bauds et affiche les messages ACARS decodes.

Portage Python de l'algo eprouve d'acarsdec (T. Leconte) : demod MSK avec PLL
sur la sous-porteuse 1800 Hz, horloge bit derivee de la sous-porteuse, filtre
adapte demi-cosinus, decision I/Q decalee (OQPSK), puis machine d'etats de
deframe (SYN SYN SOH ... ETX CRC), parite impaire par caractere, CRC CCITT
reflechi (poly 0x8408).

Dependances : numpy, scipy, SoapySDR (binding Python).
  Mac   : brew install soapysdr ; pip3 install numpy scipy ; (binding SoapySDR
          via le paquet python de soapysdr)
  Linux : sudo apt install python3-soapysdr python3-numpy python3-scipy
          + le module du peripherique (soapysdr-module-rtlsdr / -bladerf)

Exemples :
  python3 acars_decode.py 131.525
  python3 acars_decode.py --device bladerf --gain 20 131.525 131.725
  python3 acars_decode.py --device rtlsdr  --gain 40 131.550

Le materiel est detecte tout seul : si rien n'est precise, prend le premier
bladeRF ou RTL-SDR trouve.
"""

import sys
import time
import math
import cmath
import argparse
import datetime

try:
    import numpy as np
    from scipy.signal import firwin, lfilter
except ImportError as e:
    sys.exit(f"Manque numpy/scipy : {e}\n  pip3 install numpy scipy")

# SoapySDR est importe paresseusement (seulement pour le live SDR), pour que le
# mode --file (rejeu d'une capture) tourne sans SoapySDR (numpy/scipy suffisent).

# ----------------------------------------------------------------------------
# Constantes ACARS (identiques a acarsdec)
# ----------------------------------------------------------------------------
INTRATE = 12500           # audio/working sample rate (Hz)
BAUD = 2400
SUBCARRIER = 1800.0       # MSK subcarrier (Hz)

SYN = 0x16
SOH = 0x01
STX = 0x02
ETX = 0x83                # 0x03 + odd parity bit
ETB = 0x97                # 0x17 + odd parity bit
DLE = 0x7f

# MSK matched filter (half cosine at 600 Hz), oversampled (cf. msk.c)
FLEN = (INTRATE // 1200) + 1      # 11
MFLTOVER = 12
FLENO = FLEN * MFLTOVER + 1       # 133

PLLG = 38e-4
PLLC = 0.52


def _build_matched_filter():
    h = np.zeros(FLENO, dtype=np.float64)
    for i in range(FLENO):
        v = math.cos(2.0 * math.pi * 600.0 / INTRATE / MFLTOVER * (i - (FLENO - 1) / 2))
        h[i] = v if v > 0 else 0.0
    return h


def _build_crc_table():
    # reflected CRC-CCITT, polynomial 0x8408 (cf. acarsdec syndrom.h)
    table = [0] * 256
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if (c & 1) else (c >> 1)
        table[i] = c
    return table


CRC_TABLE = _build_crc_table()
NUMBITS = [bin(i).count("1") for i in range(256)]
HMF = _build_matched_filter()


def update_crc(crc, c):
    return (crc >> 8) ^ CRC_TABLE[(crc ^ c) & 0xff]


# ----------------------------------------------------------------------------
# Demodulateur MSK + deframe ACARS (un par canal/frequence)
# ----------------------------------------------------------------------------
class AcarsChannel:
    def __init__(self, freq_mhz, on_message):
        self.freq_mhz = freq_mhz
        self.on_message = on_message

        # MSK demod state
        self.MskPhi = 0.0
        self.MskClk = 0.0
        self.MskDf = 0.0
        self.MskS = 0
        self.idx = 0
        self.inb = np.zeros(FLEN, dtype=np.complex128)
        self.MskLvlSum = 0.0
        self.MskBitCount = 0

        # bit assembly + framer state
        self.outbits = 0
        self.nbits = 8
        self.state = "WSYN"
        self.txt = []
        self.crc = [0, 0]

    # ---- bit assembly (cf. putbit/msk.c) ----
    def _putbit(self, v):
        self.outbits = (self.outbits >> 1) & 0xff
        if v > 0:
            self.outbits |= 0x80
        self.nbits -= 1
        if self.nbits <= 0:
            self._decode()

    # ---- MSK demodulation of one block of AM audio (cf. demodMSK/msk.c) ----
    def demod(self, dm):
        idx = self.idx
        p = self.MskPhi
        inb = self.inb
        for in_ in dm:
            s = SUBCARRIER / INTRATE * 2.0 * math.pi + self.MskDf
            p += s
            if p >= 2.0 * math.pi:
                p -= 2.0 * math.pi

            inb[idx] = in_ * cmath.exp(-p * 1j)
            idx = (idx + 1) % FLEN

            self.MskClk += s
            if self.MskClk >= 3.0 * math.pi / 2.0 - s / 2.0:
                self.MskClk -= 3.0 * math.pi / 2.0

                o = int(MFLTOVER * (self.MskClk / s + 0.5))
                if o > MFLTOVER:
                    o = MFLTOVER
                v = 0j
                oo = o
                for j in range(FLEN):
                    v += HMF[oo] * inb[(j + idx) % FLEN]
                    oo += MFLTOVER

                lvl = abs(v)
                v /= (lvl + 1e-8)
                self.MskLvlSum += lvl * lvl / 4.0
                self.MskBitCount += 1

                if self.MskS & 1:
                    vo = v.imag
                    dphi = -v.real if vo >= 0 else v.real
                else:
                    vo = v.real
                    dphi = v.imag if vo >= 0 else -v.imag

                if self.MskS & 2:
                    self._putbit(-vo)
                else:
                    self._putbit(vo)
                self.MskS = (self.MskS + 1) & 0xff

                self.MskDf = PLLC * self.MskDf + (1.0 - PLLC) * PLLG * dphi

        self.idx = idx
        self.MskPhi = p

    # ---- ACARS deframe state machine (cf. decodeAcars/acars.c) ----
    def _reset(self):
        self.state = "WSYN"
        self.MskDf = 0.0
        self.nbits = 1

    def _decode(self):
        r = self.outbits

        if self.state == "WSYN":
            if r == SYN:
                self.state = "SYN2"; self.nbits = 8; return
            if r == ((~SYN) & 0xff):
                self.MskS ^= 2; self.state = "SYN2"; self.nbits = 8; return
            self.nbits = 1
            return

        if self.state == "SYN2":
            if r == SYN:
                self.state = "SOH1"; self.nbits = 8; return
            if r == ((~SYN) & 0xff):
                self.MskS ^= 2; self.nbits = 8; return
            self._reset()
            return

        if self.state == "SOH1":
            if r == SOH:
                self.txt = []
                self.state = "TXT"; self.nbits = 8
                self.MskLvlSum = 0.0; self.MskBitCount = 0
                return
            self._reset()
            return

        if self.state == "TXT":
            self.txt.append(r)
            if r == ETX or r == ETB:
                self.state = "CRC1"; self.nbits = 8; return
            if len(self.txt) > 240:
                self._reset()
                return
            self.nbits = 8
            return

        if self.state == "CRC1":
            self.crc[0] = r
            self.state = "CRC2"; self.nbits = 8; return

        if self.state == "CRC2":
            self.crc[1] = r
            self._emit()
            self.state = "END"; self.nbits = 8; return

        if self.state == "END":
            self._reset(); self.nbits = 8; return

    # ---- message complete : check + print ----
    def _emit(self):
        txt = self.txt
        if len(txt) < 13:
            self._reset(); return

        # CRC over chars (parity included) + the 2 BCS bytes
        crc = 0
        for b in txt:
            crc = update_crc(crc, b)
        crc = update_crc(crc, self.crc[0])
        crc = update_crc(crc, self.crc[1])
        crc_ok = (crc == 0)

        # odd parity per char
        perr = sum(1 for b in txt if (NUMBITS[b] & 1) == 0)

        lvl = 0.0
        if self.MskBitCount:
            lvl = 10.0 * math.log10(self.MskLvlSum / self.MskBitCount + 1e-12)

        chars = [b & 0x7f for b in txt]
        mode = chr(chars[0])
        address = "".join(chr(c) for c in chars[1:8]).strip()
        ack = chars[8]
        label = "".join(chr(c) for c in chars[9:11])
        block_id = chr(chars[11])
        # text between STX (index 12) and ETX/ETB (last char)
        body = "".join(chr(c) for c in chars[13:-1])

        self.on_message({
            "freq": self.freq_mhz,
            "crc_ok": crc_ok,
            "perr": perr,
            "lvl": lvl,
            "mode": mode,
            "address": address,
            "ack": ack,
            "label": label,
            "block_id": block_id,
            "text": body,
        })


# ----------------------------------------------------------------------------
# Front-end : IQ -> DDC -> decimation -> AM, alimente le demodulateur MSK
# ----------------------------------------------------------------------------
class Frontend:
    """Une frequence : decale le canal a 0 Hz, decime vers INTRATE, AM (|.|)."""

    def __init__(self, fs, foff, channel):
        self.fs = fs
        self.foff = foff
        self.channel = channel        # AcarsChannel
        self.n0 = 0                   # running sample index (phase continuity)

        # 2-stage decimation fs -> fs/8 -> fs/80 = INTRATE (fs must be 80*INTRATE)
        self.b1 = firwin(65, 55000.0, fs=fs)
        self.b2 = firwin(129, 5500.0, fs=fs / 8.0)
        self.zi1 = np.zeros(len(self.b1) - 1)
        self.zi2 = np.zeros(len(self.b2) - 1)

    def process(self, iq):
        n = len(iq)
        # DDC : bring the channel (at -foff in baseband) to 0 Hz
        k = np.arange(self.n0, self.n0 + n)
        self.n0 += n
        mix = iq * np.exp(1j * 2.0 * math.pi * self.foff * k / self.fs)

        # stage 1 : /8
        y1, self.zi1 = lfilter(self.b1, 1.0, mix, zi=self.zi1)
        y1 = y1[::8]
        # stage 2 : /10  -> INTRATE
        y2, self.zi2 = lfilter(self.b2, 1.0, y1, zi=self.zi2)
        y2 = y2[::10]

        # AM demod (envelope) + feed MSK demod
        am = np.abs(y2)
        self.channel.demod(am.tolist())


# ----------------------------------------------------------------------------
# Sources d'IQ : rejeu fichier (numpy seul), SoapySDR (bladeRF/RTL), pyrtlsdr (RTL)
# ----------------------------------------------------------------------------
def file_blocks(path, N):
    """Rejoue une capture IQ brute (float32 entrelace I,Q,I,Q,...) par blocs."""
    with open(path, "rb") as f:
        while True:
            raw = np.fromfile(f, dtype=np.float32, count=2 * N)
            if raw.size < 2:
                break
            iq = raw[0::2] + 1j * raw[1::2]
            yield iq.astype(np.complex64)


def soapy_blocks(args, fs, f_center, N):
    """SDR via SoapySDR (Cincoze : bladeRF ou RTL)."""
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32

    devs = SoapySDR.Device.enumerate()
    if not devs:
        sys.exit("Aucun peripherique SoapySDR detecte.")
    chosen = None
    order = [args.device] if args.device else ["bladerf", "rtlsdr"]
    for want in order:
        for d in devs:
            if want in str(d).lower():
                chosen = d; break
        if chosen:
            break
    if chosen is None:
        chosen = devs[0]
    print(f"[SDR] SoapySDR : {chosen}", file=sys.stderr)

    dev = SoapySDR.Device(chosen)
    dev.setSampleRate(SOAPY_SDR_RX, 0, fs)
    dev.setFrequency(SOAPY_SDR_RX, 0, f_center)
    try:
        dev.setGainMode(SOAPY_SDR_RX, 0, bool(args.agc))
    except Exception:
        pass
    if not args.agc:
        dev.setGain(SOAPY_SDR_RX, 0, args.gain)
    if args.ppm:
        try:
            dev.setFrequencyCorrection(SOAPY_SDR_RX, 0, args.ppm)
        except Exception:
            pass

    rx = dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
    dev.activateStream(rx)
    try:
        mtu = int(dev.getStreamMTU(rx))
    except Exception:
        mtu = 0
    if mtu <= 0:
        mtu = 16384
    save = open(args.save, "wb") if args.save else None
    buff = np.empty(N, dtype=np.complex64)
    chunk = np.empty(mtu, dtype=np.complex64)
    pos = 0
    try:
        while True:
            want = min(mtu, N - pos)
            sr = dev.readStream(rx, [chunk], want, timeoutUs=1000000)
            if sr.ret > 0:
                buff[pos:pos + sr.ret] = chunk[:sr.ret]
                pos += sr.ret
                if pos >= N:
                    blk = buff.copy()
                    if save is not None:
                        blk.view(np.float32).tofile(save)
                    yield blk
                    pos = 0
    finally:
        if save is not None:
            save.close()
        dev.deactivateStream(rx)
        dev.closeStream(rx)


def rtl_blocks(args, fs, f_center, N):
    """RTL-SDR via pyrtlsdr (Mac : pas besoin de SoapySDR, juste librtlsdr)."""
    from rtlsdr import RtlSdr
    sdr = RtlSdr()
    sdr.sample_rate = fs
    sdr.center_freq = f_center
    if args.ppm:
        sdr.freq_correction = int(args.ppm)
    sdr.gain = "auto" if args.agc else args.gain
    print(f"[SDR] RTL-SDR (pyrtlsdr) tuner gain={sdr.gain}", file=sys.stderr)
    save = open(args.save, "wb") if args.save else None
    try:
        while True:
            iq = sdr.read_samples(N).astype(np.complex64)
            if save is not None:
                iq.view(np.float32).tofile(save)
            yield iq
    finally:
        if save is not None:
            save.close()
        sdr.close()


def live_blocks(args, fs, f_center, N):
    """Choisit la source live : --backend, sinon SoapySDR puis repli RTL/pyrtlsdr."""
    if args.backend == "rtl":
        return rtl_blocks(args, fs, f_center, N)
    if args.backend == "soapy":
        return soapy_blocks(args, fs, f_center, N)
    try:
        import SoapySDR  # noqa: F401
        return soapy_blocks(args, fs, f_center, N)
    except Exception:
        print("[SDR] SoapySDR indisponible -> RTL via pyrtlsdr", file=sys.stderr)
        return rtl_blocks(args, fs, f_center, N)


# ----------------------------------------------------------------------------
def print_message(m):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    flag = "CRC OK " if m["crc_ok"] else "CRC BAD"
    print("-" * 64)
    print(f"[{ts}] {m['freq']:.3f} MHz  {flag}  parite_err={m['perr']}  niveau={m['lvl']:.1f} dB")
    print(f"  Mode {m['mode']!r}  Addr {m['address']!r}  Label {m['label']!r}  Block {m['block_id']!r}")
    if m["text"]:
        print("  Texte :")
        print("    " + m["text"].replace("\r", "\n    ").rstrip())
    sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser(description="Decodeur ACARS terminal (RTL-SDR / bladeRF)")
    ap.add_argument("freqs", nargs="+", type=float, help="frequence(s) en MHz (ex: 131.525)")
    ap.add_argument("--device", choices=["rtlsdr", "bladerf"], default=None,
                    help="type SoapySDR a preferer (sinon auto)")
    ap.add_argument("--backend", choices=["auto", "soapy", "rtl"], default="auto",
                    help="source live : auto (defaut), soapy, ou rtl (pyrtlsdr)")
    ap.add_argument("--gain", type=float, default=30.0, help="gain RX en dB (defaut 30)")
    ap.add_argument("--agc", action="store_true", help="activer l'AGC (deconseille pour l'AM)")
    ap.add_argument("--ppm", type=float, default=0.0, help="correction ppm")
    ap.add_argument("--save", default=None, help="enregistrer l'IQ brut dans un fichier (capture)")
    ap.add_argument("--file", default=None, help="rejouer une capture IQ au lieu du live")
    args = ap.parse_args()

    fs = 80.0 * INTRATE          # 1.0 MHz, multiple de INTRATE pour la decimation
    foff = 100000.0              # decalage pour eviter le pic DC du SDR
    f_center = args.freqs[0] * 1e6 + foff
    N = 80 * 1024                # block size, multiple of 80 (decimation)

    # un front-end + un canal par frequence (toutes ramenees depuis f_center)
    chans = []
    for f in args.freqs:
        ch = AcarsChannel(f, print_message)
        off = (f * 1e6) - f_center
        fe = Frontend(fs=fs, foff=-off, channel=ch)
        chans.append(fe)

    if args.file:
        print(f"[ACARS] rejeu de {args.file} sur {args.freqs[0]:.3f} MHz ...", file=sys.stderr)
        src = file_blocks(args.file, N)
    else:
        rate = ", ".join(f"{f:.3f}" for f in args.freqs)
        print(f"[ACARS] ecoute {rate} MHz (Fs={fs/1e6:.3f} MS/s, gain={args.gain} dB"
              f"{' AGC' if args.agc else ''}). Ctrl+C pour quitter.", file=sys.stderr)
        src = live_blocks(args, fs, f_center, N)

    try:
        for iq in src:
            for fe in chans:
                fe.process(iq)
    except KeyboardInterrupt:
        print("\n[ACARS] arret.", file=sys.stderr)
    print("[ACARS] termine.", file=sys.stderr)


if __name__ == "__main__":
    main()
