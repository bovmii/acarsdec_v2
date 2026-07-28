#!/usr/bin/env python3
"""ACARS message analyser.

Reads the .txt files produced by acarsdecv2 (--log) and explains every message
field by field: airline, route, time, ATA chapter, position, distance, and the
trade abbreviations found in the free text.

Principle: it only reports what it actually identifies. Many ACARS labels and
text formats are airline specific, so the tool says "airline defined" instead of
inventing a meaning. Everything runs offline: the reference tables below are
embedded in this file, there is no network access anywhere.

    python3 analyse_acars.py my_logs/*.txt
    python3 analyse_acars.py log.txt --summary
    python3 analyse_acars.py log.txt --reg C-FDCA

Author: Boumediene Bahloul - LASSENA / ETS Montreal
"""

import sys
import os
import re
import glob
import math
import argparse
import textwrap
from collections import Counter

__version__ = "1.0"

# Reference point used for distances: ETS, Montreal
REF_LAT, REF_LON = 45.4945, -73.5632
REF_NAME = "ETS Montreal"


# ---------------------------------------------------------------------------
# Reference tables (embedded on purpose: the tool must work with no network)
# ---------------------------------------------------------------------------

# Registration prefix -> country. Longer prefixes come first.
REG_COUNTRY = [
    ("C-", "Canada"), ("N", "United States"), ("F-", "France"),
    ("G-", "United Kingdom"), ("D-", "Germany"), ("OO-", "Belgium"),
    ("PH-", "Netherlands"), ("EI-", "Ireland"), ("LN-", "Norway"),
    ("SE-", "Sweden"), ("OY-", "Denmark"), ("OH-", "Finland"),
    ("EC-", "Spain"), ("I-", "Italy"), ("HB-", "Switzerland"),
    ("OE-", "Austria"), ("SP-", "Poland"), ("9H-", "Malta"),
    ("A6-", "United Arab Emirates"), ("VH-", "Australia"),
    ("ZK-", "New Zealand"), ("XA-", "Mexico"), ("VT-", "India"),
    ("TC-", "Turkey"), ("JA", "Japan"), ("HL", "South Korea"),
    ("B-", "China"), ("PT-", "Brazil"), ("PR-", "Brazil"), ("PP-", "Brazil"),
]

# IATA airline code (2 characters) as it appears inside the flight number
AIRLINE = {
    "AC": "Air Canada", "RV": "Air Canada Rouge", "QK": "Jazz (Air Canada Express)",
    "TS": "Air Transat", "WS": "WestJet", "WR": "WestJet Encore", "PD": "Porter",
    "F8": "Flair", "Y9": "Lynx", "5T": "Canadian North", "8P": "Pacific Coastal",
    "DL": "Delta", "AA": "American Airlines", "UA": "United", "WN": "Southwest",
    "AS": "Alaska Airlines", "B6": "JetBlue", "NK": "Spirit", "F9": "Frontier",
    "HA": "Hawaiian", "G4": "Allegiant", "MX": "Breeze",
    "AF": "Air France", "BA": "British Airways", "LH": "Lufthansa", "KL": "KLM",
    "IB": "Iberia", "AZ": "ITA Airways", "LX": "Swiss", "OS": "Austrian",
    "SN": "Brussels Airlines", "TP": "TAP Air Portugal", "SK": "SAS",
    "AY": "Finnair", "EI": "Aer Lingus", "TK": "Turkish Airlines",
    "EK": "Emirates", "QR": "Qatar Airways", "EY": "Etihad", "SQ": "Singapore Airlines",
    "CX": "Cathay Pacific", "JL": "Japan Airlines", "NH": "ANA", "KE": "Korean Air",
    "AM": "Aeromexico", "AV": "Avianca", "LA": "LATAM", "CM": "Copa",
    "FX": "FedEx", "5X": "UPS", "CV": "Cargolux",
}

# Airports keyed by IATA code. Canadian ICAO codes are "C" + IATA.
AIRPORT = {
    "YUL": "Montreal-Trudeau", "YMX": "Montreal-Mirabel", "YHU": "Montreal-Saint-Hubert",
    "YYZ": "Toronto-Pearson", "YTZ": "Toronto-Billy Bishop", "YHM": "Hamilton",
    "YOW": "Ottawa", "YQB": "Quebec City", "YVR": "Vancouver", "YYC": "Calgary",
    "YEG": "Edmonton", "YWG": "Winnipeg", "YHZ": "Halifax", "YSJ": "Saint John",
    "YFC": "Fredericton", "YQM": "Moncton", "YYG": "Charlottetown",
    "YYT": "St John's", "YQR": "Regina", "YXE": "Saskatoon", "YZF": "Yellowknife",
    "YQX": "Gander", "YXU": "London (Ontario)", "YKF": "Kitchener-Waterloo",
    "YQT": "Thunder Bay", "YXY": "Whitehorse", "YFB": "Iqaluit",
    "JFK": "New York-JFK", "EWR": "Newark", "LGA": "New York-LaGuardia",
    "BOS": "Boston", "ORD": "Chicago-O'Hare", "MDW": "Chicago-Midway",
    "ATL": "Atlanta", "DFW": "Dallas-Fort Worth", "DEN": "Denver",
    "LAX": "Los Angeles", "SFO": "San Francisco", "SEA": "Seattle",
    "MIA": "Miami", "MCO": "Orlando", "FLL": "Fort Lauderdale", "TPA": "Tampa",
    "PHL": "Philadelphia", "DTW": "Detroit", "MSP": "Minneapolis",
    "CLT": "Charlotte", "IAH": "Houston", "PHX": "Phoenix", "LAS": "Las Vegas",
    "DCA": "Washington-National", "IAD": "Washington-Dulles", "BWI": "Baltimore",
    "BUF": "Buffalo", "PIT": "Pittsburgh", "CVG": "Cincinnati", "SLC": "Salt Lake City",
    "CDG": "Paris-Charles de Gaulle", "ORY": "Paris-Orly", "LHR": "London-Heathrow",
    "LGW": "London-Gatwick", "FRA": "Frankfurt", "MUC": "Munich",
    "AMS": "Amsterdam", "BRU": "Brussels", "MAD": "Madrid", "BCN": "Barcelona",
    "FCO": "Rome-Fiumicino", "ZRH": "Zurich", "GVA": "Geneva", "VIE": "Vienna",
    "CPH": "Copenhagen", "ARN": "Stockholm", "OSL": "Oslo", "HEL": "Helsinki",
    "DUB": "Dublin", "LIS": "Lisbon", "IST": "Istanbul", "ATH": "Athens",
    "DXB": "Dubai", "DOH": "Doha", "AUH": "Abu Dhabi", "TLV": "Tel Aviv",
    "NRT": "Tokyo-Narita", "HND": "Tokyo-Haneda", "ICN": "Seoul-Incheon",
    "HKG": "Hong Kong", "SIN": "Singapore", "PEK": "Beijing", "PVG": "Shanghai",
    "SYD": "Sydney", "MEL": "Melbourne", "AKL": "Auckland",
    "MEX": "Mexico City", "CUN": "Cancun", "GRU": "Sao Paulo", "EZE": "Buenos Aires",
    "BOG": "Bogota", "PTY": "Panama City", "SJU": "San Juan", "PUJ": "Punta Cana",
}

# ATA 100 chapters: which aircraft system a maintenance message is about
ATA = {
    "05": "time limits and maintenance checks",
    "21": "air conditioning", "22": "auto flight",
    "23": "communications", "24": "electrical power",
    "25": "equipment and furnishings", "26": "fire protection",
    "27": "flight controls", "28": "fuel", "29": "hydraulic power",
    "30": "ice and rain protection", "31": "indicating and recording systems",
    "32": "landing gear and brakes", "33": "lights",
    "34": "navigation", "35": "oxygen", "36": "pneumatic",
    "38": "water and waste", "45": "central maintenance system",
    "46": "information systems", "49": "auxiliary power unit (APU)",
    "52": "doors", "53": "fuselage", "54": "nacelles and pylons",
    "55": "stabilizers", "56": "windows", "57": "wings",
    "71": "power plant", "72": "engine",
    "73": "engine fuel and control", "74": "ignition",
    "75": "engine bleed air", "76": "engine controls",
    "77": "engine indicating", "78": "exhaust and thrust reverser",
    "79": "engine oil", "80": "starting",
}

# ACARS labels. Only the ones with a standard meaning are listed; everything
# else is reported as airline defined, which is the honest answer.
LABEL = {
    "Q0": "link test",
    "SA": "media advisory, link status change",
    "H1": "message to/from terminal, general purpose",
    # The squitter label is '_' followed by DEL (0x7F), not '_' alone.
    "_\x7f": "squitter: the aircraft announces itself, no useful payload",
    "_d": "squitter (presence announcement)",
    "_": "no label",
    "5Z": "airline defined",
    "B6": "ATC request or reply",
    "B9": "ATC clearance request",
    "A6": "ATC message",
    "10": "airline defined",
    "80": "airline defined",
    "C1": "message to the cockpit",
    "RA": "information request",
    "RB": "reply to a request",
}

# Abbreviations found in the free text
GLOSSARY = {
    "QRH": "Quick Reference Handbook, the emergency procedures manual",
    "OUT": "gate departure (OOOI event)",
    "OFF": "takeoff (OOOI event)",
    "ON": "landing (OOOI event)",
    "IN": "gate arrival (OOOI event)",
    "ETA": "estimated time of arrival",
    "ETD": "estimated time of departure",
    "POS": "position report",
    "FOB": "fuel on board",
    "ATIS": "airport weather and runway information",
    "PIREP": "pilot report",
    "MEL": "Minimum Equipment List",
    "NOTAM": "notice to airmen",
    "TOC": "top of climb",
    "TOD": "top of descent",
    "FAULT": "reported fault",
    "FAIL": "reported failure",
    "RESET": "reset",
    "SUCCESSFUL": "operation succeeded",
    "INOP": "inoperative",
    "AFN": "ATS Facilities Notification, logon with air traffic control",
    "CPDLC": "controller-pilot data link communications",
    "ADS": "automatic dependent surveillance",
    "CLB": "climb",
    "DES": "descent",
    "LDG": "landing",
    "LDA": "landing distance available",
    "END": "endurance, remaining flight time",
    "WX": "weather",
    "FMS": "flight management system",
    "SATCOM": "satellite link",
}


# Trade or plain English words that also happen to be real airport codes. They
# turn up in the free text and must never be read as an airport.
STOPWORDS = {
    "SNAG", "FUEL", "GATE", "CREW", "TIME", "TEST", "DOOR", "OPEN", "SHUT",
    "GOOD", "OVER", "LAND", "TAXI", "HOLD", "TURN", "LEFT", "STOP", "PACK",
    "MAIN", "AUTO", "DATA", "LINK", "FREE", "PART", "PLAN", "LATE", "NEXT",
    "FLAP", "GEAR", "BRAKE", "WING", "FUSE", "SEAT", "LOAD", "TRIM", "IDLE",
}

# Optional full tables. acars_data.csv sits next to this script and holds every
# airport and every airline that carries a usable code, rebuilt from public data
# sets. It is read from disk, never from the network. Without it the built-in
# tables above still work, they are just smaller.
AIRPORT_ICAO = {}      # 4-letter ICAO -> airport
AIRLINE_ICAO = {}      # 3-letter ICAO -> airline


def load_data():
    """Merge acars_data.csv into the built-in tables, if the file is there."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                        "acars_data.csv")
    if not os.path.exists(path):
        return 0, 0
    n_ap = n_al = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split(",", 3)
                if len(parts) != 4:
                    continue
                kind, iata, icao, label = parts
                if not label:
                    continue
                if kind == "A":
                    if iata:
                        AIRPORT.setdefault(iata, label)
                    if icao:
                        AIRPORT_ICAO.setdefault(icao, label)
                    n_ap += 1
                elif kind == "L":
                    if iata:
                        AIRLINE.setdefault(iata, label)
                    if icao:
                        AIRLINE_ICAO.setdefault(icao, label)
                    n_al += 1
    except OSError:
        return 0, 0
    return n_ap, n_al


def airport_name(code):
    """Look up a 3-letter IATA or 4-letter ICAO code."""
    return AIRPORT.get(code) or AIRPORT_ICAO.get(code)


# ---------------------------------------------------------------------------
# Log file parsing
# ---------------------------------------------------------------------------

SEP = "-" * 50


def parse_log(path):
    """Split an acarsdecv2 .txt into messages. Returns a list of dicts."""
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print("cannot read %s: %s" % (path, exc))
        return []
    out = []
    for block in raw.split(SEP):
        head = re.search(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+([\d.]+) MHz\s+"
                         r"\(L:([+\-][\d.]+) dB\s+err:(\d+)\)(.*)", block)
        if not head:
            continue
        msg = {
            "file": os.path.basename(path),
            "time": head.group(1),
            "freq": float(head.group(2)),
            "level": float(head.group(3)),
            "err": int(head.group(4)),
            "crc_ok": "CRC ERROR" not in head.group(5),
            "mode": "", "label": "", "blk": "", "ack": "", "reg": "", "text": "",
        }
        m = re.search(r"Mode : (\S+)\s+Label : (\S+)\s+Id : (\S+)\s+(\S+)", block)
        if m:
            msg["mode"], msg["label"] = m.group(1), m.group(2)
            msg["blk"], msg["ack"] = m.group(3), m.group(4)
        m = re.search(r"Aircraft reg: (\S+)", block)
        if m:
            msg["reg"] = m.group(1)
        m = re.search(r"Text: (.*?)(?=\n(?:Mode :|Aircraft reg:|\[rx\])|\Z)",
                      block, re.S)
        if m:
            msg["text"] = m.group(1).rstrip()
        out.append(msg)
    return out


# ---------------------------------------------------------------------------
# Field identification
# ---------------------------------------------------------------------------

def printable(s):
    """ACARS frames carry control characters (DEL, STX...) that would mangle
    the terminal. Replace them with a dot."""
    return "".join(c if 32 <= ord(c) < 127 else "." for c in s)


def country_of(reg):
    for pref, name in REG_COUNTRY:
        if reg.upper().startswith(pref):
            return name
    return None


def haversine(lat, lon):
    r = 6371.0
    p1, p2 = math.radians(REF_LAT), math.radians(lat)
    dp, dl = math.radians(lat - REF_LAT), math.radians(lon - REF_LON)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_position(text):
    """Look for a position in the formats seen on the air. Returns (lat, lon)."""
    m = re.search(r"N ?(\d{1,2}\.\d+)\s*,\s*W ?(\d{1,3}\.\d+)", text)
    if m:
        return float(m.group(1)), -float(m.group(2))
    m = re.search(r"(\d{2})(\d{2}\.\d)N(\d{3})(\d{2}\.\d)W", text)
    if m:
        return (int(m.group(1)) + float(m.group(2)) / 60,
                -(int(m.group(3)) + float(m.group(4)) / 60))
    # N DDMM.M W DDDMM.M written without any separator. It shows up behind POS
    # in a position report, but also behind FPO inside an AFN logon, so the
    # prefix is not required. The shape itself is distinctive enough.
    m = re.search(r"[Nn](\d{2})(\d{2})(\d)[Ww](\d{3})(\d{2})(\d)(?!\d)", text)
    if m:
        lat = int(m.group(1)) + (int(m.group(2)) + int(m.group(3)) / 10) / 60
        lon = int(m.group(4)) + (int(m.group(5)) + int(m.group(6)) / 10) / 60
        if lat <= 90 and lon <= 180:
            return lat, -lon
    return None


def find_flights(text):
    """Flight numbers: a known IATA airline code followed by 2 to 4 digits.

    Two cases. The flight often stands alone ("AC0638/28/28"), but it is also
    glued to the start of the text behind a block number and a separating 'A'
    ("S67ARV2012" = block S67, then flight RV2012). The second case is only
    accepted when the airline code is known, so nothing is invented.
    """
    seen, out = set(), []

    def keep(tok, code, digits):
        # A flight number is written on 4 digits here, and 0000 is padding, not
        # a flight. Without those two rules almost any two letters followed by
        # digits matches, since the full table holds over 6000 airline codes.
        if len(digits) != 4 or digits == "0000" or code not in AIRLINE:
            return
        if tok in seen:
            return
        seen.add(tok)
        out.append((tok, code, digits.lstrip("0") or "0"))

    m = re.match(r"[A-Z]\d{2}A([A-Z]{2})(\d{4})", text)
    if m:
        keep(m.group(1) + m.group(2), m.group(1), m.group(2))
    for m in re.finditer(r"\b([A-Z]{2})(\d{4})\b", text):
        keep(m.group(0), m.group(1), m.group(2))
    return out


def find_airports(text):
    """Airport codes, only where they cannot be confused with the trade jargon
    that fills these messages. With the full table loaded, CLB, MED, COR, END
    and MAX are all real IATA codes somewhere in the world, so an isolated
    three-letter word is deliberately ignored. Accepted forms:

      - two ICAO codes glued together (CYTZCYHU) or two IATA ones (YYZYSJ)
      - a lone 4-letter ICAO code, which is unambiguous enough
      - an IATA code delimited by slashes or spaces on both sides (/YYG/YQM/)
    """
    out = []

    def add(code, name):
        if code not in [c for c, _ in out]:
            out.append((code, name))

    # Un couple OACI colle (CYTZCYHU) : 8 lettres qui se coupent en deux codes
    # valides, c est assez distinctif pour etre pris n importe ou dans le texte.
    # Les bornes sont "pas une lettre" et non \b, car le couple est souvent
    # accole a des chiffres : ...AP32521CYTZCYHU150724...
    for m in re.finditer(r"(?<![A-Z])([A-Z]{4})([A-Z]{4})(?![A-Z])", text):
        a, b = AIRPORT_ICAO.get(m.group(1)), AIRPORT_ICAO.get(m.group(2))
        if a and b:
            add(m.group(1), a)
            add(m.group(2), b)

    # Pour le reste on n accepte que des champs delimites par des BARRES
    # OBLIQUES. C est ce qui separe les mots entiers du texte libre des vrais
    # champs structures : sans cette regle, WEIGHT se lit WEI + GHT, MANUAL se
    # lit MAN + UAL, RUNWAY se lit RUN + WAY et PLEASE se lit PLE + ASE, quatre
    # paires de codes parfaitement valides quelque part dans le monde.
    fields = [f.strip() for f in text.split("/")]
    for i, f in enumerate(fields):
        if re.fullmatch(r"[A-Z]{6}", f):              # couple IATA colle
            a, b = AIRPORT.get(f[:3]), AIRPORT.get(f[3:])
            if a and b:
                add(f[:3], a)
                add(f[3:], b)
        elif re.fullmatch(r"[A-Z]{3}", f):            # IATA seul : par paire
            nxt = fields[i + 1] if i + 1 < len(fields) else ""
            a, b = AIRPORT.get(f), AIRPORT.get(nxt)
            if a and b and f not in GLOSSARY and nxt not in GLOSSARY:
                add(f, a)
                add(nxt, b)
    # Code OACI seul (KEWR) : quatre lettres, c est assez distinctif pour etre
    # accepte dans un champ separe par une virgule aussi, une fois ecartes les
    # mots du metier qui sont eux aussi des codes quelque part (SNAG, GATE...).
    for f in re.split(r"[/,;]", text):
        f = f.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9]{3}", f) and f not in GLOSSARY \
                and f not in STOPWORDS:
            a = AIRPORT_ICAO.get(f)
            if a:
                add(f, a)
    return out


def find_ata(text):
    """ATA reference such as 32-00 or 32-41."""
    m = re.search(r"\b(\d{2})-(\d{2})\b", text)
    if m and m.group(1) in ATA:
        return m.group(0), ATA[m.group(1)]
    return None


def find_times(text):
    """Zulu times such as 1414Z."""
    return [m.group(1) for m in re.finditer(r"\b(\d{4})Z\b", text)]


def find_utc_stamps(text):
    """Six digit UTC stamps, HHMMSS, as ATS messages carry them. Checked against
    the reception time on every AFN message of a real capture: the field always
    landed within a few seconds of it. The surrounding delimiter is required, so
    that a bare run of digits inside a longer field is not misread as a time."""
    out = []
    for m in re.finditer(r"[,/](\d{2})(\d{2})(\d{2})(?=[,/]|$)", text):
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if h < 24 and mi < 60 and s < 60:
            out.append("%02d:%02d:%02d" % (h, mi, s))
    return out


def find_report_extras(text):
    """Fields that sit just after a position inside a position report, in the
    comma separated form both operators seen here use:

        <position>,<waypoint>,<time>,<level>,<waypoint>,<time>,<waypoint>,M<temp>

    Everything is anchored on the position, so a stray number elsewhere in the
    message is not picked up. Returns a list of (field, meaning).
    """
    m = re.search(r"[Nn]\d{5}[Ww]\d{6}", text)
    if not m:
        return []
    tail = text[m.end():]
    out, waypoints = [], []
    for f in [x.strip() for x in tail.split(",")][:9]:
        if re.fullmatch(r"[0-4]\d{2}", f) and 50 <= int(f) <= 500:
            out.append(("FL" + f, "flight level %s, i.e. %s ft"
                        % (f, format(int(f) * 100, ",d"))))
        elif re.fullmatch(r"M\d{2}", f):
            out.append((f, "outside air temperature, -%s C" % f[1:]))
        elif re.fullmatch(r"[A-Z]{5}", f):
            waypoints.append(f)
        elif re.fullmatch(r"\d{6}", f):
            h, mi, s = f[:2], f[2:4], f[4:]
            if int(h) < 24 and int(mi) < 60 and int(s) < 60:
                out.append((f, "%s:%s:%s UTC" % (h, mi, s)))
    if waypoints:
        out.append((" ".join(waypoints),
                    "route waypoint%s the aircraft reports flying via"
                    % ("s" if len(waypoints) > 1 else "")))
    return out


def find_ats_fields(text):
    """An ATS (AFN) message is a run of /XXX blocks. What each one carries was
    read off a real logon exchange rather than assumed, and the ones that stayed
    unclear are reported as such instead of being given a made up meaning."""
    known = {
        "FMH": "logon request: flight id, registration and time",
        "FPO": "position at the moment of the logon",
        "FCO": "declared capability and its version",
        "FCP": "address of an air traffic facility",
        "FRP": "response field, contents not identified",
    }
    out = []
    for m in re.finditer(r"/(F[A-Z]{2})([^/]*)", text):
        tag, val = m.group(1), m.group(2).strip().rstrip(",")
        if tag in known and (tag, val) not in out:
            out.append(("/%s %s" % (tag, val[:26]), known[tag]))
    return out


def find_date(text):
    """DDMMYY written right after a TS timestamp."""
    m = re.search(r"TS\d{6},(\d{2})(\d{2})(\d{2})", text)
    if m and int(m.group(1)) <= 31 and int(m.group(2)) <= 12:
        return "%s/%s/20%s" % (m.group(1), m.group(2), m.group(3))
    return None


def find_sublabel(text):
    """A '#' right after the flight id introduces a sublabel that refines the
    message type. Its meaning is defined by the operator, so only its presence
    is reported."""
    m = re.search(r"#([A-Z0-9]{2,3})", text)
    return m.group(1) if m else None


def find_ground_station(text):
    """The seven character address that precedes the message type, such as
    YULE2YA or USADCXA, is the ground station the aircraft is talking to. When
    it starts with a known airport code, that tells you where it sits."""
    out = []
    for m in re.finditer(r"\b([A-Z]{3}[A-Z0-9]{4})\.", text):
        code = m.group(1)
        if code in out:
            continue
        out.append(code)
    return out


def find_levels(text):
    """Flight levels such as FL370."""
    return [m.group(1) for m in re.finditer(r"\bFL ?(\d{3})\b", text)]


def find_terms(text):
    up = text.upper()
    return [(k, v) for k, v in GLOSSARY.items()
            if re.search(r"\b%s\b" % re.escape(k), up)]


def analyse(msg):
    """Build the (field, meaning) rows for one message."""
    rows = []
    txt = msg["text"]

    if msg["reg"]:
        c = country_of(msg["reg"])
        rows.append((msg["reg"], "aircraft registration, %s"
                     % (c if c else "country not identified")))

    for full, code, num in find_flights(txt):
        rows.append((full, "%s flight %s" % (AIRLINE[code], num)))

    aps = find_airports(txt)
    if len(aps) >= 2:
        rows.append(("%s%s" % (aps[0][0], aps[1][0]) if len(aps[0][0]) == 3
                     else "%s / %s" % (aps[0][0], aps[1][0]),
                     "%s to %s" % (aps[0][1], aps[1][1])))
        for code, name in aps[2:]:
            rows.append((code, name))
    else:
        for code, name in aps:
            rows.append((code, name))

    for gs in find_ground_station(txt):
        # The first three letters usually name the site (YUL = Montreal), but
        # not always, so no location is claimed here: USA is a real IATA code
        # too, and USADCXA has nothing to do with Concord in North Carolina.
        rows.append((gs, "ground station the aircraft is talking to"))

    sub = find_sublabel(txt)
    if sub:
        rows.append(("#" + sub, "sublabel refining the message type, "
                                "operator defined"))

    for t in find_times(txt):
        rows.append((t + "Z", "%s:%s UTC" % (t[:2], t[2:])))

    for t in find_utc_stamps(txt):
        rows.append((t.replace(":", ""), "%s UTC, when the aircraft sent it" % t))

    for fl in find_levels(txt):
        rows.append(("FL" + fl, "flight level %s, i.e. %s ft"
                     % (fl, format(int(fl) * 100, ",d"))))

    ata = find_ata(txt)
    if ata:
        rows.append((ata[0], "ATA chapter %s = %s" % (ata[0][:2], ata[1])))

    pos = find_position(txt)
    if pos:
        d = haversine(*pos)
        rows.append(("position", "%.3f N  %.3f W, %.0f km from %s, bearing %s %.0f"
                     % (pos[0], -pos[1], d, REF_NAME,
                        compass(bearing(*pos)), bearing(*pos))))
    rows.extend(find_report_extras(txt))

    dat = find_date(txt)
    if dat:
        rows.append((dat.replace("/", ""), "date, %s" % dat))

    rows.extend(find_ats_fields(txt))

    lab = msg["label"]
    if lab:
        rows.append(("label %s" % printable(lab),
                     LABEL.get(lab, "airline defined")))
    if msg["ack"]:
        rows.append((msg["ack"],
                     "acknowledged" if msg["ack"] == "ACK"
                     else "not acknowledged" if msg["ack"] == "NAK"
                     else "acknowledge field, raw value"))

    for k, v in find_terms(txt):
        rows.append((k, v))

    # A repeated field says nothing more the second time. It happens whenever a
    # message carries the same block twice, which is exactly what a bench test
    # produces when the text is sent doubled.
    seen, uniq = set(), []
    for a, b in rows:
        if (a, b) not in seen:
            seen.add((a, b))
            uniq.append((a, b))
    return uniq


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def table(rows, w_left=20, w_right=70):
    """Boxed table, right column wrapped."""
    if not rows:
        return ["  (no field identified)"]
    w_left = max(w_left, min(28, max(len(str(a)) for a, _ in rows)))
    top = "+" + "-" * (w_left + 2) + "+" + "-" * (w_right + 2) + "+"
    mid = "+" + "=" * (w_left + 2) + "+" + "=" * (w_right + 2) + "+"
    out = [top, "| %-*s | %-*s |" % (w_left, "Field", w_right, "Meaning"), mid]
    for a, b in rows:
        parts = textwrap.wrap(str(b), w_right) or [""]
        left = textwrap.wrap(str(a), w_left) or [""]
        for i in range(max(len(parts), len(left))):
            out.append("| %-*s | %-*s |"
                       % (w_left, left[i] if i < len(left) else "",
                          w_right, parts[i] if i < len(parts) else ""))
        out.append(top)
    return out


def show(msg, index, total):
    flag = "CRC OK" if msg["crc_ok"] else "CRC INVALID"
    print()
    print("=" * 96)
    print("Message %d/%d   %s   %.3f MHz   L:%+.1f dB   err:%d   %s"
          % (index, total, msg["time"], msg["freq"], msg["level"],
             msg["err"], flag))
    print("=" * 96)
    if not msg["crc_ok"]:
        print("  Warning: invalid CRC. The content is corrupted, so reading it "
              "field by field is meaningless.")
    for line in table(analyse(msg)):
        print(line)
    body = printable(" ".join(msg["text"].split()))
    print("Raw text: " + (body if body else "(empty)"))


def bearing(lat, lon):
    """Initial bearing from the reference point to (lat, lon), in degrees."""
    p1, p2 = math.radians(REF_LAT), math.radians(lat)
    dl = math.radians(lon - REF_LON)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(deg):
    pts = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return pts[int((deg + 11.25) % 360 / 22.5)]


def positions(msgs):
    """Every position reported by an aircraft, with distance and bearing from
    the receiver, plus a plain text map. Only frames the CRC accepted."""
    pts = []
    for m in msgs:
        if not m["crc_ok"]:
            continue
        p = find_position(m["text"])
        if p:
            d = haversine(*p)
            b = bearing(*p)
            pts.append((d, b, p, m))
    if not pts:
        print("\nNo position reported in these messages.")
        return
    pts.sort(key=lambda p: p[0])
    print()
    print("=" * 96)
    print("POSITIONS   %d aircraft report(s), distances from %s (%.4f, %.4f)"
          % (len(pts), REF_NAME, REF_LAT, REF_LON))
    print("=" * 96)
    print("  %-8s %-9s %8s  %-8s %9s   %s"
          % ("time", "aircraft", "distance", "bearing", "level", "coordinates"))
    for d, b, (la, lo), m in pts:
        print("  %-8s %-9s %6.0f km  %-3s %3.0f  %+6.1f dB   %.3f N  %.3f W"
              % (m["time"][11:], m["reg"], d, compass(b), b, m["level"], la, -lo))

    # plain text map, receiver at the centre, north up
    W, H = 63, 21
    span = max(d for d, _, _, _ in pts) * 1.15
    grid = [[" "] * W for _ in range(H)]
    cx, cy = W // 2, H // 2
    for y in range(H):
        grid[y][cx] = "|"
    for x in range(W):
        grid[cy][x] = "-"
    grid[cy][cx] = "R"
    for d, b, (la, lo), m in pts:
        rad = math.radians(b)
        x = int(round(cx + d * math.sin(rad) / span * (W // 2)))
        y = int(round(cy - d * math.cos(rad) / span * (H // 2)))
        if 0 <= x < W and 0 <= y < H:
            grid[y][x] = "o" if grid[y][x] in " |-" else "*"
    print()
    print("  north up, R = receiver, o = aircraft, edge = %.0f km" % span)
    for row in grid:
        print("  " + "".join(row))

    # Ground speed and track, rebuilt from two positions of the same aircraft.
    # ACARS does not carry either, so this is derived, not received: a wrong bit
    # in a position would show up here as an absurd speed.
    by_reg = {}
    for d, b, p, m in pts:
        by_reg.setdefault(m["reg"], []).append((m["time"], p))
    legs = []
    for reg, seq in by_reg.items():
        seq.sort()
        for (t1, p1), (t2, p2) in zip(seq, seq[1:]):
            dt = ((int(t2[11:13]) * 3600 + int(t2[14:16]) * 60 + int(t2[17:19]))
                  - (int(t1[11:13]) * 3600 + int(t1[14:16]) * 60 + int(t1[17:19])))
            if dt <= 0 or p1 == p2:
                continue
            gl, gb = REF_LAT, REF_LON
            globals()["REF_LAT"], globals()["REF_LON"] = p1
            dist, brg = haversine(*p2), bearing(*p2)
            globals()["REF_LAT"], globals()["REF_LON"] = gl, gb
            legs.append((reg, t1[11:], t2[11:], dt, dist, dist / dt * 3600, brg))
    if legs:
        print()
        print("  Ground speed and track, derived from two reports of one aircraft")
        print("  %-9s %-9s %-9s %5s %8s %10s %8s"
              % ("aircraft", "from", "to", "gap", "distance", "speed", "track"))
        for reg, t1, t2, dt, dist, kmh, brg in legs:
            print("  %-9s %-9s %-9s %4ds %7.1f km %6.0f km/h %3s %3.0f"
                  % (reg, t1, t2, dt, dist, kmh, compass(brg), brg))
        print("  A jet cruises around 800 to 950 km/h: a plausible figure here "
              "means the two")
        print("  positions were decoded without a single wrong bit.")


def summary(msgs):
    print()
    print("=" * 96)
    print("SUMMARY   %d message(s)" % len(msgs))
    print("=" * 96)
    ok = sum(1 for m in msgs if m["crc_ok"])
    print("  Valid CRC          : %d / %d (%.0f %%)"
          % (ok, len(msgs), 100.0 * ok / len(msgs) if msgs else 0))
    lv = sorted(m["level"] for m in msgs)
    if lv:
        print("  Level              : min %+.1f  median %+.1f  max %+.1f dB"
              % (lv[0], lv[len(lv) // 2], lv[-1]))
    regs = Counter(m["reg"] for m in msgs if m["reg"])
    print("  Distinct aircraft  : %d" % len(regs))
    for reg, n in regs.most_common(8):
        c = country_of(reg)
        print("      %-10s %2d message(s)%s" % (reg, n, "  (%s)" % c if c else ""))
    lab = Counter(m["label"] for m in msgs if m["label"])
    if lab:
        print("  Labels             : " + ", ".join(
            "%s x%d" % (printable(k), v) for k, v in lab.most_common(10)))
    # Everything below reads the message body, so it only makes sense on frames
    # the CRC accepted. A corrupted body yields plausible looking nonsense.
    good = [m for m in msgs if m["crc_ok"]]
    air = Counter()
    for m in good:
        for _, code, _ in find_flights(m["text"]):
            air[AIRLINE[code]] += 1
    if air:
        print("  Airlines           : " + ", ".join(
            "%s x%d" % (k, v) for k, v in air.most_common(8))
            + "   (valid CRC only)")
    dists = []
    for m in good:
        p = find_position(m["text"])
        if p:
            dists.append((haversine(*p), m["reg"], m["level"]))
    if dists:
        dists.sort()
        print("  Known positions    : %d" % len(dists))
        print("      closest        : %4.0f km  (%s at %+.1f dB)"
              % (dists[0][0], dists[0][1], dists[0][2]))
        print("      farthest       : %4.0f km  (%s at %+.1f dB)"
              % (dists[-1][0], dists[-1][1], dists[-1][2]))
        print("      MAXIMUM RANGE MEASURED: %.0f km" % dists[-1][0])


def main():
    global REF_LAT, REF_LON, REF_NAME
    p = argparse.ArgumentParser(
        description="ACARS message analyser: reads acarsdecv2 .txt logs and "
                    "explains each message field by field. Fully offline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="EXAMPLES\n"
               "  python3 analyse_acars.py acars_2026-07-28_*.txt\n"
               "  python3 analyse_acars.py log.txt --summary\n"
               "  python3 analyse_acars.py log.txt --reg C-FDCA\n"
               "  python3 analyse_acars.py log.txt --text BRAKE -n 5\n"
               "  python3 analyse_acars.py log.txt --positions\n")
    p.add_argument("files", nargs="+", help=".txt files produced by --log")
    p.add_argument("--summary", action="store_true",
                   help="print only the summary")
    p.add_argument("--positions", action="store_true",
                   help="list every reported position with distance, bearing and a map")
    p.add_argument("--reg", help="keep only this aircraft")
    p.add_argument("--label", help="keep only this label")
    p.add_argument("--text", help="keep only messages containing this text")
    p.add_argument("--crc-ok", action="store_true",
                   help="skip messages with an invalid CRC")
    p.add_argument("-n", type=int, metavar="N",
                   help="detail only the first N messages")
    p.add_argument("--pos", metavar="LAT,LON",
                   help="reference point for distances "
                        "(default: %.4f,%.4f)" % (REF_LAT, REF_LON))
    args = p.parse_args()
    n_ap, n_al = load_data()

    if args.pos:
        try:
            la, lo = args.pos.split(",")
            REF_LAT, REF_LON = float(la), float(lo)
            REF_NAME = "the given position"
        except ValueError:
            print("--pos expects LAT,LON, for example 45.4945,-73.5632")
            return 1

    paths = []
    for f in args.files:
        paths.extend(sorted(glob.glob(f)) or [f])
    msgs = []
    for path in paths:
        msgs.extend(parse_log(path))
    if not msgs:
        print("no message found in %d file(s)." % len(paths))
        return 1

    if args.reg:
        msgs = [m for m in msgs if m["reg"].upper() == args.reg.upper()]
    if args.label:
        msgs = [m for m in msgs if m["label"] == args.label]
    if args.text:
        msgs = [m for m in msgs if args.text.upper() in m["text"].upper()]
    if args.crc_ok:
        msgs = [m for m in msgs if m["crc_ok"]]
    if not msgs:
        print("no message matches the filters.")
        return 1

    print("analyse_acars v%s   %d file(s), %d message(s)"
          % (__version__, len(paths), len(msgs)))
    if n_ap or n_al:
        print("reference tables: %d airports, %d airlines (offline)"
              % (n_ap, n_al))
    if args.positions:
        positions(msgs)
        summary(msgs)
        return 0

    if not args.summary:
        shown = msgs[:args.n] if args.n else msgs
        for i, m in enumerate(shown, 1):
            show(m, i, len(msgs))
        if args.n and len(msgs) > args.n:
            print("\n(%d more message(s) not detailed, drop -n to see them all)"
                  % (len(msgs) - args.n))
    summary(msgs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
