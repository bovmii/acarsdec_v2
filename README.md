# ACARS Decoder - acarsdec_v2.py (English version)

**Version 1.1**

*French version: see `README_ACARS_RX_FR.md`.*

Author: Boumediene Bahloul, intern at the LASSENA laboratory (ETS Montreal).

---

## What I did

I wrote an ACARS decoder in Python, `acarsdec_v2.py`, independent of acarsdec.

I started from the reference decoder **acarsdec** (Thierry Leconte's, f00b4r0
fork). I took its algorithm: the **MSK demodulator** (`msk.c`) and the **ACARS
frame state machine** (`acars.c`), and rewrote them in Python. I added a front
end (carrier tuning, envelope detection) and a continuous listening mode on the
RTL-SDR.

Why rebuild my own instead of just using acarsdec: acarsdec turned out to be
painful on our bench (dependencies, rejected file formats, finicky RTL config).
My decoder is a **single Python file**, runs identically on **Linux and macOS**,
and I control every step, which let me debug the RFSoC ACARS transmitter.

I validated it on real ACARS (a `test.wav` recording, 2 messages decoded with a
valid CRC) and on the **RFSoC** transmission decoded live (valid CRC), which
proves that our board's ACARS modulation is correct.

---

## 1. Requirements and installation

You need **Python 3** (any recent 3.x, not Python 2) with **numpy** and **scipy**,
and the **rtl-sdr** tools (the `rtl_sdr` command, used for continuous listening).

### Automatic installation (recommended)

The easy way: **one script installs everything** (the dependencies and the
`acarsdecv2` command). From the `acarsdec_v2/` folder:

```bash
# macOS / Linux
./install.sh
```

That's it. And if you would rather do the steps yourself, no problem: the manual
installation below works just as well.

### Linux (Debian / Ubuntu)

```bash
sudo apt install rtl-sdr python3-numpy python3-scipy
```

If the RTL is held by another service (ADS-B) or the DVB kernel module:

```bash
sudo systemctl stop readsb 2>/dev/null
sudo rmmod dvb_usb_rtl28xxu rtl2832_sdr 2>/dev/null
```

### macOS

```bash
brew install librtlsdr
python3 -m pip install numpy scipy
export PATH="/opt/homebrew/bin:$PATH"
```

### Check that the RTL is detected

```bash
rtl_test
```

### Optional: make it a system command

To type `acarsdecv2` from anywhere (no `python3`, no `./`):

```bash
chmod +x acarsdec_v2.py
# macOS (Homebrew already in PATH)
ln -sf "$PWD/acarsdec_v2.py" /opt/homebrew/bin/acarsdecv2
# Linux
sudo ln -sf "$PWD/acarsdec_v2.py" /usr/local/bin/acarsdecv2
```

Then, from any folder: `acarsdecv2 -f 131.525`.
(Deliberately not plain `acarsdec`: that name belongs to the reference decoder,
and overwriting it would break an existing installation.)
(Under zsh, run `rehash` once, or open a new terminal.)

---

## 2. Usage

> **All examples below use `acarsdecv2`**, the command installed by `./install.sh`.
> **If you did not run the installer**, replace `acarsdecv2` with
> `python3 acarsdec_v2.py` everywhere, from inside the `acarsdec_v2/` folder.
> Both do exactly the same thing.

Help in French: `acarsdecv2 helpfr`.

### Continuous listening on the RTL (the main mode)

```bash
acarsdecv2 -f 131.525 -g 30
```

(no `--live` needed: give a frequency with `-f` and listening starts; a bare command shows the help.)
It listens continuously and prints each message as it comes. `Ctrl+C` to stop.
**Nothing is saved by default**: add `--log` to keep a record (see Saving messages).

Example output:

```
--------------------------------------------------
2026-07-13 15:48:10  131.525 MHz  (L:+77.4 dB  err:0)
Mode : F   Label : 14   Id : .   NAK
Aircraft reg: LASSENA
Text: test
```

Several frequencies at once (multi-channel, single RTL):

```bash
acarsdecv2 -f 131.525 131.725 131.825
```

Output format (`full` by default, or `line`, or `json`):

```bash
acarsdecv2 -f 131.525 --fmt line
acarsdecv2 -f 131.525 --fmt json -i LASSENA1
```

### Decode an IQ capture

```bash
rtl_sdr -f 131400000 -s 1024000 -g 30 -n 6000000 capture.iq
acarsdecv2 capture.iq --format u8 --fs 1024000
```

### Decode a WAV file (already demodulated audio)

```bash
acarsdecv2 recording.wav
```

### All options

| Option | Purpose | Default |
|--------|---------|---------|
| `--live` | force live listening (already the default without a file) | - |
| `-f, --freq <MHz> [MHz ...]` | listening frequency/frequencies (several allowed) | 131.550 |
| `-g, --gain <dB>` | RTL gain (live mode) | 30 |
| `--ppm <n>` | RTL frequency correction in ppm | 0 |
| `--save <file>` | live mode: also save the raw IQ | - |
| `--format {u8,c64}` | IQ capture format | u8 |
| `--fs <S/s>` | IQ capture sample rate | 1024000 |
| `--carrier <Hz>` | carrier offset in the capture (else auto) | auto |
| `--fmt {full,line,json}` | output format | full |
| `-b, --labels <L1,L2>` | keep only these labels (e.g. H1,Q0) | all |
| `-e, --skip-empty` | hide messages with no text | - |
| `-A, --downlink-only` | keep only aircraft-to-ground (approx.) | - |
| `-i, --station <id>` | station id (shown in full/json) | - |
| `-v, --verbose` | periodic reception status (live mode) | - |
| `--log [file]` | save decoded messages (see Saving messages) | disabled |

In live mode the RTL sample rate is chosen automatically to cover all requested
frequencies.

### Saving messages

Nothing is saved by default. Two ways to keep a record:

```bash
acarsdecv2 -f 131.550 --log                     # timestamped file in acarsdec_v2/
acarsdecv2 -f 131.550 --log ~/Desktop/roof.txt  # choose the file and folder
```

Bare `--log` creates `acars_YYYY-MM-DD_HH-MM-SS.txt` **next to the script**, no
matter which folder you run the command from. Give a path to choose the location.

`--log` stores decoded **messages only**. To capture **everything** printed on
screen (banner, `[rtl]` lines, errors), use `tee`, which is a **shell** command,
not an option of this tool:

```bash
acarsdecv2 -f 131.550 | tee out.txt        # screen + file
acarsdecv2 -f 131.550 | tee -a out.txt     # append instead of overwriting
acarsdecv2 -f 131.550 2>&1 | tee out.txt   # capture errors too
```

`tee` needs **both**: the pipe `|` before it, and a **file name** after it.
Without a file name it saves nothing, it just echoes to the screen. And without
`-a` it overwrites the file on every run.

### Which frequencies to listen to

| Region | ACARS channels |
|--------|----------------|
| North America (Montreal) | **131.550** (main), 130.025, 130.450, 129.125 |
| Europe | 131.725, 131.525 |
| RFSoC test bench | whatever the GUI is set to (131.525 or 136.950) |

Several frequencies at once only if they are close together (less than ~2 MHz
apart), otherwise they fall outside the band sampled by the RTL.

---

## 3. How it works

An ACARS message is modulated in **AM-MSK**: the data (2400 bit/s) modulates a
1800 Hz audio subcarrier (1200 and 2400 Hz tones), and that audio amplitude
modulates (AM) the VHF radio carrier (~131 MHz). The receiver recovers the audio
by envelope detection, then demodulates the MSK.

My processing chain:

```
RTL-SDR (IQ at the carrier)
   |  1. tune the carrier to 0 Hz (baseband)
   |  2. resample the complex signal to 12000 Hz (rejects the rest of the band)
   |  3. envelope detection: |signal|  (recovers the AM audio)
   v
Audio 12000 Hz
   |  4. MSK demod (VCO 1800 Hz + matched filter + staggered I/Q + PLL)
   v
Bits -> bytes
   |  5. state machine: SYN SYN SOH ... text ... ETX, then CRC
   |  6. parity + 16-bit CRC check
   v
Decoded message (if the CRC is valid)
```

Steps 4, 5 and 6 are my faithful port of acarsdec (f00b4r0 fork). Steps 1, 2, 3
and the live mode are my part.

---

## 4. Understanding the output

```
2026-07-13 15:48:10  131.525 MHz  (L:+77.4 dB  err:0)
Mode : F   Label : 14   Id : .   NAK
Aircraft reg: LASSENA
Text: test
```

- **Date / time**: message reception.
- **131.525 MHz**: the frequency (channel) that received the message.
- **`L:`**: signal level in dB (relative). Too low = raise the gain, saturated =
  lower it.
- **`err:`**: parity errors (0 = perfect).
- **`[CRC ERROR]`** appears if the CRC does not check out.
- **Mode / Label / Id / NAK-ACK / Aircraft reg / Text**: the ACARS fields.

The same block is appended to the log file if you used `--log`.

---

## 5. Troubleshooting

- **Nothing decodes**: check the frequency (`--freq`), the level (`L:`: raise or
  lower `--gain`), and that the RTL actually receives there (old dongles struggle
  around 131 MHz; I use an RTL-SDR Blog V4).
- **`rtl_sdr: command not found`**: rtl-sdr not installed or not in the PATH.
- **`usb_claim_interface error -6`**: another program holds the RTL
  (`pkill acarsdec`; `sudo systemctl stop readsb`).
- **`aucun message decode` on a file**: check `--fs` and `--format`, or force
  `--carrier <Hz>`.

---

## 6. Status / validation

- Decodes our own signal (`acars_tx.py`): valid CRC.
- Decodes a real ACARS recording (`test.wav`): 2 messages, valid CRC, where the
  real acarsdec refuses to even open the file (12500 Hz).
- Decodes the **RFSoC** transmission live via the RTL: valid CRC.
- Robustness (chaos monkey test): no crash on adversarial inputs, and no false
  positive (noise never produces a valid-CRC message).
