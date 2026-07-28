# ACARS Decoder - acarsdec_v2.py (English version)

**Version 1.3**

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

I validated it three ways. On a `test.wav` recording (2 messages, valid CRC).
On the **RFSoC** transmission decoded live, which proves that our board's ACARS
modulation is correct. And on **real air traffic**: 201 messages from 20
aircraft in two hours, from an antenna set up next to the Ecole nationale
d'aerotechnique in Saint-Hubert, 94 % of them passing the CRC, the farthest one
284 km away. That capture is in the repository.

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
| `-a, --analyse` | explain each message field by field (see below) | - |
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

### Explaining a message field by field

```bash
acarsdecv2 -f 131.550 -g 40 --analyse      # live
acarsdecv2 recording.wav --analyse         # on a file
```

Each decoded message is followed by a table that reads it out: airline and
flight, route, ATA chapter, position with its distance and bearing from the
receiver, ground station, UTC stamps, and the trade abbreviations in the free
text.

```
2026-07-28 10:15:03  131.550 MHz  (L:+44.8 dB  err:0)
Aircraft reg: C-FDCA
Text: M68AAC0638MMSNG AC0638/28/28/YYZYSJ/1414Z/405/1/32-00 /213540 /...
+------------+-------------------------------------------------------------+
| Field      | Meaning                                                     |
+============+=============================================================+
| C-FDCA     | aircraft registration, Canada                               |
| AC0638     | Air Canada flight 638                                       |
| YYZYSJ     | Toronto-Pearson to Saint John                               |
| 1414Z      | 14:14 UTC                                                   |
| 32-00      | ATA chapter 32 = landing gear and brakes                    |
| QRH        | Quick Reference Handbook, the emergency procedures manual   |
+------------+-------------------------------------------------------------+
```

This needs `analyse_acars.py` next to the script (section 7). Without it the
decoder still works, it just says so.

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
- **Fewer messages at maximum gain**: more gain is not more sensitivity. On my
  R820T the noise floor went from **+5 dB at gain 40 to +11 dB at 49.6**, so
  distant aircraft drown in it. Start around 40 and only raise it if levels are
  too low.

### The counter stops but the capture is fine

The `[rx] N message(s) | level ...` lines of `-v` are the proof of life. As long
as they keep coming every 4 s, the chain works, even if the counter does not
move: it just means nothing is on the air. Gaps of over a minute are normal on a
quiet channel. Only when **those lines stop entirely** is something wrong.

### If the RTL drops mid-capture

The RTL can stop feeding the decoder two ways: the `rtl_sdr` process exits, or
it stays alive and sends nothing (a USB stall). Both used to end a capture in
silence. They are now detected, reported with a timestamp **on screen and in the
`--log`**, and the RTL is restarted automatically:

```
[rx] 2026-07-28 10:09:37  the RTL stopped sending data (rtl_sdr still running) after 214s. Restarting it (1/5), 34 message(s) so far.
[rx] 2026-07-28 10:09:39  RTL back, capture continues.
```

It gives up after 5 failed restarts in a row and exits with status 1 instead of
0, so an overnight capture that died is not mistaken for one that finished. A
stream that ran at least 30 s before dropping counts as a fresh incident, so a
single USB hiccup does not eat the retry budget.

### The display freezes but the program is still running

If the output stops dead while the program is clearly alive (`Ctrl+C` still
works), the **terminal** is blocking, not the decoder. A terminal buffer is only
1 KB on macOS: once it stops being drained, and an accidental `Ctrl+S` is the
usual cause, the decoder blocks on its next write within about a minute.

Press **`Ctrl+Q`** and everything scrolls back at once, nothing is lost. To avoid
it entirely, keep the decoder off the terminal:

```bash
acarsdecv2 -f 131.550 -g 40 -v --log > ~/Desktop/out.txt 2>&1 &
tail -f ~/Desktop/out.txt
```

Only the `tail` can freeze then, and the capture keeps running.

---

## 6. Status / validation

- Decodes our own signal (`acars_tx.py`): valid CRC.
- Decodes a real ACARS recording (`test.wav`): 2 messages, valid CRC, where the
  real acarsdec refuses to even open the file (12500 Hz).
- Decodes the **RFSoC** transmission live via the RTL: valid CRC. It also
  carried a 73 character ATS message unchanged, not just a short test string.
- Decodes **real air traffic** over an antenna: 201 messages, 20 aircraft,
  **94 % valid CRC**, range measured at **284 km** (`acquisition_2026-07-28.txt`).
- Cross-checked without trusting the CRC: two position reports from one aircraft
  give a **ground speed of 848 to 933 km/h**, a jet cruise speed. A single wrong
  bit in a position would show up as an absurd figure.
- Robustness (chaos monkey test): no crash on adversarial inputs, and no false
  positive (noise never produces a valid-CRC message).

---

## 7. The analyser

`analyse_acars.py` does the same reading on saved logs, and adds two views the
live mode cannot give.

```bash
python3 analyse_acars.py my_logs/*.txt              # every message, explained
python3 analyse_acars.py log.txt --summary          # aggregate only
python3 analyse_acars.py log.txt --positions        # positions, map, speeds
python3 analyse_acars.py log.txt --reg C-FDCA       # one aircraft
python3 analyse_acars.py log.txt --text BRAKE -n 5  # search, detail 5
python3 analyse_acars.py log.txt --crc-ok           # drop corrupted frames
python3 analyse_acars.py log.txt --pos 45.50,-73.57 # another reference point
```

`--positions` lists every reported position with its distance and bearing, draws
a plain text map, and **derives ground speed and track** from two reports of the
same aircraft. ACARS transmits neither, so a plausible figure (a jet cruises
around 800 to 950 km/h) is a strong check that both positions were decoded
without a single wrong bit.

### Sample capture

`acquisition_2026-07-28.txt` is a **real over the air capture**: 201 messages
from 20 aircraft, recorded on 131.550 MHz next to the Ecole nationale
d'aerotechnique in Saint-Hubert on 28 July 2026, seven runs merged into one
file. 94 % of the frames pass the CRC, 14 carry a position, and the farthest
aircraft was 284 km away.

Distances are measured from a reference point, so give the recording site:
`--pos 45.5175,-73.4169`. Without it they are computed from the default, the
ETS campus, 12 km away.

```bash
python3 analyse_acars.py acquisition_2026-07-28.txt --summary
python3 analyse_acars.py acquisition_2026-07-28.txt --positions
python3 analyse_acars.py acquisition_2026-07-28.txt --text BRAKE
```

That last one pulls out an Air Canada maintenance message reporting a brake
system fault in flight, with the QRH reset that fixed it. It is there so the
analyser can be tried on real traffic without owning a receiver.

### Reference tables

`acars_data.csv` holds **31 361 airports, aerodromes, heliports and seaplane
bases** and **6 087 airlines**. It was built once from OurAirports (public
domain) and OpenFlights, and is **read from disk only: the analyser never
touches the network**. Without the file it falls back to smaller built-in
tables and still runs.

### What it will not do

It only reports what it identifies. Many ACARS labels are airline specific, so
it says "airline defined" rather than inventing a meaning, and it never claims a
location for a ground station.

Detection is deliberately conservative, because a full airport table makes plain
English words look like routes: `WEIGHT` splits into WEI + GHT, `RUNWAY` into
RUN + WAY, and `SYS` in "BRAKE SYS 2 FAULT" is a real IATA code in Russia.
Airport codes are therefore only read from slash delimited fields, and flight
numbers need four digits and a known airline code. Aggregate figures ignore
frames the CRC rejected, since a corrupted body yields plausible looking
nonsense.
