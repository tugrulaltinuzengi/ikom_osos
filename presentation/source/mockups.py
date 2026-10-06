"""Rendered figures for the OSOS deck.

Two kinds of image are generated here:

  * phone screens — drawn from the real Compose source in
    osos_emu/android/app/src/main/java/com/osos/hmi/ui/, so the tile keys, tab
    names, gate thresholds and inspector layout match what the app actually
    puts on screen;
  * the neural-net figures — the MNIST strip is rendered from the *actual*
    IDX test set in neural_net_c/data/, not from invented pixels.

Everything is drawn at 3x and downsampled, because PowerPoint will scale these
up on a projector.
"""
import os
import struct

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(HERE, "figures")
os.makedirs(OUT, exist_ok=True)

S = 3  # supersample factor

# palette mirrored from theme_osos.py
PANEL = (0x0D, 0x11, 0x17)
PANEL2 = (0x16, 0x1C, 0x24)
PANEL3 = (0x1E, 0x26, 0x30)
HAIR = (0x2C, 0x36, 0x44)
HAIR2 = (0x3D, 0x4A, 0x5C)
LCD = (0x63, 0xD2, 0xE8)
LCD_D = (0x2E, 0x7D, 0x8E)
SEG = (0xFF, 0x44, 0x38)
UYARI = (0xFF, 0xA9, 0x28)
COPPER = (0xC8, 0x9A, 0x5B)
GREEN = (0x4A, 0xD9, 0x91)
TEXT = (0xE6, 0xED, 0xF3)
MUTED = (0x84, 0x94, 0xA6)
DIM = (0x5A, 0x68, 0x78)

FONTS = r"C:\Windows\Fonts"


def font(name, size):
    for cand in (name, name.lower()):
        p = os.path.join(FONTS, cand)
        if os.path.exists(p):
            return ImageFont.truetype(p, size * S)
    return ImageFont.load_default()


def sui(size):
    return font("segoeui.ttf", size)


def suib(size):
    return font("segoeuib.ttf", size)


def suisb(size):
    return font("seguisb.ttf", size)


def mono(size):
    return font("consola.ttf", size)


def monob(size):
    return font("consolab.ttf", size)


def rr(d, xy, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([xy[0] * S, xy[1] * S, xy[2] * S, xy[3] * S],
                        radius=r * S, fill=fill, outline=outline, width=width * S)


def rect(d, xy, fill=None, outline=None, width=1):
    d.rectangle([xy[0] * S, xy[1] * S, xy[2] * S, xy[3] * S],
                fill=fill, outline=outline, width=width * S)


def tx(d, xy, s, f, fill=TEXT, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)


def save(im, name):
    w, h = im.size
    im = im.resize((w // S, h // S), Image.LANCZOS)
    path = os.path.join(OUT, name)
    im.save(path)
    return path


# --------------------------------------------------------------- phone chrome
PW, PH = 300, 620          # logical phone size


def phone(title, subtitle=None, tab=0):
    """Phone body + app bar + bottom tab bar. Returns (image, draw)."""
    im = Image.new("RGB", (PW * S, PH * S), PANEL)
    d = ImageDraw.Draw(im)
    rr(d, (0, 0, PW - 1, PH - 1), 18, fill=(0x0A, 0x0E, 0x13), outline=HAIR2, width=1)
    # status bar
    tx(d, (14, 12), "09:41", mono(8), MUTED)
    tx(d, (PW - 14, 12), "LTE  ▮", mono(8), MUTED, anchor="ra")
    # app bar
    rect(d, (1, 28, PW - 2, 62), fill=PANEL2)
    rect(d, (1, 61, PW - 2, 62), fill=HAIR)
    tx(d, (14, 34), title, suisb(12), TEXT)
    if subtitle:
        tx(d, (14, 49), subtitle, mono(7.5), MUTED)
    # bottom bar
    rect(d, (1, PH - 44, PW - 2, PH - 2), fill=PANEL2)
    rect(d, (1, PH - 44, PW - 2, PH - 43), fill=HAIR)
    # Six tabs since the fleet work - Console was added and Commands shortened
    # to Cmds to keep the labels from colliding at this width.
    tabs = ["Monitor", "Draw", "Cmds", "Alarms", "Console", "Set"]
    step = (PW - 2) / len(tabs)
    for i, t in enumerate(tabs):
        cx = 1 + step * (i + 0.5)
        on = i == tab
        tx(d, (cx, PH - 26), t, suisb(7) if on else sui(7),
           LCD if on else DIM, anchor="ma")
        if on:
            rect(d, (cx - 13, PH - 36, cx + 13, PH - 34), fill=LCD)
    return im, d


def toggle(d, x, y, on, w=30, h=16):
    """Material-style switch, as used for sleep and each load channel."""
    rr(d, (x, y, x + w, y + h), h // 2,
       fill=LCD_D if on else PANEL3, outline=LCD if on else HAIR2, width=1)
    knob = x + w - h + 2 if on else x + 2
    rr(d, (knob, y + 2, knob + h - 4, y + h - 2), (h - 4) // 2,
       fill=LCD if on else MUTED)


def tile(d, x, y, w, h, key, value, unit, selected=False, null=False):
    rr(d, (x, y, x + w, y + h), 6, fill=PANEL2, outline=LCD if selected else HAIR,
       width=1)
    tx(d, (x + 9, y + 8), key, sui(7.5), MUTED)
    col = SEG if null else (LCD if selected else TEXT)
    tx(d, (x + 9, y + 20), value, mono(15), col)
    if unit:
        wv = d.textlength(value, font=mono(15)) / S
        tx(d, (x + 12 + wv, y + 28), unit, sui(8), MUTED)


# --------------------------------------------------------------- 1. Fleet tree
def fleet_tree():
    """Level one of the Monitor navigator: every modem, every analyzer, in
    the operator's own folders. Drawn from ui/FleetTreeScreen.kt."""
    im, d = phone("OSOS HMI", None, tab=0)
    tx(d, (PW - 14, 40), "● gateway online", mono(7.5), GREEN, anchor="ra")

    # master sleep row
    tx(d, (14, 74), "Master sleep", suisb(9.5), TEXT)
    toggle(d, PW - 46, 71, False)
    rect(d, (12, 96, PW - 12, 97), fill=HAIR)

    y = 106

    def folder(name, n):
        nonlocal y
        tx(d, (14, y), name.upper(), mono(7.5), COPPER)
        tx(d, (PW - 14, y), f"{n} analyzers", mono(7), DIM, anchor="ra")
        y += 16

    def modem(mid, state, tag=None):
        nonlocal y
        tx(d, (18, y), mid, suisb(9), TEXT)
        if tag:
            w = d.textlength(mid, font=suisb(9)) / S
            tx(d, (24 + w, y + 2), tag, mono(6.5), DIM)
        col = COPPER if state == "ASLEEP" else GREEN
        tx(d, (PW - 14, y + 1), state, mono(7.5), col, anchor="ra")
        y += 15

    def analyzer(name, volts, muted=False):
        nonlocal y
        tx(d, (32, y), name, sui(8.5), MUTED if muted else TEXT)
        tx(d, (PW - 56, y), volts, mono(8.5), DIM if muted else LCD, anchor="ra")
        tx(d, (PW - 16, y), "edit", sui(7.5), LCD_D, anchor="ra")
        y += 14

    folder("Saha-1", 4)
    modem("gw-01", "awake")
    analyzer("Ana Pano", "229.1 V")
    analyzer("Kompanzasyon", "230.1 V")
    analyzer("Jeneratör", "230.9 V")
    analyzer("an-04", "229.8 V")
    y += 6

    folder("Saha-2", 4)
    modem("gw-02", "ASLEEP")
    analyzer("Kazan Dairesi", "228.7 V", muted=True)
    analyzer("Soğutma", "230.1 V", muted=True)
    analyzer("an-03", "231.6 V", muted=True)
    analyzer("an-04", "230.4 V", muted=True)
    y += 6

    folder("Depo", 3)
    modem("gw-03", "awake")
    analyzer("Yükleme Rampası", "229.4 V")
    analyzer("an-02", "230.7 V")
    analyzer("an-03", "228.9 V")
    y += 6

    folder("Unfiled", 1)
    modem("dkm440-gw1", "awake", tag="v1")
    analyzer("an-0", "228.8 V")

    y += 10
    tx(d, (14, y), "+ new folder", sui(8.5), LCD)

    y += 20
    rect(d, (12, y, PW - 12, y + 1), fill=HAIR)
    y += 8
    tx(d, (14, y), "gw-02 asleep — 4 alarms muted, digest on wake",
       mono(7), COPPER)
    y += 13
    tx(d, (14, y), "names and folders are retained MQTT, not topic segments",
       mono(7), DIM)
    return save(im, "phone-fleet.png")


# ------------------------------------------------------- 1b. Modem detail
def modem_detail():
    """Level two: one modem's own state. Sleep, and the four load channels.
    Drawn from ui/ModemDetailScreen.kt."""
    im, d = phone("gw-01", "192.169.10.75 · fw 0.4.0 · rssi -46", tab=0)
    tx(d, (PW - 14, 40), "● online", mono(7.5), GREEN, anchor="ra")

    y = 74
    tx(d, (14, y), "Sleep", suisb(9.5), TEXT)
    toggle(d, PW - 46, y - 3, False)
    y += 18
    tx(d, (14, y), "interval 5 s · awake since 09:12", mono(7), MUTED)
    y += 22
    rect(d, (12, y, PW - 12, y + 1), fill=HAIR)

    y += 10
    tx(d, (14, y), "LOAD CHANNELS", mono(7.5), SEG)
    tx(d, (PW - 14, y), "observed, not requested", mono(6.5), DIM, anchor="ra")
    y += 18
    loads = [("ch1", "D5 / GPIO14", False), ("ch2", "D6 / GPIO12", False),
             ("ch3", "D7 / GPIO13", True), ("ch4", "D1 / GPIO5", False)]
    for ch, pin, on in loads:
        rr(d, (12, y, PW - 12, y + 34), 6, fill=PANEL2,
           outline=SEG if on else HAIR, width=1)
        tx(d, (22, y + 7), ch, suisb(9), SEG if on else TEXT)
        tx(d, (22, y + 20), pin, mono(7), MUTED)
        toggle(d, PW - 52, y + 9, on)
        y += 40

    y += 4
    tx(d, (14, y), "off on boot — never persisted", mono(7), COPPER)

    y += 20
    rect(d, (12, y, PW - 12, y + 1), fill=HAIR)
    y += 10
    tx(d, (14, y), "ANALYZERS", mono(7.5), LCD)
    y += 16
    for aid, host, v in [("an-01", "192.169.10.100", "229.1 V"),
                         ("an-02", "192.169.10.101", "230.1 V"),
                         ("an-03", "192.169.10.102", "230.9 V")]:
        tx(d, (18, y), aid, sui(8.5), TEXT)
        tx(d, (64, y + 1), host, mono(7), DIM)
        tx(d, (PW - 16, y), v, mono(8.5), LCD, anchor="ra")
        y += 15

    y += 8
    # Consolas has no U+2713, so it renders as a tofu box. Spell it.
    tx(d, (14, y), "last ack  ok: ch3 on", mono(7.5), GREEN)
    return save(im, "phone-modem.png")


# --------------------------------------------------------------- 1c. Monitor
def monitor():
    im, d = phone("osos-hmi", "gw-01 · an-01  ·  Ana Pano", tab=0)
    tx(d, (14, 72), "seq 4127 · 2026-08-03T11:20:05Z · meter ok", mono(7.5), GREEN)

    tabs = ["overview", "L1", "L2", "L3", "power"]
    x = 12
    for i, t in enumerate(tabs):
        w = d.textlength(t, font=sui(8)) / S + 14
        on = i == 0
        tx(d, (x + w / 2, 92), t, suisb(8) if on else sui(8), LCD if on else DIM,
           anchor="ma")
        if on:
            rect(d, (x + 4, 106, x + w - 4, 108), fill=LCD)
        x += w
    rect(d, (12, 107, PW - 12, 108), fill=HAIR)

    rows = [
        [("Voltage L1", "0.00", "V", False), ("Voltage L2", "0.00", "V", False)],
        [("Voltage L3", "0.00", "V", False), ("Current L1", "0.00", "A", False)],
        [("Current L2", "0.00", "A", False), ("Freq L1", "0.00", "Hz", False)],
        [("Supply Voltage", "23.35", "V", True), ("Current N", "—", "", "null")],
    ]
    y = 118
    for r in rows:
        x = 12
        for key, val, unit, sel in r:
            tile(d, x, y, 133, 46, key, val, unit,
                 selected=(sel is True), null=(sel == "null"))
            x += 139
        y += 52

    # sparkline card for the selected tile
    rr(d, (12, y, PW - 12, y + 92), 6, fill=PANEL2, outline=HAIR, width=1)
    tx(d, (21, y + 8), "Supply Voltage — 720 pts · min 23.31 · max 23.38",
       sui(7), MUTED)
    pts = [23.35, 23.36, 23.34, 23.35, 23.37, 23.33, 23.35, 23.36, 23.34,
           23.35, 23.38, 23.35, 23.34, 23.36, 23.35, 23.33, 23.35, 23.36]
    x0, x1 = 21, PW - 21
    y0, y1 = y + 26, y + 82
    mn, mx = min(pts), max(pts)
    path = []
    for i, v in enumerate(pts):
        px = x0 + (x1 - x0) * i / (len(pts) - 1)
        py = y1 - (y1 - y0) * (v - mn) / (mx - mn)
        path.append((px * S, py * S))
    d.line(path, fill=LCD, width=2 * S, joint="curve")

    y += 100
    tx(d, (14, y), "Log", suisb(8.5), TEXT)
    log = [("[11:20:05] mqtt: telemetry seq 4127  22/22", MUTED),
           ("[11:20:00] mqtt: telemetry seq 4126  22/22", MUTED),
           ("[11:19:55] mqtt: telemetry seq 4125  22/22", MUTED),
           ("[11:19:50] mqtt: telemetry seq 4124  22/22", MUTED),
           ("[11:19:45] mqtt: telemetry seq 4123  22/22", MUTED),
           ("[11:19:40] status: online fw 0.3.0 rssi -46", DIM),
           ("[11:19:40] mqtt: connected 8883 tls1.3", GREEN),
           ("[11:19:38] wifi: your-ssid  192.169.10.75", DIM)]
    y += 16
    for t, c in log:
        tx(d, (14, y), t, mono(7), c)
        y += 12
    return save(im, "phone-monitor.png")


# --------------------------------------------------------------- 2. Draw
def draw_screen():
    im, d = phone("osos-hmi", "draw a symbol · 650 ms pen-up recognises", tab=1)
    tx(d, (14, 72), "0 ping · 1 read now · 2 fast 2s · 3 normal 10s",
       mono(6.5), DIM)
    tx(d, (14, 82), "4 L1 · 5 L2 · 6 L3 · 7 overview · 8 power", mono(6.5), DIM)

    # canvas — square, and small enough that the gate card and the inspector
    # both stay on screen; the real app scrolls, a still image cannot
    side = PW - 28 - 62
    pad = (14 + 31, 96, PW - 14 - 31, 96 + side)
    rr(d, pad, 8, fill=(0x00, 0x00, 0x00), outline=HAIR2, width=1)
    # a hand-drawn "1"
    cx = (pad[0] + pad[2]) / 2
    y0 = pad[1] + side * 0.18
    stroke = [(cx - 22, y0 + 16), (cx - 6, y0), (cx - 1, y0 - 2),
              (cx, y0 + 36), (cx + 1, y0 + 72), (cx + 2, y0 + 104)]
    d.line([(p[0] * S, p[1] * S) for p in stroke], fill=(255, 255, 255),
           width=12 * S, joint="curve")

    y = pad[3] + 10
    rr(d, (14, y, 66, y + 26), 13, fill=None, outline=HAIR2, width=1)
    tx(d, (40, y + 8), "Clear", sui(8.5), TEXT, anchor="ma")
    # 28x28 preview
    rect(d, (76, y, 102, y + 26), fill=(0x00, 0x00, 0x00), outline=HAIR)
    d.line([(89 * S, (y + 5) * S), (89 * S, (y + 21) * S)], fill=(255, 255, 255),
           width=3 * S)
    tx(d, (110, y + 9), "28×28 · preprocessed", mono(7), DIM)

    # the safety gate
    y += 36
    rr(d, (14, y, PW - 14, y + 62), 6, fill=PANEL2, outline=UYARI, width=1)
    tx(d, (24, y + 9), "digit 1  →  read now", suisb(9.5), TEXT)
    tx(d, (24, y + 24), "scope=gateway · confirm required", mono(7), UYARI)
    rr(d, (24, y + 36, 74, y + 54), 9, fill=LCD)
    tx(d, (49, y + 41), "Send", suib(8.5), PANEL, anchor="ma")
    rr(d, (82, y + 36, 138, y + 54), 9, outline=HAIR2, width=1)
    tx(d, (110, y + 41), "Cancel", sui(8.5), MUTED, anchor="ma")

    # inspector
    y += 72
    rr(d, (14, y, PW - 14, PH - 54), 6, fill=PANEL2, outline=HAIR, width=1)
    tx(d, (24, y + 8), "Classifier inspector", suisb(9), TEXT)
    tx(d, (24, y + 23), "digits (MLP 784-128-10, gate ≥ 90%)", sui(7), MUTED)
    rows = [("1", "99.2", 10, LCD), ("7", "0.5", 0, MUTED), ("4", "0.2", 0, MUTED)]
    yy = y + 36
    for dg, p, bars, c in rows:
        tx(d, (26, yy), f"  {dg}  {p:>5}%  " + "█" * bars, mono(7.5), c)
        yy += 11
    tx(d, (24, yy + 4), "custom symbols — trained head (gate ≥ 85% + cos ≥ 0.80)",
       sui(6.5), MUTED)
    yy += 17
    for nm, hp, cb in [("valf", " 2.1", "0.412"), ("kesici", " 0.8", "0.301")]:
        tx(d, (26, yy), f"  {nm:<10} head {hp:>5}%  cos best {cb}", mono(7), DIM)
        yy += 11
    return save(im, "phone-draw.png")


# --------------------------------------------------------------- 3. Commands
def commands():
    im, d = phone("Commands", "digit map + learned symbols", tab=2)
    y = 74
    tx(d, (14, y), "Digit commands (MNIST)", suisb(9), TEXT)
    y += 18
    digits = [
        ("0", "ping gateway", "gateway", UYARI),
        ("1", "read now", "gateway", UYARI),
        ("2", "fast reporting (2 s)", "gateway", UYARI),
        ("3", "normal reporting (10 s)", "gateway", UYARI),
        ("4", "show L1", "local", LCD),
        ("5", "show L2", "local", LCD),
        ("6", "show L3", "local", LCD),
        ("7", "overview", "local", LCD),
        ("8", "power factors", "local", LCD),
        ("9", "reserved", "none", DIM),
    ]
    for dg, lab, scope, c in digits:
        tx(d, (18, y), dg, monob(9), c)
        tx(d, (34, y), lab, sui(8), TEXT if scope != "none" else DIM)
        tx(d, (PW - 18, y), scope, mono(7), c, anchor="ra")
        y += 15
        rect(d, (14, y - 3, PW - 14, y - 2.5), fill=HAIR)

    y += 8
    tx(d, (14, y), "Custom commands", suisb(9), TEXT)
    y += 18
    for nm, n, act in [("valf", 14, "read now"), ("kesici", 11, "ping gateway")]:
        rr(d, (14, y, PW - 14, y + 34), 6, fill=PANEL2, outline=HAIR, width=1)
        tx(d, (24, y + 7), nm, suisb(9), COPPER)
        tx(d, (24, y + 21), f"{n}/15 samples · head trained", mono(7), MUTED)
        tx(d, (PW - 24, y + 13), act, mono(7.5), LCD, anchor="ra")
        y += 40

    rr(d, (14, y, PW - 14, y + 28), 14, fill=None, outline=COPPER, width=1)
    tx(d, (PW / 2, y + 9), "+  Add command", suisb(9), COPPER, anchor="ma")
    return save(im, "phone-commands.png")


# --------------------------------------------------------------- 4. Alarms
def alarms():
    im, d = phone("Alarms", "evaluated on the telemetry stream", tab=3)
    y = 74
    tx(d, (14, y), "Active", suisb(9), TEXT)
    y += 18
    rr(d, (14, y, PW - 14, y + 46), 6, fill=(0x2A, 0x14, 0x12), outline=SEG,
       width=1)
    tx(d, (24, y + 8), "meter link FAULT for ≥30s", suisb(9), SEG)
    tx(d, (24, y + 24), "since 11:18:40 · builtin-meter", mono(7), MUTED)
    y += 56

    tx(d, (14, y), "Rules", suisb(9), TEXT)
    y += 18
    rules = [
        ("Voltage L1", "207.00 … 253.00", "30 s", True),
        ("Voltage L2", "207.00 … 253.00", "30 s", True),
        ("Voltage L3", "207.00 … 253.00", "30 s", True),
        ("Freq L1", "49.50 … 50.50", "10 s", True),
        ("Supply Voltage", "22.00 … 26.00", "60 s", False),
    ]
    for key, rng, hold, on in rules:
        rr(d, (14, y, PW - 14, y + 40), 6, fill=PANEL2, outline=HAIR, width=1)
        tx(d, (24, y + 7), key, suisb(8.5), TEXT if on else DIM)
        tx(d, (24, y + 22), f"outside [{rng}] for ≥ {hold}", mono(7),
           MUTED if on else DIM)
        # toggle
        col = LCD if on else HAIR2
        rr(d, (PW - 58, y + 13, PW - 26, y + 29), 8, fill=col)
        knob = PW - 33 if on else PW - 51
        d.ellipse([(knob - 6) * S, (y + 15) * S, (knob + 6) * S, (y + 27) * S],
                  fill=PANEL)
        y += 46

    y += 4
    rr(d, (14, y, PW - 14, y + 28), 14, outline=LCD, width=1)
    tx(d, (PW / 2, y + 9), "+  Add rule", suisb(9), LCD, anchor="ma")

    y += 40
    tx(d, (14, y), "Built-in, always on:", sui(7.5), MUTED)
    for t in ["meter_ok == false for ≥ 30 s",
              "gateway LWT reports offline",
              "no telemetry for > 3× interval"]:
        y += 12
        tx(d, (18, y), "— " + t, mono(6.5), DIM)
    return save(im, "phone-alarms.png")


# --------------------------------------------------------------- MNIST strip
def mnist_strip(n=10, cell=64, gap=6):
    """Real digits, read straight out of the IDX test set the trainer eats."""
    img_path = os.path.join(ROOT, "source", "neural-net-c", "data", "t10k-images-idx3-ubyte")
    lbl_path = os.path.join(ROOT, "source", "neural-net-c", "data", "t10k-labels-idx1-ubyte")
    with open(img_path, "rb") as f:
        magic, count, rows, cols = struct.unpack(">IIII", f.read(16))
        raw = f.read(count * rows * cols)
    with open(lbl_path, "rb") as f:
        f.read(8)
        labels = f.read(count)

    # first occurrence of each digit 0..9, so the strip is legible
    picks = []
    for want in range(n):
        for i in range(count):
            if labels[i] == want:
                picks.append(i)
                break

    W = n * cell + (n - 1) * gap
    H = cell + 22
    im = Image.new("RGB", (W * S, H * S), PANEL)
    d = ImageDraw.Draw(im)
    for j, idx in enumerate(picks):
        px = raw[idx * 784:(idx + 1) * 784]
        tile_im = Image.frombytes("L", (28, 28), px).resize(
            (cell * S, cell * S), Image.NEAREST)
        # tint the greyscale into LCD cyan so it belongs to the deck
        tinted = Image.merge("RGB", (
            tile_im.point(lambda v: int(v * LCD[0] / 255)),
            tile_im.point(lambda v: int(v * LCD[1] / 255)),
            tile_im.point(lambda v: int(v * LCD[2] / 255)),
        ))
        x = j * (cell + gap)
        im.paste(tinted, (x * S, 0))
        d.rectangle([x * S, 0, (x + cell) * S - 1, cell * S - 1], outline=HAIR,
                    width=1 * S)
        tx(d, (x + cell / 2, cell + 6), str(labels[idx]), mono(9), MUTED,
           anchor="ma")
    return save(im, "mnist-strip.png")


def mnist_pipeline(cell=104):
    """One drawn stroke walked through the eight preprocessing steps."""
    img_path = os.path.join(ROOT, "source", "neural-net-c", "data", "t10k-images-idx3-ubyte")
    with open(img_path, "rb") as f:
        struct.unpack(">IIII", f.read(16))
        raw = f.read(784 * 20)
    px = raw[2 * 784:3 * 784]          # a '1'

    stages = ["280×280 canvas", "threshold 25", "crop to ink", "fit 20 px",
              "CoM centre 28×28"]
    gap = 30
    W = len(stages) * cell + (len(stages) - 1) * gap
    H = cell + 26
    im = Image.new("RGB", (W * S, H * S), PANEL)
    d = ImageDraw.Draw(im)

    base = Image.frombytes("L", (28, 28), px)
    variants = []
    # 1. the raw 280x280 canvas: a fat antialiased finger stroke, off-centre.
    #    Drawn big then shrunk so the edges carry real grey — that grey is the
    #    whole reason step 2 exists.
    canvas = Image.new("L", (280, 280), 0)
    cd = ImageDraw.Draw(canvas)
    cd.line([(96, 96), (128, 62), (140, 58), (144, 150), (148, 232)],
            fill=255, width=20, joint="curve")
    v0 = canvas.resize((28, 28), Image.BILINEAR)
    variants.append(v0)
    # 2. thresholded at 25 — grey edges become hard ink
    variants.append(v0.point(lambda v: 255 if v > 25 else 0))
    # 3. crop to the ink bounding box — aspect preserved, letterboxed, so the
    #    step reads as "we found the ink" and not "we stretched it"
    bb = variants[1].getbbox()
    ink = variants[1].crop(bb)
    iw, ih = ink.size
    k = min(26 / iw, 26 / ih)
    shown = ink.resize((max(1, int(iw * k)), max(1, int(ih * k))), Image.NEAREST)
    v2 = Image.new("L", (28, 28), 0)
    v2.paste(shown, ((28 - shown.width) // 2, (28 - shown.height) // 2))
    variants.append(v2)
    # 4. block-average the longer side down to 20 px, aspect kept, corner-placed
    k = 20 / max(iw, ih)
    small = ink.resize((max(1, round(iw * k)), max(1, round(ih * k))),
                       Image.BILINEAR)
    v3 = Image.new("L", (28, 28), 0)
    v3.paste(small, (3, 3))
    variants.append(v3)
    # 5. shift so the centre of mass lands in the middle of the 28x28 field —
    #    the same stroke as every stage before it, only translated
    px3 = list(v3.getdata())
    tot = sum(px3) or 1
    cx = sum((i % 28) * v for i, v in enumerate(px3)) / tot
    cy = sum((i // 28) * v for i, v in enumerate(px3)) / tot
    v4 = Image.new("L", (28, 28), 0)
    v4.paste(v3, (round(13.5 - cx), round(13.5 - cy)))
    variants.append(v4)

    for j, (lab, v) in enumerate(zip(stages, variants)):
        big = v.resize((cell * S, cell * S), Image.NEAREST)
        tinted = Image.merge("RGB", (
            big.point(lambda q: int(q * LCD[0] / 255)),
            big.point(lambda q: int(q * LCD[1] / 255)),
            big.point(lambda q: int(q * LCD[2] / 255)),
        ))
        x = j * (cell + gap)
        im.paste(tinted, (x * S, 0))
        d.rectangle([x * S, 0, (x + cell) * S - 1, cell * S - 1], outline=HAIR2,
                    width=1 * S)
        tx(d, (x + cell / 2, cell + 8), lab, mono(8), MUTED, anchor="ma")
        if j < len(stages) - 1:
            ax = x + cell + gap / 2
            d.line([((x + cell + 6) * S, cell / 2 * S),
                    ((x + cell + gap - 6) * S, cell / 2 * S)],
                   fill=HAIR2, width=2 * S)
            d.polygon([((x + cell + gap - 6) * S, cell / 2 * S),
                       ((x + cell + gap - 12) * S, (cell / 2 - 4) * S),
                       ((x + cell + gap - 12) * S, (cell / 2 + 4) * S)],
                      fill=HAIR2)
    return save(im, "mnist-pipeline.png")


# --------------------------------------------------------------- MLP diagram
def mlp_diagram(W=760, H=300):
    """784 → 128 (ReLU) → 10 (softmax), drawn to scale in spirit: the input
    column is sampled, not enumerated, and that is said out loud on the slide."""
    im = Image.new("RGB", (W * S, H * S), PANEL)
    d = ImageDraw.Draw(im)

    cols = [
        (110, 14, "input", "784", "28×28 pixels ÷ 255", MUTED),
        (380, 10, "hidden", "128", "ReLU", LCD),
        (650, 10, "output", "10", "softmax", COPPER),
    ]
    top, bot = 46, H - 58
    pos = []
    for cx, n, name, count, sub, col in cols:
        ys = [top + (bot - top) * i / (n - 1) for i in range(n)]
        pos.append((cx, ys, col))

    # edges — every pair would be a grey wash, so draw a sparse sample and say
    # so; the point is "fully connected", not the literal count
    for (x0, y0s, _), (x1, y1s, c1) in zip(pos, pos[1:]):
        for ai, a in enumerate(y0s):
            for bi, b in enumerate(y1s):
                if (ai + bi) % 2:
                    continue
                d.line([(x0 * S, a * S), (x1 * S, b * S)],
                       fill=(0x1B, 0x22, 0x2C), width=1)
    for (cx, ys, col), (_, n, name, count, sub, _) in zip(pos, cols):
        for y in ys:
            d.ellipse([(cx - 6) * S, (y - 6) * S, (cx + 6) * S, (y + 6) * S],
                      fill=PANEL2, outline=col, width=2 * S)
        tx(d, (cx, 12), count, monob(15), col, anchor="ma")
        tx(d, (cx, H - 40), name.upper(), suisb(9), TEXT, anchor="ma")
        tx(d, (cx, H - 26), sub, mono(8), MUTED, anchor="ma")

    # the two weight matrices, named exactly as nn.cpp names them. Plated, or
    # the edge mesh swallows them.
    for lx, l1, l2 in ((245, "W¹  128×784", "+ b¹  128"),
                       (515, "W²  10×128", "+ b²  10")):
        d.rectangle([(lx - 62) * S, 142 * S, (lx + 62) * S, 180 * S], fill=PANEL)
        tx(d, (lx, 146), l1, monob(9.5), TEXT, anchor="ma")
        tx(d, (lx, 162), l2, mono(9), MUTED, anchor="ma")
    tx(d, (W - 12, H - 14), "input column sampled for legibility",
       mono(7.5), DIM, anchor="ra")
    return save(im, "mlp-diagram.png")


if __name__ == "__main__":
    for fn in (fleet_tree, modem_detail, monitor, draw_screen, commands,
               alarms, mnist_strip, mnist_pipeline, mlp_diagram):
        print("wrote", fn())
