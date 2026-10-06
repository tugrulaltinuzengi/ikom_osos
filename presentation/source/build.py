"""Build OSOS-Delivery.pptx — the 2026-08-06 delivery deck.

    python build.py

Content is drawn from the repository's own documents, so the deck cannot drift
from the specs: SRS-00, docs/BENCH.md, docs/VOLTAGE_ACCURACY.md,
docs/IKOM_APPLICATIONS.md, firmware8266/README.md, docs/ANDROID_APP.md,
neural_net_c/EXPLANATION.md and modbus/dkm_440_mapping/METHOD.md.
"""
import os
import sys

from PIL import Image, ImageEnhance
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

import theme_osos as T

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
IMG = os.path.join(ROOT, "reference", "photos")
FIG = os.path.join(HERE, "figures")
OUTFILE = os.path.join(HERE, "OSOS-Delivery.pptx")

n = 0          # slide counter, drives the footer


def num():
    global n
    n += 1
    return n


# ------------------------------------------------------------------ hero crop
def hero(src, dst, box, dark=0.55, w=1400):
    """Crop a bench photo to a slide panel and dim it so text can sit on top."""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    im = im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))
    im = im.resize((w, int(w * im.size[1] / im.size[0])), Image.LANCZOS)
    im = ImageEnhance.Brightness(im).enhance(dark)
    im = ImageEnhance.Color(im).enhance(0.85)
    p = os.path.join(FIG, dst)
    im.save(p, quality=92)
    return p


def photo_card(s, path, x, y, h, cap=None, crop=None):
    """A bench photo in a hairline frame with a monospaced caption under it."""
    im = Image.open(path)
    if crop:
        W, H = im.size
        im = im.crop((int(crop[0] * W), int(crop[1] * H),
                      int(crop[2] * W), int(crop[3] * H)))
        path = os.path.join(FIG, "_crop_" + os.path.basename(path))
        im.save(path, quality=92)
    w = h * im.size[0] / im.size[1]
    T.box(s, x - 0.045, y - 0.045, w + 0.09, h + 0.09, fill=T.PANEL2, line=T.HAIR)
    T.picture(s, path, x, y, h=h)
    if cap:
        T.caption(s, x - 0.045, y + h + 0.14, w + 0.4, cap)
    return w


# =========================================================== 01 · title
def s_title(prs):
    s = T.blank(prs)
    T.bg(s)
    p = hero(os.path.join(IMG, "dkm440-front.jpg"), "hero-dkm.jpg",
             (0.10, 0.06, 0.95, 0.94), dark=0.62, w=1200)
    T.picture(s, p, 8.15, 0, h=7.5)
    # left-edge gradient substitute: a soft stack of panels feathering the photo
    for i, a in enumerate([0.0, 0.25, 0.5, 0.75]):
        T.box(s, 8.15 + i * 0.16, 0, 0.17, 7.5,
              fill=T.PANEL if i == 0 else T.PANEL2)
    T.box(s, 8.15, 0, 0.16, 7.5, fill=T.PANEL)
    T.box(s, 8.79, 0, Pt(1.0).inches, 7.5, fill=T.HAIR)

    T.box(s, 0, 0, 0.16, 7.5, fill=T.LCD)
    T.text(s, 0.95, 1.32, 7.4, 0.3, "IKOM  ·  STAJ TESLİMİ  ·  2026-08-06",
           size=10.5, color=T.LCD, font=T.MONO)
    T.text(s, 0.92, 1.82, 7.6, 2.2,
           "Reading a power\nanalyser from a phone",
           size=44, color=T.TEXT, font=T.DISP, spacing=1.0)
    T.rule(s, 0.95, 3.72, 1.6, color=T.LCD, weight=2.5)
    T.text(s, 0.95, 4.06, 7.0, 1.5,
           "A DATAKOM DKM-440 is read over Modbus TCP, republished as JSON over\n"
           "MQTT/TLS, and displayed on an Android phone — where a from-scratch\n"
           "C++ neural network turns a hand-drawn symbol into a gateway command.",
           size=14, color=T.MUTED, font=T.BODY, spacing=1.45)

    ch = [("DKM-440", T.LCD), ("ESP8266", T.LCD), ("EMQX / TLS 1.3", T.LCD),
          ("Android", T.LCD), ("C++17 MLP", T.COPPER)]
    x = 0.95
    for lab, c in ch:
        w = 0.16 + len(lab) * 0.088
        T.chip(s, x, 5.66, w, 0.32, lab, c)
        x += w + 0.16
    T.text(s, 0.95, 5.20, 7.4, 0.3,
           "Industrial telemetry is taught in slices; this bench is the whole "
           "path, on one desk.",
           size=11.5, color=T.LCD, font=T.BODY, spacing=1.3)
    T.text(s, 0.95, 6.45, 7.0, 0.3,
           "Every figure in this deck is a measured value from the bench, or it "
           "is labelled as unproven.", size=10.5, color=T.DIM, font=T.MONO,
           spacing=1.3)
    return s


# =========================================================== 02 · what exists
def s_summary(prs):
    s = T.content(prs, "What runs today", "verified end to end · 2026-07-28",
                  active=("meter", "gw", "broker", "phone"))

    # the chain, drawn as five panels on one rail
    y = 1.80
    nodes = [
        ("DKM-440", "192.169.10.74:502\nModbus TCP · unit 1", T.LCD),
        ("ESP8266", "192.169.10.75\nWi-Fi · gateway", T.LCD),
        ("EMQX", "…emqxsl.com:8883\nTLS 1.3 · retained + LWT", T.LCD),
        ("osos-hmi", "Android · Kotlin\nlive tiles · alarms", T.LCD),
    ]
    w, gap = 2.72, 0.35
    for i, (title, sub, c) in enumerate(nodes):
        x = 0.70 + i * (w + gap)
        T.card(s, x, y, w, 1.30, accent=c)
        T.text(s, x + 0.22, y + 0.28, w - 0.44, 0.3, title, size=15,
               color=T.TEXT, font=T.DISP)
        T.text(s, x + 0.22, y + 0.62, w - 0.44, 0.5, sub, size=9,
               color=T.MUTED, font=T.MONO, spacing=1.3)
        if i < len(nodes) - 1:
            T.arrow(s, x + w + 0.04, y + 0.72, x + w + gap - 0.04, y + 0.72,
                    color=T.LCD_D, width=1.75)
    for i, lab in enumerate(("Modbus\nTCP", "MQTT\nTLS", "MQTT\nsub")):
        lx = 0.70 + (i + 1) * (w + gap) - gap
        T.text(s, lx - 0.28, y + 0.16, gap + 0.56, 0.4, lab, size=7.5,
               color=T.DIM, font=T.MONO, align=PP_ALIGN.CENTER, spacing=1.2)

    T.rule(s, 0.70, 3.52, 11.93, color=T.HAIR)

    stats = [
        ("22 / 22", "registers per cycle", "15 consecutive cycles"),
        ("5 s", "report interval", "fixed read budget"),
        ("TLS 1.3", "to the broker", "DigiCert G2 verified"),
        ("97.65 %", "MNIST test accuracy", "784-128-10, from scratch"),
    ]
    for i, (v, lab, sub) in enumerate(stats):
        x = 0.70 + i * 3.02
        col = T.COPPER if i == 3 else T.LCD
        T.stat(s, x, 3.82, 2.9, v, lab, color=col, size=30, sub=sub)
        if i:
            T.vrule(s, x - 0.24, 3.86, 0.98, color=T.HAIR)

    T.rule(s, 0.70, 5.30, 11.93, color=T.HAIR)
    T.bullets(s, 0.70, 5.52, 11.93, 1.3, [
        ("Cross-checked, not self-reported.",
         "A PC-side Modbus client read the same value the gateway published, "
         "in the same second."),
        ("The meter cannot move.",
         "Its address is a DHCP reservation on MAC xx-xx-xx-xx-xx-xx, because "
         "CFG_METER_HOST is a compile-time constant."),
    ], size=12)
    T.footer(s, num())
    return s


# =========================================================== 03 · why
def s_why(prs):
    s = T.content(prs, "Why build it at all", "the brief behind the bench",
                  active=("meter", "gw", "broker", "phone", "net"))

    y = T.block(s, 0.70, 1.70, 6.5,
                "Because there is nowhere\nto practise this.",
                size=26, color=T.LCD, font=T.DISP, spacing=1.14, gap=0.34)
    T.block(s, 0.70, y, 6.5,
            "Industrial telemetry is taught in slices — a serial lecture here, "
            "a protocol chapter there, a cloud broker in a different course "
            "entirely. Nobody hands a newcomer the whole path from a physical "
            "register to a pixel on a phone and says: make it work.\n\n"
            "This bench is that path, compressed onto one desk, with real "
            "hardware that misbehaves in real ways. It is an emulation ground "
            "for someone starting in this field — including the person who "
            "built it.",
            size=13, color=T.MUTED, spacing=1.5)

    T.card(s, 7.72, 1.72, 4.91, 4.62)
    T.text(s, 7.98, 1.96, 4.4, 0.3, "WHAT A NEWCOMER MEETS HERE", size=9,
           color=T.LCD, font=T.DISP)
    T.rule(s, 7.98, 2.28, 4.4, color=T.HAIR2)
    items = [
        ("A device that punishes impatience",
         "the DKM-440 stops answering a master that fires back to back"),
        ("A protocol with no self-description",
         "Modbus gives you a number; the meaning lives in a PDF"),
        ("A network that lies quietly",
         "a DHCP lease moved four times and blinded the gateway each time"),
        ("A chip with one UART",
         "the constraint that chose the entire architecture"),
        ("A model that is only probably right",
         "and sits in front of an industrial actuator"),
    ]
    y = 2.46
    for head, body in items:
        T.box(s, 7.98, y + 0.055, 0.075, 0.075, fill=T.LCD)
        T.text(s, 8.18, y, 4.2, 0.24, head, size=11.5, color=T.TEXT,
               font=T.BODY, bold=True)
        yy = T.block(s, 8.18, y + 0.245, 4.2, body, size=9.5, color=T.MUTED,
                     font=T.MONO, spacing=1.28)
        y = yy + 0.24

    T.rule(s, 0.70, 5.72, 6.5, color=T.HAIR)
    T.text(s, 0.70, 5.92, 6.6, 0.8,
           "Every one of those is a lesson that does not survive a simulator. "
           "That is the argument for hardware.",
           size=11, color=T.DIM, font=T.MONO, spacing=1.4)
    T.footer(s, num())
    return s


# =========================================================== 04 · divider
def d_bench(prs):
    s = T.divider(prs, "part one", "The bench",
                  "Three instruments, one subnet, and a supply whose dial is the "
                  "only thing on the bench that can move.",
                  accent=T.LCD, active=("meter",))
    T.footer(s, num())
    return s


# =========================================================== 05 · hardware
def s_bench(prs):
    s = T.content(prs, "The hardware", "photographed 2026-07-28",
                  active=("meter", "gw"))
    h = 3.15
    x = 0.70
    for fn, cap in (
        ("dkm440-front.jpg",
         "DATAKOM DKM-440 · Ver 10.1\nRJ45 top edge — Modbus TCP :502"),
        ("bench-psu.jpg",
         "CLASS 305D · 23.35 V @ 0.157 A\nvariable — the dial is not a constant"),
        ("esp8266-nodemcu.jpg",
         "Ai-Thinker ESP-8266MOD · COM11\n802.11 b/g/n — the WAN bridge"),
    ):
        w = photo_card(s, os.path.join(IMG, fn), x, 1.78, h, cap)
        x += w + 0.40

    T.card(s, 9.55, 1.74, 3.08, 3.96)
    T.text(s, 9.79, 1.96, 2.6, 0.26, "THE SUBNET", size=9, color=T.LCD,
           font=T.DISP)
    T.rule(s, 9.79, 2.26, 2.6, color=T.HAIR2)
    net = [("router", "192.169.10.1"), ("bench PC", ".72  DHCP"),
           ("DKM-440", ".74  reserved"), ("ESP8266", ".75  DHCP")]
    y = 2.44
    for k, v in net:
        T.text(s, 9.79, y, 1.15, 0.24, k, size=10, color=T.MUTED, font=T.BODY)
        T.text(s, 10.90, y, 1.6, 0.24, v, size=10, color=T.TEXT, font=T.MONO)
        y += 0.34
    T.rule(s, 9.79, y + 0.04, 2.6, color=T.HAIR)
    T.text(s, 9.79, y + 0.22, 2.6, 0.24, "SSID your-ssid", size=9.5,
           color=T.MUTED, font=T.MONO)
    T.text(s, 9.79, y + 0.48, 2.6, 0.24, "RSSI −46 dBm", size=9.5,
           color=T.MUTED, font=T.MONO)
    T.block(s, 9.79, y + 0.86, 2.6,
            "192.169.x.x is not private address space — 192.168 was meant. It "
            "only shadows real hosts inside that block, so it stays. Recorded "
            "so nobody rediscovers it.",
            size=9, color=T.DIM, spacing=1.35)

    T.rule(s, 0.70, 5.72, 8.55, color=T.HAIR)
    T.rich(s, 0.70, 5.92, 8.55, 1.0, [[
        ("The meter is LAN-only and has no business on the internet.  ",
         T.TEXT, T.BODY, True, 12),
        ("The ESP8266 is the one controlled egress point: it translates "
         "registers into JSON and speaks outward to a broker, so nothing "
         "on the internet ever addresses the meter.", T.MUTED, T.BODY, False, 12),
    ]], spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 06 · the meter
def s_meter(prs):
    s = T.content(prs, "Reading the panel honestly",
                  "why two alarm lamps are lit and nothing is wrong",
                  active=("meter",))
    photo_card(s, os.path.join(IMG, "dkm440-front.jpg"), 0.70, 1.80, 2.30,
               crop=(0.12, 0.66, 0.98, 0.97),
               cap="the status LEDs, bottom edge of the panel")

    T.text(s, 6.00, 1.74, 6.63, 0.3, "THE FOUR LAMPS", size=9, color=T.LCD,
           font=T.DISP)
    T.rule(s, 6.00, 2.02, 6.63, color=T.HAIR2)
    lamps = [("ENERJİ", "off", "energy accumulation", T.DIM),
             ("HABERL.", "off", "communications", T.DIM),
             ("ALARM", "LIT", "an AC meter with no AC connected", T.SEG),
             ("UYARI", "LIT", "warning — absent phases", T.UYARI)]
    y = 2.22
    for name, state, meaning, c in lamps:
        T.box(s, 6.00, y + 0.075, 0.11, 0.11, fill=c if state == "LIT" else None,
              line=c, radius=0.5)
        T.text(s, 6.26, y, 1.3, 0.26, name, size=11, color=T.TEXT, font=T.MONO)
        T.text(s, 7.62, y, 0.7, 0.26, state, size=10, color=c, font=T.DISP)
        T.text(s, 8.42, y, 4.2, 0.26, meaning, size=11, color=T.MUTED,
               font=T.BODY)
        y += 0.40

    T.code(s, 0.70, 4.62, 5.05, 1.30, [
        ("MainBus_Voltage_L1  100  = 0.000", T.LCD),
        ("MainBus_Current_L1  180  = 0.000", T.LCD),
        ("MainBus_Freq_L1     266  = 0.000", T.LCD),
    ], title="EVERY AC REGISTER READS ZERO — CORRECTLY", size=10)

    T.card(s, 6.00, 4.02, 6.63, 2.72, accent=T.UYARI)
    T.text(s, 6.26, 4.24, 6.1, 0.3, "0.000 is not null", size=17,
           color=T.UYARI, font=T.MONO)
    T.block(s, 6.26, 4.66, 6.1,
            "A zero means “read correctly, genuinely zero”. A null means the "
            "register could not be read at all. The gateway publishes the key "
            "either way, so a consumer can always tell the two apart — that "
            "distinction is requirement FW-12.\n\n"
            "It matters because the meter is a True-RMS AC analyser with "
            "nothing on its voltage or current inputs. The lamps are not a "
            "fault; they are the device correctly complaining about absent "
            "phases.",
            size=11.5, color=T.MUTED, spacing=1.42)
    T.footer(s, num())
    return s


# =========================================================== 07 · supply
def s_supply(prs):
    s = T.content(prs, "The most misread number on the bench",
                  "Supply_Voltage · register 40260 · BESLEME GERİLİMİ",
                  active=("meter",), accent=T.UYARI)

    T.text(s, 0.70, 1.76, 6.3, 0.9,
           "Three different values have been recorded for this register.\n"
           "All three were correct at the time.",
           size=17, color=T.TEXT, font=T.DISP, spacing=1.15)

    T.kv_table(s, 0.70, 2.96, 6.3, [
        ("2026-07-23", "26.5 V", T.MUTED),
        ("2026-07-28  gateway + PC client", "13.2 V", T.MUTED),
        ("2026-07-28  photographed dial", "23.35 V", T.LCD),
    ], col1=4.3, head=("when", "value"), accent=T.UYARI, row_h=0.40)

    T.text(s, 0.70, 4.60, 6.3, 1.4,
           "It is a live readback of whatever the bench supply is dialled to — "
           "not a characteristic of the meter. It is the one channel on this "
           "bench that can move, which makes it useful as a staleness canary "
           "and useless as a regression reference.",
           size=12, color=T.MUTED, font=T.BODY, spacing=1.45)

    T.card(s, 7.40, 1.76, 5.23, 2.30, accent=T.LCD)
    T.text(s, 7.64, 2.00, 4.8, 0.3, "USE THIS INSTEAD", size=9, color=T.LCD,
           font=T.DISP)
    T.text(s, 7.64, 2.34, 4.8, 0.7, "22 / 22", size=34, color=T.LCD, font=T.MONO)
    T.text(s, 7.64, 2.96, 4.8, 0.9,
           "The register count proves the Modbus path is healthy. The voltage "
           "only proves the dial position.",
           size=11.5, color=T.MUTED, font=T.BODY, spacing=1.4)

    T.card(s, 7.40, 4.24, 5.23, 2.42, accent=T.SEG)
    T.text(s, 7.64, 4.48, 4.8, 0.3, "OPEN — AND MORE URGENT", size=9,
           color=T.SEG, font=T.DISP)
    T.text(s, 7.64, 4.80, 4.8, 0.5,
           "The app reads ≈2 % above the supply's own display, always in the "
           "same direction.", size=11.5, color=T.TEXT, font=T.BODY, spacing=1.35)
    T.text(s, 7.64, 5.48, 4.8, 1.0,
           "Cable loss has the wrong sign, so it is excluded: either the PSU "
           "display under-reads or the DKM's housekeeping ADC over-reads. One "
           "DMM across the meter's own terminals settles it, and nobody has "
           "taken that measurement yet.",
           size=10.5, color=T.MUTED, font=T.BODY, spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 08 · divider
def d_path(prs):
    s = T.divider(prs, "part two", "The path a value takes",
                  "From a resistive divider inside the meter to a JSON string in "
                  "a phone's memory, one layer at a time.",
                  accent=T.LCD, active=("meter", "gw", "broker", "phone"))
    T.footer(s, num())
    return s


# =========================================================== 09 · OSI map
def s_osi(prs):
    s = T.content(prs, "The whole system, on the OSI model",
                  "two hops, seven layers, one payload",
                  active=("meter", "gw", "broker", "phone"))

    x0, x1, x2, x3 = 0.70, 1.34, 3.10, 7.90
    w3 = 12.63 - x3
    T.text(s, x1, 1.58, 1.7, 0.24, "LAYER", size=8, color=T.LCD, font=T.DISP)
    T.text(s, x2, 1.58, 4.7, 0.24, "HOP 1   METER → GATEWAY", size=8,
           color=T.LCD, font=T.DISP)
    T.text(s, x3, 1.58, w3, 0.24, "HOP 2   GATEWAY → BROKER → PHONE", size=8,
           color=T.LCD, font=T.DISP)
    T.rule(s, x0, 1.86, 11.93, color=T.HAIR2)

    layers = [
        ("7", "Application",
         "Modbus  FC03 read holding registers",
         "MQTT 3.1.1  PUBLISH / SUBSCRIBE"),
        ("6", "Presentation",
         "IEEE-754 float32, big-endian word order",
         "JSON UTF-8   ·   weights as base64 LE float32"),
        ("5", "Session",
         "MBAP transaction id pairs reply to request",
         "MQTT session, keepalive, retained status + LWT"),
        ("4", "Transport",
         "TCP port 502",
         "TCP port 8883, wrapped in TLS 1.3"),
        ("3", "Network",
         "IPv4  192.169.10.75 → 192.169.10.74",
         "IPv4 → …ala.eu-central-1.emqxsl.com"),
        ("2", "Data link",
         "Ethernet II   MAC xx-xx-xx-xx-xx-xx",
         "802.11 b/g/n   CSMA/CA, SSID your-ssid"),
        ("1", "Physical",
         "Cat5e twisted pair, RJ45",
         "2.4 GHz ISM   RSSI −46 dBm at the bench"),
    ]
    y = 2.00
    rh = 0.63
    for i, (no, name, a, b) in enumerate(layers):
        band = T.PANEL2 if i % 2 == 0 else T.PANEL
        T.box(s, x0, y, 11.93, rh, fill=band)
        T.text(s, x0 + 0.10, y + 0.17, 0.5, 0.3, no, size=15, color=T.LCD_D,
               font=T.MONO)
        T.text(s, x1, y + 0.13, 1.7, 0.3, name, size=12.5, color=T.TEXT,
               font=T.DISP)
        T.text(s, x1, y + 0.36, 1.7, 0.2, f"L{no}", size=8, color=T.DIM,
               font=T.MONO)
        T.text(s, x2, y + 0.20, 4.65, 0.3, a, size=10.5, color=T.MUTED,
               font=T.MONO)
        T.text(s, x3, y + 0.20, w3, 0.3, b, size=10.5, color=T.MUTED,
               font=T.MONO)
        y += rh
    T.vrule(s, x3 - 0.28, 2.00, rh * 7, color=T.HAIR2)

    T.text(s, x0, 6.50, 11.93, 0.4,
           "TLS sits between 4 and 7 — it is why the payload can cross the "
           "public internet at all, and it is the only layer here that a "
           "leaked credential would still walk straight through.",
           size=11, color=T.DIM, font=T.BODY, spacing=1.3)
    T.footer(s, num())
    return s


# =========================================================== 10 · encapsulation
def s_encap(prs):
    s = T.content(prs, "Four bytes, wrapped twice",
                  "23.35 V leaving the meter and arriving at the phone",
                  active=("meter", "gw", "broker", "phone"))

    T.text(s, 0.70, 1.62, 5.6, 0.26, "HOP 1  —  WHAT THE METER SENDS", size=9,
           color=T.LCD, font=T.DISP)
    layersA = [
        ("Ethernet II header", "14 B", T.DIM),
        ("IPv4 header", "20 B", T.DIM),
        ("TCP header", "20 B", T.DIM),
        ("MBAP header  tid · pid · len · unit", "7 B", T.MUTED),
        ("FC03 reply  fn + byte count", "2 B", T.MUTED),
        ("41 BA CC CD   ← the value", "4 B", T.LCD),
    ]
    y = 1.96
    for i, (lab, size, c) in enumerate(layersA):
        inset = i * 0.26
        wbox = 5.6 - inset * 2
        last = i == len(layersA) - 1
        T.box(s, 0.70 + inset, y, wbox, 0.52,
              fill=T.PANEL2 if not last else T.PANEL,
              line=T.LCD if last else T.HAIR)
        T.text(s, 0.70 + inset + 0.16, y + 0.15, wbox - 1.0, 0.3, lab,
               size=10.5, color=T.LCD if last else c, font=T.MONO)
        T.text(s, 0.70 + wbox + inset - 0.70, y + 0.15, 0.54, 0.3, size,
               size=10, color=T.DIM, font=T.MONO, align=PP_ALIGN.RIGHT)
        y += 0.545
    T.caption(s, 0.70, y + 0.06, 5.6,
              "67 bytes on the wire to carry 4 bytes of measurement")

    T.arrow(s, 6.52, 3.60, 7.02, 3.60, color=T.LCD, width=2.0)
    T.text(s, 6.20, 3.24, 1.2, 0.24, "ESP8266", size=8, color=T.LCD,
           font=T.DISP, align=PP_ALIGN.CENTER)
    T.text(s, 6.14, 3.78, 1.3, 0.4, "decode\n+ re-wrap", size=8, color=T.DIM,
           font=T.MONO, align=PP_ALIGN.CENTER, spacing=1.25)

    T.text(s, 7.03, 1.62, 5.6, 0.26, "HOP 2  —  WHAT THE PHONE RECEIVES",
           size=9, color=T.LCD, font=T.DISP)
    layersB = [
        ("802.11 frame", "~34 B", T.DIM),
        ("IPv4 + TCP", "40 B", T.DIM),
        ("TLS 1.3 record  AEAD sealed", "~22 B", T.MUTED),
        ("MQTT PUBLISH  osos/{gw}/telemetry", "~28 B", T.MUTED),
        ('"Supply_Voltage": 23.350', "~26 B", T.LCD),
    ]
    y = 1.96
    for i, (lab, size, c) in enumerate(layersB):
        inset = i * 0.26
        wbox = 5.6 - inset * 2
        last = i == len(layersB) - 1
        T.box(s, 7.03 + inset, y, wbox, 0.52,
              fill=T.PANEL2 if not last else T.PANEL,
              line=T.LCD if last else T.HAIR)
        T.text(s, 7.03 + inset + 0.16, y + 0.15, wbox - 1.0, 0.3, lab,
               size=10.5, color=T.LCD if last else c, font=T.MONO)
        T.text(s, 7.03 + wbox + inset - 0.70, y + 0.15, 0.54, 0.3, size,
               size=10, color=T.DIM, font=T.MONO, align=PP_ALIGN.RIGHT)
        y += 0.545
    T.caption(s, 7.03, y + 0.06, 5.6,
              "the full 22-register frame is under 1 KB (NF-2, still unmeasured)")

    T.rule(s, 0.70, 5.42, 11.93, color=T.HAIR)
    T.bullets(s, 0.70, 5.62, 11.93, 1.2, [
        ("The number changes representation twice, and value never.",
         "Binary float32 on the meter side, decimal text on the broker side. "
         "String(v, 3) is the only transformation, and it is lossy in the third "
         "decimal by design — nothing scales, offsets or corrects the reading "
         "anywhere in the chain."),
    ], size=12)
    T.footer(s, num())
    return s


# =========================================================== 11 · modbus read
def s_modbus(prs):
    s = T.content(prs, "One register read, byte for byte",
                  "function code 03 · big-endian float32 across two registers",
                  active=("meter", "gw"))

    T.code(s, 0.70, 1.72, 5.85, 2.30, [
        ("REQUEST                              12 bytes", T.LCD),
        "",
        ("00 01   transaction id", T.MUTED),
        ("00 00   protocol id (0 = Modbus)", T.MUTED),
        ("00 06   length of what follows", T.MUTED),
        ("01      unit id", T.TEXT),
        ("03      FC03 read holding registers", T.TEXT),
        ("01 04   start address 260", T.LCD),
        ("00 02   quantity: 2 registers", T.LCD),
    ], title="ESP8266  →  192.169.10.74:502")

    T.code(s, 6.78, 1.72, 5.85, 2.30, [
        ("RESPONSE                             13 bytes", T.LCD),
        "",
        ("00 01   transaction id — pairs the reply", T.MUTED),
        ("00 00   protocol id", T.MUTED),
        ("00 07   length", T.MUTED),
        ("01      unit id", T.TEXT),
        ("03      FC03 echoed", T.TEXT),
        ("04      byte count", T.TEXT),
        ("41 BA CC CD   →  23.350 V", T.LCD),
    ], title="192.169.10.74:502  →  ESP8266")

    T.card(s, 0.70, 4.22, 5.85, 2.28, accent=T.SEG)
    T.text(s, 0.94, 4.46, 5.4, 0.3, "THE DEVICE'S TEMPER", size=9, color=T.SEG,
           font=T.DISP)
    T.text(s, 0.94, 4.80, 5.4, 1.5,
           "The DKM-440 stops answering a master that fires requests back to "
           "back. It is a property of the device, not the transport — it "
           "survived the move from RS-485 to TCP unchanged.",
           size=11.5, color=T.MUTED, font=T.BODY, spacing=1.4)
    T.text(s, 0.94, 5.86, 5.4, 0.5,
           "kReadGapMs = 30      READ_RETRIES = 1",
           size=12, color=T.SEG, font=T.MONO)
    T.text(s, 0.94, 6.14, 5.4, 0.3, "remove the gap and reads start failing "
           "intermittently", size=9, color=T.DIM, font=T.MONO)

    T.card(s, 6.78, 4.22, 5.85, 2.28, accent=T.UYARI)
    T.text(s, 7.02, 4.46, 5.4, 0.3, "IT APPLIES TO CONCURRENT MASTERS TOO",
           size=9, color=T.UYARI, font=T.DISP)
    T.kv_table(s, 7.02, 4.86, 5.37, [
        ("gateway polling alone", "22 / 22  ×15", T.GREEN),
        ("one PC client opened alongside", "21 / 22", T.SEG),
    ], col1=3.5, row_h=0.42)
    T.text(s, 7.02, 5.86, 5.4, 0.6,
           "Close QModMaster, server.py and every PC client before an "
           "acceptance run.",
           size=11, color=T.MUTED, font=T.BODY, spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 12 · why ethernet
def s_uart(prs):
    s = T.content(prs, "Why this board reads Ethernet, not RS-485",
                  "one constraint chose the whole architecture",
                  active=("meter", "gw"))

    T.text(s, 0.70, 1.72, 5.6, 0.8,
           "The ESP8266 has exactly one usable hardware UART.",
           size=20, color=T.TEXT, font=T.DISP, spacing=1.1)
    T.text(s, 0.70, 2.52, 5.6, 1.6,
           "UART1 can transmit but has no receive line, so any Modbus RTU "
           "implementation must take UART0 — which is the programming and "
           "console port. Reading the meter over its own Ethernet port "
           "sidesteps the problem entirely.",
           size=12.5, color=T.MUTED, font=T.BODY, spacing=1.5)

    T.text(s, 0.70, 4.10, 5.6, 0.26, "WHAT GOING OVER TCP DELETES", size=9,
           color=T.LCD, font=T.DISP)
    T.rule(s, 0.70, 4.38, 5.6, color=T.HAIR2)
    gone = ["a MAX3485 transceiver", "A/B wiring and bus termination",
            "DE/RE direction toggling", "3.5-character frame timing"]
    y = 4.56
    for g in gone:
        T.text(s, 0.70, y, 0.3, 0.26, "×", size=13, color=T.SEG, font=T.MONO)
        T.text(s, 1.02, y + 0.02, 5.2, 0.26, g, size=12, color=T.MUTED,
               font=T.BODY)
        y += 0.38

    T.card(s, 6.90, 1.72, 5.73, 3.10, accent=T.LCD)
    T.text(s, 7.16, 1.98, 5.2, 0.3, "AND THE PART THAT ACTUALLY MATTERED",
           size=9, color=T.LCD, font=T.DISP)
    T.text(s, 7.16, 2.34, 5.2, 0.9,
           "The serial console stays usable while the gateway runs.",
           size=19, color=T.TEXT, font=T.DISP, spacing=1.1)
    T.text(s, 7.16, 3.24, 5.2, 1.4,
           "That is not a convenience. Every diagnosis in this project — the "
           "dead meter, the register counts, the TLS handshake — was read off "
           "that console. A gateway you cannot watch is a gateway you cannot "
           "debug.",
           size=12, color=T.MUTED, font=T.BODY, spacing=1.45)

    T.code(s, 6.90, 5.02, 5.73, 1.48, [
        ("tls: broker supports MFLN(1024) - using small buffers", T.MUTED),
        ("mqtt: connecting to your-deployment.emqxsl.com:8883 ... ok", T.GREEN),
        ("seq=15  22/22 regs  besleme=23.350  heap=18432", T.LCD),
    ], title="COM11 · 115200 BAUD", accent=T.LCD)
    T.footer(s, num())
    return s


# =========================================================== 13 · register map
def s_map(prs):
    s = T.content(prs, "Finding a register nobody documented",
                  "modbus/dkm_440_mapping/METHOD.md",
                  active=("meter",))

    T.text(s, 0.70, 1.70, 11.93, 0.5,
           "A measurement register holds  raw = scale × value.  Drive the value "
           "to several known points; the register whose raw plots a straight "
           "line against them is that measurement, and the slope is the scale.",
           size=13.5, color=T.TEXT, font=T.BODY, spacing=1.4)

    steps = [
        ("Move one thing",
         "On a bench a single source feeds every input, so a static dump shows "
         "the same number in a dozen registers. Motion is the discriminator."),
        ("Record 3–5 points",
         "Two points pin a line; three to five across a wide range give a "
         "meaningful R² and expose non-linearity."),
        ("Least-squares every register",
         "Fit raw = m·V + b. The true register scores R² ≈ 1.000; noise and "
         "drift score low. Constant registers are skipped — no line to fit."),
        ("Rank, then verify",
         "R² first, swing second, so a perfectly-fitting-but-barely-moving "
         "artefact cannot win. Then cross-check the winner against the TEDAŞ "
         "table."),
    ]
    w = 2.87
    for i, (head, body) in enumerate(steps):
        x = 0.70 + i * (w + 0.145)
        T.card(s, x, 2.46, w, 1.86, accent=T.LCD)
        T.text(s, x + 0.20, 2.68, 0.5, 0.26, f"{i + 1}", size=13,
               color=T.LCD, font=T.MONO)
        T.text(s, x + 0.20, 2.98, w - 0.40, 0.3, head, size=12.5, color=T.TEXT,
               font=T.DISP)
        T.text(s, x + 0.20, 3.32, w - 0.40, 0.9, body, size=10, color=T.MUTED,
               font=T.BODY, spacing=1.35)

    T.code(s, 0.70, 4.56, 6.9, 1.62, [
        ("  addr     R^2  slope(raw/V)  intercept  scale  swing", T.MUTED),
        (" 20480  1.0000        10.000       0.00     10    500", T.LCD),
        (" 20500  0.7500        -0.020    2624.17      1      1", T.DIM),
    ], title="find_register.py OUTPUT", accent=T.LCD)
    T.caption(s, 0.70, 6.26, 6.9,
              "top row: R²=1.0000, big swing → that is the register, scale ÷10")

    T.card(s, 7.86, 4.56, 4.77, 1.62, accent=T.SEG)
    T.text(s, 8.10, 4.78, 4.3, 0.3, "STANDING CONSTRAINT  C-4", size=9,
           color=T.SEG, font=T.DISP)
    T.text(s, 8.10, 5.10, 4.3, 0.5, "never touch 16385–16406", size=15,
           color=T.SEG, font=T.MONO)
    T.text(s, 8.10, 5.58, 4.3, 0.5,
           "Neither read nor write. The scan scripts exclude the block "
           "explicitly.", size=10.5, color=T.MUTED, font=T.BODY, spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 14 · mqtt
def s_mqtt(prs):
    s = T.content(prs, "Getting it off the bench",
                  "MQTT over TLS 1.3 to EMQX Serverless",
                  active=("gw", "broker"))

    T.text(s, 0.70, 1.62, 6.0, 0.26, "TOPICS", size=9, color=T.LCD, font=T.DISP)
    T.rule(s, 0.70, 1.90, 6.0, color=T.HAIR2)
    topics = [
        ("osos/m/{mid}/a/{aid}/telemetry", "every 5 s · the 22 values", T.LCD),
        ("osos/m/{mid}/registry", "retained · which analyzers exist", T.LCD),
        ("osos/m/{mid}/state", "retained · sleep, interval, loads", T.LCD),
        ("osos/m/{mid}/status", "retained · online/offline + LWT", T.LCD),
        ("osos/m/{mid}/cmd", "phone → modem", T.GREEN),
        ("osos/m/{mid}/ack", "modem → phone", T.GREEN),
        ("osos/m/{mid}/labels", "retained · APP-owned names", T.COPPER),
        ("osos/{gw}/telemetry", "legacy v1 · still rendered", T.MUTED),
    ]
    y = 2.10
    for t, meaning, c in topics:
        T.text(s, 0.70, y, 3.4, 0.28, t, size=11.5, color=c, font=T.MONO)
        T.text(s, 4.20, y + 0.02, 2.5, 0.28, meaning, size=10, color=T.MUTED,
               font=T.BODY)
        y += 0.36
    T.text(s, 0.70, y + 0.06, 6.0, 0.5,
           "Protocol v2. Every modem-published payload carries \"v\": 2; the "
           "legacy topics carry none and are v1 by definition, so the old "
           "gateway still renders with no special case.",
           size=10, color=T.MUTED, font=T.BODY, spacing=1.3)

    T.text(s, 7.10, 1.62, 5.53, 0.26, "WHY TLS FITS ON THIS CHIP", size=9,
           color=T.LCD, font=T.DISP)
    T.rule(s, 7.10, 1.90, 5.53, color=T.HAIR2)
    T.text(s, 7.10, 2.10, 5.53, 1.3,
           "The broker negotiates Maximum Fragment Length, so BearSSL runs with "
           "1 KB receive buffers instead of the default 16 KB. That headroom is "
           "the only reason TLS coexists with the JSON encoder here.",
           size=11.5, color=T.MUTED, font=T.BODY, spacing=1.45)
    T.kv_table(s, 7.10, 3.06, 5.53, [
        ("RAM", "33,920 / 80,192      42 %", T.MUTED),
        ("IRAM", "60,799 / 65,536      92 %", T.SEG),
        ("flash", "388,320 / 1,048,576  37 %", T.MUTED),
    ], col1=1.5, row_h=0.38, head=("footprint", "v0.4, CFG_USE_TLS=1"),
        accent=T.LCD)
    T.text(s, 7.10, 4.44, 5.53, 0.4,
           "92 % IRAM is the tight constraint on this board — not flash.",
           size=10, color=T.DIM, font=T.MONO, spacing=1.3)

    T.rule(s, 0.70, 5.10, 11.93, color=T.HAIR)
    cards = [
        ("Server verified", T.GREEN,
         "CFG_TLS_INSECURE=0, against a DigiCert Global Root G2 anchor compiled "
         "into config.h. Handshake confirmed on hardware."),
        ("Credentials out of git", T.GREEN,
         "config.h is gitignored; only config.h.example is committed. Losing it "
         "loses the Wi-Fi and broker passwords."),
        ("No role separation", T.SEG,
         "Gateway and head-end share one credential. A leaked gateway password "
         "grants publish rights on every topic — the weakest point in the "
         "system."),
    ]
    for i, (head, c, body) in enumerate(cards):
        x = 0.70 + i * 4.02
        T.card(s, x, 5.32, 3.89, 1.34, accent=c)
        T.text(s, x + 0.20, 5.54, 3.5, 0.28, head, size=12.5, color=T.TEXT,
               font=T.DISP)
        T.text(s, x + 0.20, 5.86, 3.5, 0.8, body, size=9.5, color=T.MUTED,
               font=T.BODY, spacing=1.32)
    T.footer(s, num())
    return s


# =========================================================== 15 · the cycle
def s_cycle(prs):
    s = T.content(prs, "What the operation actually does",
                  "one five-second cycle, start to finish",
                  active=("meter", "gw", "broker", "phone"))

    x0, xw = 0.70, 11.93
    ty = 2.34
    T.rule(s, x0, ty, xw, color=T.HAIR2, weight=1.25)
    marks = [(0.0, "0 ms"), (0.146, "~730 ms"), (0.20, "~1.0 s"),
             (0.60, ""), (1.0, "5 000 ms")]
    for f, lab in marks:
        x = x0 + xw * f - (0.004 if f < 1 else 0.02)
        T.vrule(s, x, ty - 0.10, 0.22, color=T.HAIR2, weight=1.25)
        if lab:
            T.text(s, x - 0.5, ty + 0.20, 1.0, 0.24, lab, size=9, color=T.DIM,
                   font=T.MONO, align=PP_ALIGN.CENTER)

    bands = [
        (0.0, 0.146, "22 register reads", T.LCD),
        (0.146, 0.20, "encode", T.COPPER),
        (0.20, 0.26, "publish", T.GREEN),
        (0.26, 1.0, "idle", T.HAIR2),
    ]
    by = 1.78
    for f0, f1, lab, c in bands:
        x = x0 + xw * f0
        w = xw * (f1 - f0)
        T.box(s, x, by, w, 0.50, fill=c if c != T.HAIR2 else T.PANEL2, line=c)
        if w > 0.9:
            T.text(s, x, by + 0.14, w, 0.3, lab, size=11,
                   color=T.PANEL if c != T.HAIR2 else T.MUTED, font=T.DISP,
                   align=PP_ALIGN.CENTER, bold=True)
    # the two middle bands are too narrow to letter — legend them instead
    legend = [(T.LCD, "22 × (request + 30 ms gap)  ≈  730 ms"),
              (T.COPPER, "encode · ArduinoJson 7"),
              (T.GREEN, "publish · one TLS record")]
    ly = 2.84
    for c, lab in legend:
        T.box(s, x0, ly + 0.055, 0.09, 0.09, fill=c)
        T.text(s, x0 + 0.22, ly, 5.2, 0.24, lab, size=9.5, color=T.MUTED,
               font=T.MONO)
        ly += 0.28
    T.block(s, 6.55, 2.86, 6.08,
            "The remaining ~4 s is idle by design. You cannot poll faster to "
            "evaluate an alarm without breaking the polite-master rule — which "
            "is exactly why alarm rules live on the phone, over the telemetry "
            "stream the gateway already publishes.",
            size=11, color=T.MUTED, spacing=1.4)

    T.code(s, 0.70, 3.74, 5.55, 2.60, [
        ('{ "ts": "2026-08-03T11:20:05Z",', T.MUTED),
        ('  "seq": 4127,', T.MUTED),
        ('  "buffered": false,', T.UYARI),
        ('  "meter_ok": true,', T.GREEN),
        '  "values": {',
        ('    "Supply_Voltage":     23.350,', T.LCD),
        ('    "MainBus_Voltage_L1":  0.000,', T.LCD),
        ('    "MainBus_Current_N":   null,', T.SEG),
        "    …  22 keys total",
        "  } }",
    ], title="osos/dkm440-gw1/telemetry", accent=T.LCD)

    T.text(s, 6.55, 3.74, 6.08, 0.26, "THREE FIELDS THAT ARE NOT DECORATION",
           size=9, color=T.LCD, font=T.DISP)
    T.rule(s, 6.55, 4.02, 6.08, color=T.HAIR2)
    T.bullets(s, 6.55, 4.22, 6.08, 2.2, [
        ("seq", "monotonic per boot, independent of connectivity — a consumer "
         "can detect a gap even if timestamps look fine."),
        ("buffered", "honestly false on this build. Store-and-forward did not "
         "fit in 36 KB of free heap, and it is reported as absent rather than "
         "faked."),
        ("null vs 0.000", "not read, versus read as genuinely zero. Losing that "
         "distinction would make a dead meter look like an idle one."),
    ], size=11, marker=T.LCD, gap=7)
    T.footer(s, num())
    return s


# =========================================================== 16 · divider
def d_net(prs):
    s = T.divider(prs, "part three", "The neural network",
                  "Written from scratch in C++17 — no framework, no library, "
                  "every derivative by hand.",
                  accent=T.COPPER, active=("net",))
    T.footer(s, num())
    return s


# =========================================================== 17 · nn idea
def s_nn_idea(prs):
    s = T.content(prs, "What a neural network is",
                  "neural_net_c/EXPLANATION.md §1–§2",
                  active=("net",), accent=T.COPPER)

    T.text(s, 0.70, 1.66, 5.8, 0.3, "1 · A NEURON IS A WEIGHTED SUM", size=9,
           color=T.COPPER, font=T.DISP)
    T.rule(s, 0.70, 1.94, 5.8, color=T.HAIR2)
    T.text(s, 0.70, 2.22, 5.8, 0.5,
           "zⱼ  =  Σᵢ ( Wⱼᵢ · inᵢ )  +  bⱼ",
           size=22, color=T.COPPER, font=T.MONO)
    T.text(s, 0.70, 2.86, 5.8, 1.1,
           "Take the inputs, multiply each by its own weight, add a bias, "
           "produce one number. That is the entire neuron. Everything else in "
           "the project is bookkeeping: running many of these in parallel is a "
           "layer, running layers in sequence is a network, and choosing good "
           "W and b automatically is training.",
           size=12, color=T.MUTED, font=T.BODY, spacing=1.45)

    T.text(s, 6.83, 1.66, 5.8, 0.3, "2 · WHY THERE MUST BE A HIDDEN LAYER",
           size=9, color=T.COPPER, font=T.DISP)
    T.rule(s, 6.83, 1.94, 5.8, color=T.HAIR2)

    gx, gy, gs = 7.05, 2.24, 1.30
    T.box(s, gx, gy, gs, gs, fill=T.PANEL2, line=T.HAIR)
    pts = [(0, 0, "0"), (0, 1, "1"), (1, 0, "1"), (1, 1, "0")]
    for px, py, lab in pts:
        cx = gx + 0.26 + px * (gs - 0.52)
        cy = gy + gs - 0.26 - py * (gs - 0.52)
        c = T.COPPER if lab == "1" else T.LCD
        T.box(s, cx - 0.11, cy - 0.11, 0.22, 0.22, fill=c, radius=0.5)
        T.text(s, cx - 0.11, cy - 0.075, 0.22, 0.2, lab, size=9, color=T.PANEL,
               font=T.MONO, align=PP_ALIGN.CENTER)
    T.arrow(s, gx + 0.08, gy + gs - 0.08, gx + gs - 0.08, gy + 0.08,
            color=T.SEG, width=1.5, head=False, dashed=True)
    T.text(s, gx, gy + gs + 0.08, gs, 0.24, "XOR", size=9, color=T.MUTED,
           font=T.MONO, align=PP_ALIGN.CENTER)

    yy = T.block(s, 8.62, 2.20, 4.01,
                 "No single straight line separates XOR's ones from its zeros. "
                 "A hidden layer fixes it: each hidden neuron draws its own "
                 "line, turning the input into a representation in which the "
                 "classes are separable. The output neuron then draws one line "
                 "in that new space.",
                 size=11.5, color=T.MUTED, spacing=1.40, gap=0.16)
    T.block(s, 8.62, yy, 4.01,
            "The smallest possible demonstration of why depth works at all: "
            "layers build coordinates in which the problem becomes easy.",
            size=11, color=T.COPPER, spacing=1.38)

    T.rule(s, 0.70, 4.44, 11.93, color=T.HAIR)
    T.text(s, 0.70, 4.62, 5.8, 0.3, "3 · WHY THE ACTIVATION MUST BE NON-LINEAR",
           size=9, color=T.COPPER, font=T.DISP)
    T.text(s, 0.70, 4.94, 5.8, 1.0,
           "A linear function of a linear function is still linear, so without "
           "a non-linear f any depth collapses into a single matrix. Stacking "
           "layers would buy nothing at all.",
           size=11.5, color=T.MUTED, font=T.BODY, spacing=1.42)

    acts = [("sigmoid", "1 / (1 + e⁻ᶻ)", "s′ = s(1−s)", "derivative peaks at 0.25"),
            ("ReLU", "max(0, z)", "r′ = 1 if z>0", "does not vanish — trains faster"),
            ("softmax", "eᶻʲ / Σ eᶻᵏ", "vector-valued", "max subtracted to stop overflow")]
    for i, (nm, f, dv, note) in enumerate(acts):
        x = 6.83 + i * 1.97
        T.card(s, x, 4.62, 1.82, 1.72, accent=T.COPPER)
        T.text(s, x + 0.16, 4.82, 1.5, 0.26, nm, size=11.5, color=T.TEXT,
               font=T.DISP)
        T.text(s, x + 0.16, 5.12, 1.6, 0.26, f, size=10, color=T.COPPER,
               font=T.MONO)
        T.text(s, x + 0.16, 5.40, 1.6, 0.26, dv, size=9, color=T.MUTED,
               font=T.MONO)
        T.text(s, x + 0.16, 5.70, 1.55, 0.6, note, size=8.5, color=T.DIM,
               font=T.BODY, spacing=1.3)
    T.footer(s, num())
    return s


# =========================================================== 18 · training
def s_nn_train(prs):
    s = T.content(prs, "How it learns", "forward, loss, backward, step",
                  active=("net",), accent=T.COPPER)

    # Caret notation, exactly as neural_net_c/EXPLANATION.md writes it: the
    # index is the layer l, and a superscript numeral would read as layer 1.
    steps = [
        ("FORWARD", "a^0 = x\nz^l = W^l·a^(l-1) + b^l\na^l = f(z^l)",
         "Each layer caches z and a — not an optimisation. Backprop needs both."),
        ("LOSS", "L = −Σ y_j log a_j",
         "Cross-entropy over a softmax output punishes a confident wrong answer "
         "far harder than MSE does."),
        ("BACKWARD", "δ^L = a − y\nδ^l = (W^(l+1))^T·δ^(l+1)\n        ⊙ f′(z^l)",
         "The chain rule, written out. With softmax + cross-entropy the output "
         "term collapses to a − y."),
        ("STEP", "W ← W − η·(1/n)·Σ δ·a^T",
         "Mini-batch SGD: shuffle, accumulate gradients over 64 samples, take "
         "one averaged step."),
    ]
    w = 2.87
    for i, (head, math, body) in enumerate(steps):
        x = 0.70 + i * (w + 0.145)
        T.card(s, x, 1.72, w, 2.52, accent=T.COPPER)
        T.text(s, x + 0.20, 1.94, w - 0.4, 0.26, head, size=9, color=T.COPPER,
               font=T.DISP)
        T.text(s, x + 0.20, 2.26, w - 0.4, 0.9, math, size=12.5, color=T.TEXT,
               font=T.MONO, spacing=1.45)
        T.text(s, x + 0.20, 3.30, w - 0.4, 0.85, body, size=10, color=T.MUTED,
               font=T.BODY, spacing=1.38)
        if i < 3:
            T.arrow(s, x + w + 0.015, 2.98, x + w + 0.13, 2.98,
                    color=T.COPPER, width=1.5)

    T.card(s, 0.70, 4.50, 5.85, 2.0, accent=T.GREEN)
    T.text(s, 0.94, 4.72, 5.4, 0.26, "HOW WE KNOW THE DERIVATIVES ARE RIGHT",
           size=9, color=T.GREEN, font=T.DISP)
    T.text(s, 0.94, 5.02, 5.4, 0.5,
           "max |analytic − numeric|  <  1e-9",
           size=15, color=T.GREEN, font=T.MONO)
    T.text(s, 0.94, 5.46, 5.4, 0.9,
           "gradcheck.cpp perturbs every weight by ±ε and compares the finite "
           "difference against backprop's gradient. It is the one test that "
           "makes hand-written calculus trustworthy — and it is why the maths "
           "above is not just decoration on a slide.",
           size=11, color=T.MUTED, font=T.BODY, spacing=1.4)

    T.text(s, 6.90, 4.50, 5.73, 0.26, "HYPERPARAMETERS — main_mnist.cpp",
           size=9, color=T.COPPER, font=T.DISP)
    T.kv_table(s, 6.90, 4.84, 5.73, [
        ("EPOCHS", "10", T.TEXT),
        ("BATCH", "64", T.TEXT),
        ("ETA  (learning rate)", "0.1", T.TEXT),
        ("shuffle", "Fisher–Yates, per epoch", T.TEXT),
        ("weight init", "scaled by fan-in", T.TEXT),
    ], col1=3.0, row_h=0.34)
    T.footer(s, num())
    return s


# =========================================================== 19 · mnist
def s_mnist(prs):
    s = T.content(prs, "MNIST — the standard first problem",
                  "70 000 handwritten digits · 60 k train / 10 k test",
                  active=("net",), accent=T.COPPER)

    T.picture(s, os.path.join(FIG, "mnist-strip.png"), 0.70, 1.70, w=7.15)
    T.caption(s, 0.70, 2.72, 7.15,
              "real samples, read straight out of data/t10k-images-idx3-ubyte")

    T.card(s, 8.30, 1.62, 4.33, 1.42, accent=T.COPPER)
    T.text(s, 8.56, 1.82, 3.9, 0.3, "TEST ACCURACY", size=9, color=T.COPPER,
           font=T.DISP)
    T.text(s, 8.56, 2.10, 3.9, 0.7, "97.65 %", size=38, color=T.COPPER,
           font=T.MONO)
    T.text(s, 11.10, 2.36, 1.4, 0.3, "10 000 unseen", size=9, color=T.DIM,
           font=T.MONO, align=PP_ALIGN.RIGHT)

    T.picture(s, os.path.join(FIG, "mlp-diagram.png"), 0.70, 3.20, w=7.15)

    T.text(s, 8.30, 3.30, 4.33, 0.26, "WHY THIS SHAPE", size=9, color=T.COPPER,
           font=T.DISP)
    T.rule(s, 8.30, 3.58, 4.33, color=T.HAIR2)
    T.bullets(s, 8.30, 3.78, 4.33, 2.6, [
        ("784 in", "28 × 28 pixels flattened and divided by 255. No "
         "convolution, no augmentation at train time."),
        ("128 hidden, ReLU", "wide enough to learn stroke parts, small enough "
         "that the whole weight file is 407 KB and fits in a phone asset."),
        ("10 out, softmax", "ten probabilities that sum to one — which is what "
         "makes a confidence gate meaningful later."),
    ], size=10.5, marker=T.COPPER, gap=7)

    T.rule(s, 0.70, 6.10, 7.15, color=T.HAIR)
    T.text(s, 0.70, 6.28, 7.15, 0.5,
           "Written from scratch: no TensorFlow, no PyTorch, no BLAS. "
           "Roughly 900 lines of C++17, every derivative derived by hand and "
           "checked numerically.",
           size=11, color=T.MUTED, font=T.BODY, spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 20 · to the phone
def s_parity(prs):
    s = T.content(prs, "From the trainer to the phone",
                  "MX-1 and MX-2 — the seam between the two specs",
                  active=("net", "phone"), accent=T.COPPER)

    T.text(s, 0.70, 1.64, 11.93, 0.26,
           "ONE STROKE, EIGHT STEPS — AND TWO INDEPENDENT IMPLEMENTATIONS OF IT",
           size=9, color=T.COPPER, font=T.DISP)
    T.picture(s, os.path.join(FIG, "mnist-pipeline.png"), 0.70, 1.96, w=8.10)
    T.caption(s, 0.70, 3.62, 8.10,
              "280×280 canvas · stroke 20 round cap · R-channel · threshold 25 · "
              "ink ≥ 30 · fit 20 px block-average · centre-of-mass in 28×28")

    T.card(s, 9.10, 1.90, 3.53, 1.86, accent=T.GREEN)
    T.text(s, 9.32, 2.10, 3.1, 0.26, "MX-1  WEIGHT PARITY", size=9,
           color=T.GREEN, font=T.DISP)
    T.text(s, 9.32, 2.42, 3.1, 1.2,
           "w.bin exports to nnc-json-1 (base64 LE float32) and loads "
           "bit-identically in both runtimes — www/nn.js and Android "
           "Weights.kt. One trained artifact, two consumers, zero re-training.",
           size=10, color=T.MUTED, font=T.BODY, spacing=1.38)

    T.rule(s, 0.70, 4.14, 11.93, color=T.HAIR)

    T.card(s, 0.70, 4.36, 7.55, 2.14, accent=T.SEG)
    T.text(s, 0.96, 4.58, 7.0, 0.26, "MX-2 IS THE ONE REAL PIECE OF TECHNICAL "
           "DEBT", size=9, color=T.SEG, font=T.DISP)
    T.text(s, 0.96, 4.90, 7.0, 0.9,
           "draw.js and Preprocess.kt must produce byte-identical 784-vectors "
           "from the same stroke. Two hand-ported implementations of an "
           "eight-step pixel pipeline — and no test pinning them together.",
           size=12, color=T.TEXT, font=T.BODY, spacing=1.42)
    T.text(s, 0.96, 5.78, 7.0, 0.6,
           "A divergence would not crash anything. It would silently change "
           "which command fires. One golden-vector fixture — a single stroke "
           "and its expected 784 bytes, asserted in both runtimes — closes it.",
           size=11, color=T.MUTED, font=T.BODY, spacing=1.4)

    T.card(s, 8.50, 4.36, 4.13, 2.14, accent=T.COPPER)
    T.text(s, 8.74, 4.58, 3.7, 0.26, "MX-5  ROUND TRIP", size=9, color=T.COPPER,
           font=T.DISP)
    T.text(s, 8.74, 4.92, 3.7, 0.5, "label,p0..p783", size=13, color=T.COPPER,
           font=T.MONO)
    T.text(s, 8.74, 5.34, 3.7, 1.0,
           "Symbols drawn on the phone export in exactly the CSV format "
           "data_mnist.cpp already ingests, so the full network can be "
           "retrained on personal symbols with a wider output layer.",
           size=10, color=T.MUTED, font=T.BODY, spacing=1.38)
    T.footer(s, num())
    return s


# =========================================================== 21 · divider
def d_phone(prs):
    s = T.divider(prs, "part four", "The phone is the head-end",
                  "Live values, alarm rules, and a drawing pad that turns a "
                  "symbol into a command — with a gate in front of it.",
                  accent=T.LCD, active=("phone",))
    T.footer(s, num())
    return s


# =========================================================== 22 · app tour
def s_app(prs):
    s = T.content(prs, "osos-hmi", "Kotlin · Jetpack Compose · HiveMQ MQTT client",
                  active=("phone",))

    # Five screens, because this is the only slide in the presented cut that
    # carries phone images - dropping one drops it from the talk entirely.
    shots = [
        ("phone-fleet.png", "FLEET", T.LCD,
         "Every modem and analyzer, in the operator's own folders. Asleep "
         "modems dim. One master sleep switch."),
        ("phone-modem.png", "MODEM", T.SEG,
         "One modem's observed state: sleep, interval, and four load channels "
         "switched from the phone."),
        ("phone-monitor.png", "MONITOR", T.LCD,
         "Five tile views for the selected analyzer; tap a tile for its "
         "sparkline over the last 720 frames."),
        ("phone-draw.png", "DRAW", T.COPPER,
         "650 ms of pen-up idle triggers recognition, so multi-stroke symbols "
         "still work. Every result opens the inspector."),
        ("phone-alarms.png", "ALARMS", T.UYARI,
         "Rules on the telemetry stream. Muted while asleep — still recorded, "
         "and returned as a digest on wake."),
    ]
    h = 3.72
    step = 2.386
    for i, (fn, title, col, body) in enumerate(shots):
        x = 0.70 + i * step
        T.picture(s, os.path.join(FIG, fn), x, 1.72, h=h)
        T.text(s, x, 1.72 + h + 0.20, 2.25, 0.26, title, size=11, color=col,
               font=T.DISP)
        T.text(s, x, 1.72 + h + 0.50, 2.25, 0.9, body, size=9.5, color=T.MUTED,
               font=T.BODY, spacing=1.35)

    T.caption(s, 0.70, 7.10 - 0.02, 11.0, "")
    T.footer(s, num(), "osos-hmi 0.3.0 · screens redrawn from the Compose "
             "source, not photographed")
    return s


# =========================================================== 23 · commands
def s_commands(prs):
    s = T.content(prs, "Adding a command",
                  "one JSON file is the single source of truth",
                  active=("phone", "gw"))

    T.code(s, 0.70, 1.70, 6.70, 3.06, [
        "{",
        ('  "digits": {', T.MUTED),
        ('    "0": { "scope": "gateway", "action": "ping" },', T.UYARI),
        ('    "1": { "scope": "gateway", "action": "read_now" },', T.UYARI),
        ('    "2": { "scope": "gateway", "action": "set_interval",', T.UYARI),
        ('           "args": { "seconds": 2 } },', T.UYARI),
        ('    "4": { "scope": "local", "action": "view",', T.LCD),
        ('           "args": { "page": "L1" } },', T.LCD),
        ('    "9": { "scope": "none", "action": "unassigned" }', T.DIM),
        "  }",
        "}",
    ], title="config/commands.json", accent=T.LCD)

    T.text(s, 7.70, 1.70, 4.93, 0.26, "HOW TO ADD ONE", size=9, color=T.LCD,
           font=T.DISP)
    T.rule(s, 7.70, 1.98, 4.93, color=T.HAIR2)
    T.bullets(s, 7.70, 2.18, 4.93, 2.6, [
        ("Pick a free digit.", "9 is reserved and unassigned; that is the "
         "cheapest slot."),
        ("Choose a scope.", "gateway means it leaves the phone. local means it "
         "only changes what the phone shows."),
        ("Name an existing action.", "ping, read_now, set_interval, view — the "
         "firmware and BOUND_ACTIONS both key off these strings."),
        ("Regenerate the assets.", "the same file is bundled into the app and "
         "served to the browser HMI, so they cannot disagree."),
    ], size=10.5, gap=7)

    T.rule(s, 0.70, 5.00, 11.93, color=T.HAIR)
    T.text(s, 0.70, 5.20, 5.6, 0.26, "TWO SCOPES, TWO RISK PROFILES", size=9,
           color=T.LCD, font=T.DISP)

    T.card(s, 0.70, 5.52, 5.85, 1.16, accent=T.LCD)
    T.text(s, 0.94, 5.70, 5.4, 0.26, "scope = local", size=12, color=T.LCD,
           font=T.MONO)
    T.text(s, 0.94, 5.98, 5.4, 0.6,
           "Fires instantly from the prediction. A misread switches to the "
           "wrong tile view — harmless, and instantly obvious.",
           size=10.5, color=T.MUTED, font=T.BODY, spacing=1.35)

    T.card(s, 6.78, 5.52, 5.85, 1.16, accent=T.UYARI)
    T.text(s, 7.02, 5.70, 5.4, 0.26, "scope = gateway", size=12, color=T.UYARI,
           font=T.MONO)
    T.text(s, 7.02, 5.98, 5.4, 0.6,
           "Leaves the phone and reaches an industrial device. Requires "
           "confidence ≥ 0.90 and an explicit Send tap. Never fires on "
           "recognition alone.",
           size=10.5, color=T.MUTED, font=T.BODY, spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 24 · safety gate
def s_gate(prs):
    s = T.content(prs, "A guess in front of an actuator",
                  "MX-3 — the requirement that exists because of that asymmetry",
                  active=("phone", "gw"), accent=T.UYARI)

    T.picture(s, os.path.join(FIG, "phone-draw.png"), 0.70, 1.72, h=4.55)

    x = 3.20
    T.text(s, x, 1.72, 9.43, 0.9,
           "Recognition never actuates. It only ever proposes.",
           size=22, color=T.TEXT, font=T.DISP, spacing=1.1)

    gates = [
        ("1", "Confidence gate", "softmax ≥ 0.90 for digits · head ≥ 0.85 "
         "with a cosine ≥ 0.80 sanity check for custom symbols", T.LCD),
        ("2", "Human gate", "a gateway command arms a confirm bar and is "
         "published only after an explicit Send tap", T.UYARI),
        ("3", "Structural gate", "relay and dkm_write are absent from the "
         "firmware source — not flag-disabled, not commented out, absent", T.SEG),
    ]
    y = 2.76
    for no, head, body, c in gates:
        T.card(s, x, y, 9.43, 1.06, accent=c)
        T.text(s, x + 0.24, y + 0.24, 0.4, 0.4, no, size=20, color=c,
               font=T.MONO)
        T.text(s, x + 0.86, y + 0.22, 8.3, 0.28, head, size=13.5, color=T.TEXT,
               font=T.DISP)
        T.text(s, x + 0.86, y + 0.56, 8.3, 0.4, body, size=11, color=T.MUTED,
               font=T.BODY, spacing=1.3)
        y += 1.18

    T.rule(s, x, 6.20, 9.43, color=T.HAIR)
    T.text(s, x, 6.38, 9.43, 0.5,
           "The third gate is the one that matters. The first two are policy "
           "and can be changed by a settings screen; the third cannot be "
           "reached by any configuration, because there is no code to reach.",
           size=11, color=T.DIM, font=T.BODY, spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 25 · custom
def s_custom(prs):
    s = T.content(prs, "Teaching it your own symbol",
                  "a logistic head trained on-device over a frozen embedding",
                  active=("phone", "net"), accent=T.COPPER)

    T.picture(s, os.path.join(FIG, "phone-commands.png"), 10.20, 1.72, h=4.90)

    T.text(s, 0.70, 1.66, 9.0, 0.26, "WHAT HAPPENS WHEN YOU SAVE 10 SAMPLES",
           size=9, color=T.COPPER, font=T.DISP)
    T.rule(s, 0.70, 1.94, 9.05, color=T.HAIR2)

    stages = [
        ("Freeze the MLP", "The 784-128-10 network is not retrained. Its "
         "128-unit ReLU hidden layer is reused as an embedding — a compact "
         "description of what was drawn."),
        ("Augment ×5", "Each stored 28×28 is shifted by ±1 and ±2 px, turning "
         "10–15 samples into 50–75 training vectors for free."),
        ("Train a head", "A logistic regression head, 128 → N, by SGD with L2. "
         "N is however many custom commands exist. Training finishes in "
         "milliseconds and reruns automatically whenever samples change."),
        ("Gate twice", "The head's softmax must clear 0.85 and the best stored "
         "sample's cosine must clear 0.80. While a class has under 10 samples "
         "the head is not trusted at all — it falls back to pure cosine ≥ 0.93."),
    ]
    y = 2.16
    for i, (head, body) in enumerate(stages):
        T.text(s, 0.70, y + 0.02, 0.4, 0.3, f"{i + 1}", size=13,
               color=T.COPPER, font=T.MONO)
        T.text(s, 1.20, y, 8.55, 0.28, head, size=13, color=T.TEXT, font=T.DISP)
        y = T.block(s, 1.20, y + 0.32, 8.55, body, size=11, color=T.MUTED,
                    spacing=1.38, gap=0.34)

    T.rule(s, 0.70, 6.24, 9.05, color=T.HAIR)
    T.block(s, 0.70, 6.42, 9.05,
            "The inspector shows head softmax, per-class cosine and the digit "
            "MLP's top-3 after every recognition — a match is never a black box.",
            size=11, color=T.COPPER, spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 26 · alarms
def s_alarms(prs):
    s = T.content(prs, "Adding an alarm",
                  "and why the rules cannot live in the firmware",
                  active=("phone",), accent=T.SEG)

    T.picture(s, os.path.join(FIG, "phone-alarms.png"), 0.70, 1.72, h=4.55)

    x = 3.20
    T.card(s, x, 1.72, 9.43, 1.28, accent=T.SEG)
    T.text(s, x + 0.24, 1.94, 9.0, 0.28, "THE CONSTRAINT THAT DECIDED THIS",
           size=9, color=T.SEG, font=T.DISP)
    T.text(s, x + 0.24, 2.24, 9.0, 0.7,
           "The Modbus read budget is fixed by the report interval. You cannot "
           "poll faster to evaluate a threshold without breaking the "
           "polite-master rule — so alarms are evaluated on the telemetry "
           "stream the gateway already publishes, and cost zero extra reads.",
           size=11.5, color=T.MUTED, font=T.BODY, spacing=1.4)

    T.text(s, x, 3.20, 9.43, 0.26, "A RULE IS FOUR FIELDS", size=9,
           color=T.LCD, font=T.DISP)
    T.rule(s, x, 3.48, 9.43, color=T.HAIR2)
    fields = [("key", "which telemetry value", "MainBus_Voltage_L1"),
              ("min / max", "the acceptable band", "207.00 … 253.00"),
              ("holdSec", "how long it must stay out", "30"),
              ("enabled", "armed or not", "true")]
    y = 3.68
    for f, meaning, ex in fields:
        T.text(s, x, y, 1.6, 0.26, f, size=11, color=T.LCD, font=T.MONO)
        T.text(s, x + 1.75, y + 0.02, 3.4, 0.26, meaning, size=10.5,
               color=T.MUTED, font=T.BODY)
        T.text(s, x + 5.35, y, 4.05, 0.26, ex, size=10.5, color=T.TEXT,
               font=T.MONO)
        y += 0.40
    T.text(s, x, y + 0.04, 9.43, 0.4,
           "The hold timer is what makes it usable: a single noisy frame will "
           "not wake anyone at 3 a.m.",
           size=10.5, color=T.DIM, font=T.BODY, spacing=1.3)

    T.text(s, x, 5.76, 9.43, 0.26, "THREE RULES YOU DO NOT HAVE TO WRITE",
           size=9, color=T.LCD, font=T.DISP)
    T.rule(s, x, 6.04, 9.43, color=T.HAIR2)
    builtins = [("meter_ok == false", "for ≥ 30 s"),
                ("gateway LWT", "retained status says offline"),
                ("telemetry silence", "no frame for > 3× the interval")]
    for i, (a, b) in enumerate(builtins):
        bx = x + i * 3.16
        T.text(s, bx, 6.24, 3.0, 0.26, a, size=11, color=T.SEG, font=T.MONO)
        T.text(s, bx, 6.52, 3.0, 0.26, b, size=10, color=T.MUTED, font=T.BODY)
    T.footer(s, num())
    return s


# =========================================================== 27 · status
def s_status(prs):
    s = T.content(prs, "Where it actually stands",
                  "evidence-based · nothing here is rounded up",
                  active=("meter", "gw", "broker", "phone", "net"))

    cols = [
        ("PROVEN ON HARDWARE", T.GREEN, [
            "22/22 registers, 15 consecutive cycles",
            "PC client read the same value, same second",
            "TLS 1.3 handshake, server verified (BR-1)",
            "meter address survives a power cycle",
            "fleet tree renders 2 modems + a v1 gateway",
            "gradient check 1e-9 · MNIST 97.65 % (SRS-02)",
            "credentials out of version control",
        ]),
        ("CODE COMPLETE, UNPROVEN", T.UYARI, [
            "cmd/ack on the ESP8266 — compiles, not flashed",
            "sleep and 4 load channels — same",
            "power-pull → retained offline (A2)",
            "< 2 s command latency (NF-1)",
            "RS-485 gateway — never run on hardware",
            "overnight soak — not yet attempted",
        ]),
        ("OPEN, AND SAID SO", T.SEG, [
            "sleep current never measured on a meter (F-6)",
            "no broker role separation or ACLs (BR-2)",
            "store-and-forward: buffered is always false",
            "no golden-vector test for MX-2 parity",
            "supply channel reads ≈2 % high, uninvestigated",
            "mains accuracy never verified against a DMM",
        ]),
    ]
    for i, (head, c, items) in enumerate(cols):
        x = 0.70 + i * 4.02
        T.card(s, x, 1.72, 3.89, 4.28, accent=c)
        T.text(s, x + 0.22, 1.96, 3.4, 0.26, head, size=9, color=c, font=T.DISP)
        T.rule(s, x + 0.22, 2.26, 3.45, color=T.HAIR2)
        y = 2.46
        for it in items:
            T.box(s, x + 0.22, y + 0.07, 0.07, 0.07, fill=c)
            T.text(s, x + 0.44, y, 3.24, 0.5, it, size=10.5, color=T.MUTED,
                   font=T.BODY, spacing=1.3)
            y += 0.50

    T.rule(s, 0.70, 6.20, 11.93, color=T.HAIR)
    T.rich(s, 0.70, 6.40, 11.93, 0.6, [[
        ("The PC head-end was superseded, not skipped.  ", T.TEXT, T.BODY, True, 12),
        ("HE-1…HE-5 were written before the Android app existed. The phone is "
         "the head-end now, and those five requirements should be rewritten to "
         "say so rather than left looking failed.", T.MUTED, T.BODY, False, 12),
    ]], spacing=1.35)
    T.footer(s, num())
    return s


# =========================================================== 28 · next
def s_fleet(prs):
    """One modem was never the shape of the problem: many modems, each
    mastering many analyzers, named by the operator rather than by the wiring."""
    s = T.content(prs, "From one meter to a fleet",
                  "protocol v2 · many modems × many analyzers",
                  active=("gw", "broker", "phone"))

    T.text(s, 0.70, 1.68, 11.93, 0.5,
           "The machine owns the addresses. The operator owns the names.",
           size=19, color=T.LCD, font=T.DISP, spacing=1.1)
    T.text(s, 0.70, 2.12, 11.93, 0.4,
           "A modem announces what it actually polls on a retained registry "
           "topic; the app annotates it with names and folders on a separate "
           "retained topic it alone owns. Two writers, two topics, no shared "
           "field — so a rename can never corrupt a Modbus address, and "
           "neither can win a race with the other.",
           size=12, color=T.MUTED, font=T.BODY, spacing=1.4)

    T.rule(s, 0.70, 2.86, 11.93, color=T.HAIR)

    feats = [
        ("Multiple analyzers", T.LCD, "FLAT IDS, FOLDERS AS METADATA",
         "an-01 stays an-01 for life. Names and folders live in MQTT, not in "
         "the topic, so a rename moves no data and breaks no history. The "
         "simulator runs 25 per modem; the ESP8266 is capped at 8 by its "
         "buffer."),
        ("Sleep mode", T.COPPER, "MUTE, NEVER DEAF",
         "Alarms keep evaluating while asleep — only the notification is "
         "suppressed, and everything suppressed comes back as a digest on "
         "wake. Per-modem, plus one master switch. The overnight record "
         "survives the quiet."),
        ("Modem energy", T.COPPER, "NEVER DEEP SLEEP",
         "Sleep means a 5 s → 300 s interval and a lower radio duty cycle, "
         "with the broker connection intact. Deep sleep would drop the very "
         "link the wake command arrives on, and fire the LWT — reporting the "
         "modem dead while it merely rested."),
        ("Load control", T.SEG, "FOUR CHANNELS, OFF ON BOOT",
         "Relay channels on the modem's own GPIO — not a meter register, so "
         "the DKM-440 command block stays untouched. Loads are never "
         "persisted: re-closing a contactor after a power cut has to be a "
         "decision, not a default."),
    ]
    w = 2.87
    for i, (head, c, tag, body) in enumerate(feats):
        x = 0.70 + i * (w + 0.145)
        T.card(s, x, 3.08, w, 2.42, accent=c)
        T.text(s, x + 0.20, 3.30, w - 0.4, 0.3, head, size=15, color=T.TEXT,
               font=T.DISP)
        T.text(s, x + 0.20, 3.62, w - 0.4, 0.22, tag, size=8, color=c,
               font=T.MONO)
        T.text(s, x + 0.20, 3.92, w - 0.4, 1.4, body, size=10, color=T.MUTED,
               font=T.BODY, spacing=1.38)

    T.text(s, 0.70, 5.72, 11.93, 0.26, "AND THE ONE THAT COSTS NOTHING", size=9,
           color=T.GREEN, font=T.DISP)
    T.rule(s, 0.70, 6.00, 11.93, color=T.HAIR2)
    kept = [
        ("Versioned", "every v2 payload carries \"v\": 2 — the legacy topics "
         "carry none and are v1 by definition"),
        ("Backward compatible", "the old gateway still renders, tagged v1, "
         "with no special case in the reducer"),
        ("Free rollback", "if the flash goes wrong the demo degrades to v1 "
         "rather than dying"),
    ]
    for i, (a, b) in enumerate(kept):
        bx = 0.70 + i * 4.02
        T.text(s, bx, 6.24, 3.8, 0.26, a, size=11, color=T.GREEN, font=T.MONO)
        T.text(s, bx, 6.52, 3.8, 0.26, b, size=10, color=T.MUTED, font=T.BODY)
    T.footer(s, num())
    return s


def s_adopt(prs):
    """The handoff. What IKOM actually has to do to run this on their own
    broker, their own meters, their own database."""
    s = T.content(prs, "Putting it into production",
                  "four steps · docs/BROKER_ACL.md carries the detail",
                  active=("meter", "gw", "broker", "phone", "net"))

    T.text(s, 0.70, 1.62, 6.10, 0.26, "ADDING A METER IS ONE LINE", size=9,
           color=T.LCD, font=T.DISP)
    T.rule(s, 0.70, 1.90, 6.10, color=T.HAIR2)
    T.code(s, 0.70, 2.04, 6.10, 1.86, [
        ("// firmware8266/osos_gw8266/config.h", T.DIM),
        "static const AnalyzerCfg CFG_ANALYZERS[] = {",
        '    { "an-01", "192.169.10.74", 502, 1, 5 },',
        ('    { "an-02", "192.169.10.75", 502, 1, 5 },   // <- new', T.GREEN),
        "};",
        ('#define CFG_MODEM_ID  "gw-01"   // per modem', T.DIM),
    ], size=10)
    T.text(s, 0.70, 4.00, 6.10, 0.9,
           "No topic changes, no app rebuild, no migration. The analyzer "
           "appears in the tree the moment the modem republishes its registry, "
           "named an-02 until someone names it properly from the phone.",
           size=11, color=T.MUTED, font=T.BODY, spacing=1.4)

    steps = [
        ("1 · Per-modem credentials", T.SEG,
         "One broker user per modem, plus one head-end user, with the ACLs in "
         "docs/BROKER_ACL.md. This is the one item still open (BR-2) and the "
         "only one that is a security issue rather than a feature."),
        ("2 · Point it at your broker", T.LCD,
         "CFG_MQTT_HOST in config.h, and the app's Settings screen. Nothing "
         "else is broker-specific — no EMQX API, no vendor extension."),
        ("3 · Own the metadata", T.COPPER,
         "osos/m/+/labels and osos/tree are retained JSON the app writes. A "
         "bridge into IKOM Data Manager subscribes to those two topics and "
         "the fleet is in your database, named."),
        ("4 · Store-and-forward first", T.UYARI,
         "buffered is always false today. A reader that silently drops data "
         "during a network blip cannot be a system of record — this is the "
         "gate before any billing use."),
    ]
    y = 1.62
    for head, c, body in steps:
        T.card(s, 7.10, y, 5.53, 1.24, accent=c)
        T.text(s, 7.32, y + 0.14, 5.1, 0.26, head, size=12, color=T.TEXT,
               font=T.DISP)
        T.text(s, 7.32, y + 0.44, 5.1, 0.7, body, size=9.5, color=T.MUTED,
               font=T.BODY, spacing=1.34)
        y += 1.34

    T.rule(s, 0.70, 5.06, 11.93, color=T.HAIR)
    T.text(s, 0.70, 5.22, 11.93, 0.26, "WHAT IS ALREADY VENDOR-NEUTRAL",
           size=9, color=T.GREEN, font=T.DISP)
    T.rule(s, 0.70, 5.50, 11.93, color=T.HAIR2)
    neutral = [
        ("The topic grammar", "one file per language, three implementations "
         "that must agree"),
        ("The gateway", "any Modbus TCP device, once its register map is known"),
        ("The app", "subscribes fleet-wide; it has no idea what a DKM-440 is"),
    ]
    for i, (a, b) in enumerate(neutral):
        bx = 0.70 + i * 4.02
        T.text(s, bx, 5.72, 3.85, 0.26, a, size=11, color=T.GREEN, font=T.MONO)
        T.text(s, bx, 6.00, 3.85, 0.5, b, size=10, color=T.MUTED, font=T.BODY,
               spacing=1.3)

    T.text(s, 0.70, 6.60, 11.93, 0.3,
           "The register map is the part that is specific to this meter. "
           "Everything above it moves.",
           size=11, color=T.DIM, font=T.MONO)
    T.footer(s, num())
    return s


def s_next(prs):
    s = T.content(prs, "What this is worth to IKOM",
                  "docs/IKOM_APPLICATIONS.md · 2026-07-31",
                  active=("meter", "gw", "broker", "phone", "net"))

    T.text(s, 0.70, 1.68, 11.93, 0.5,
           "The valuable line in the repository is the architecture, not the "
           "register map.",
           size=19, color=T.LCD, font=T.DISP, spacing=1.1)
    T.text(s, 0.70, 2.12, 11.93, 0.4,
           "Three of the four pieces built here are vendor-neutral. Any "
           "Modbus field device can go behind this gateway in about a day once "
           "its map is known — and the method for deriving an unknown map is "
           "itself written down.",
           size=12, color=T.MUTED, font=T.BODY, spacing=1.4)

    T.rule(s, 0.70, 2.86, 11.93, color=T.HAIR)

    apps = [
        ("Submetering", T.LCD, "RECOMMENDED FIRST",
         "One DKM-440 covers 30 single-phase feeders — an entire distribution "
         "panel at one Modbus address. Apartment blocks, shopping centres, "
         "organised industrial zones. One meter, one gateway, thirty billable "
         "circuits."),
        ("Power quality", T.COPPER, "BEST MARGIN",
         "The meter measures harmonics to the 17th, THD-V/I and imbalance — "
         "none of it currently exposed. Instrument a plant for a fortnight, "
         "produce a report, recommend filters. Sells expertise, not boxes."),
        ("OSOS as a service", T.LCD, "SHORTEST PATH TO REVENUE",
         "Automatic meter reading is regulated and recurring in Turkey. This "
         "is already most of a compliant reader; the gap is data integrity, "
         "history and a reporting front end — not new hardware."),
        ("Street lighting", T.LCD, "",
         "An astronomical time relay plus two remotely drivable relays, in the "
         "same box as the measurement. Municipal lighting maps onto it almost "
         "exactly."),
    ]
    w = 2.87
    for i, (head, c, tag, body) in enumerate(apps):
        x = 0.70 + i * (w + 0.145)
        T.card(s, x, 3.08, w, 2.42, accent=c)
        T.text(s, x + 0.20, 3.30, w - 0.4, 0.3, head, size=15, color=T.TEXT,
               font=T.DISP)
        if tag:
            T.text(s, x + 0.20, 3.62, w - 0.4, 0.22, tag, size=8, color=c,
                   font=T.MONO)
        T.text(s, x + 0.20, 3.92, w - 0.4, 1.4, body, size=10, color=T.MUTED,
               font=T.BODY, spacing=1.38)

    T.text(s, 0.70, 5.72, 11.93, 0.26, "BEFORE ANY OF THEM", size=9,
           color=T.SEG, font=T.DISP)
    T.rule(s, 0.70, 6.00, 11.93, color=T.HAIR2)
    blockers = [
        ("Store-and-forward", "a reader that silently drops data during a "
         "network blip cannot be a system of record"),
        ("A historian", "720 frames in RAM is monitoring; billing and "
         "compliance need durable history"),
        ("Per-device credentials", "cheap to fix now, expensive after the "
         "first customer site"),
    ]
    for i, (a, b) in enumerate(blockers):
        x = 0.70 + i * 4.02
        T.text(s, x, 6.20, 3.8, 0.26, a, size=11.5, color=T.SEG, font=T.DISP)
        T.text(s, x, 6.48, 3.8, 0.4, b, size=10, color=T.MUTED, font=T.BODY,
               spacing=1.3)
    T.footer(s, num())
    return s


# =========================================================== 29 · close
def s_close(prs):
    s = T.blank(prs)
    T.bg(s)
    T.box(s, 0, 0, 0.16, 7.5, fill=T.LCD)

    T.text(s, 0.95, 1.30, 10.0, 0.3, "IN ONE SENTENCE", size=10.5, color=T.LCD,
           font=T.MONO)
    T.text(s, 0.92, 1.76, 11.4, 2.0,
           "A register inside an industrial meter\nnow reaches a phone in five "
           "seconds,\nand a drawing sends one back.",
           size=36, color=T.TEXT, font=T.DISP, spacing=1.12)

    T.rule(s, 0.95, 4.10, 1.6, color=T.LCD, weight=2.5)

    T.text(s, 0.95, 4.44, 5.4, 1.6,
           "Everything between those two ends — the polite-master pacing, the "
           "one-UART constraint, the least-squares register hunt, the TLS "
           "buffer negotiation, the confidence gate — is the actual work. The "
           "demo is the receipt.",
           size=13, color=T.MUTED, font=T.BODY, spacing=1.5)

    T.text(s, 7.10, 4.44, 5.5, 0.26, "STILL OWED", size=9, color=T.UYARI,
           font=T.DISP)
    T.rule(s, 7.10, 4.72, 5.5, color=T.HAIR2)
    owed = ["flashing v0.4 to the ESP8266 — it compiles, it has not run",
            "broker role separation and ACLs",
            "the awake-vs-asleep current, measured not assumed",
            "a DMM across the meter's own supply terminals"]
    y = 4.92
    for o in owed:
        T.box(s, 7.10, y + 0.06, 0.07, 0.07, fill=T.UYARI)
        T.text(s, 7.32, y, 5.3, 0.4, o, size=11, color=T.MUTED, font=T.BODY,
               spacing=1.3)
        y += 0.40

    T.rail(s, ("meter", "gw", "broker", "phone", "net"), x=0.95, y=6.60,
           span=5.35)
    T.text(s, 7.10, 6.62, 5.5, 0.3,
           "SRS-00 · SRS-01 · SRS-02   ·   delivery 2026-08-06",
           size=10, color=T.DIM, font=T.MONO, align=PP_ALIGN.RIGHT)
    return s


# ===========================================================================
# The condensed edit — 16 slides
#
# Same material, half the slides. The four section dividers come out (the rail
# already answers "where in the system are we?"), and "Why build it at all"
# comes out because each of its five points recurs later as a slide of its own.
# Eight pairs then merge; each merged slide is re-measured from scratch rather
# than being two slides scaled down.
#
# What did not survive the squeeze, so nobody goes looking for it:
#   · the mlp-diagram figure and the MX-5 CSV round trip (slide 11 keeps MX-1/2)
#   · the CFG_USE_TLS footprint table — only its binding number, 91 % IRAM
#   · the four-step register-map narrative keeps its own slide, untouched
# ===========================================================================

# =========================================================== c04 · meter+supply
def c_meter(prs):
    """s_meter + s_supply. The panel, and the one channel on it that moves."""
    s = T.content(prs, "Reading the panel honestly",
                  "two alarm lamps lit, and one number that keeps moving",
                  active=("meter",))

    photo_card(s, os.path.join(IMG, "dkm440-front.jpg"), 0.70, 1.78, 1.60,
               crop=(0.12, 0.66, 0.98, 0.97),
               cap="the status LEDs, bottom edge of the panel")

    T.text(s, 4.90, 1.62, 7.73, 0.3, "THE FOUR LAMPS", size=9, color=T.LCD,
           font=T.DISP)
    T.rule(s, 4.90, 1.90, 7.73, color=T.HAIR2)
    lamps = [("ENERJİ", "off", "energy accumulation", T.DIM),
             ("HABERL.", "off", "communications", T.DIM),
             ("ALARM", "LIT", "an AC meter with no AC connected", T.SEG),
             ("UYARI", "LIT", "warning — absent phases", T.UYARI)]
    y = 2.10
    for name, state, meaning, c in lamps:
        T.box(s, 4.90, y + 0.075, 0.11, 0.11,
              fill=c if state == "LIT" else None, line=c, radius=0.5)
        T.text(s, 5.16, y, 1.25, 0.26, name, size=11, color=T.TEXT, font=T.MONO)
        T.text(s, 6.50, y, 0.8, 0.26, state, size=10, color=c, font=T.DISP)
        T.text(s, 7.40, y, 5.23, 0.26, meaning, size=11, color=T.MUTED,
               font=T.BODY)
        y += 0.40

    T.code(s, 0.70, 3.90, 5.85, 1.27, [
        ("MainBus_Voltage_L1  100  = 0.000", T.LCD),
        ("MainBus_Current_L1  180  = 0.000", T.LCD),
        ("MainBus_Freq_L1     266  = 0.000", T.LCD),
    ], title="EVERY AC REGISTER READS ZERO — CORRECTLY", size=10)

    T.card(s, 6.78, 3.90, 5.85, 2.24, accent=T.UYARI)
    T.text(s, 7.02, 4.12, 5.4, 0.3, "0.000 is not null", size=16,
           color=T.UYARI, font=T.MONO)
    T.block(s, 7.02, 4.50, 5.37,
            "A zero means read correctly, genuinely zero. A null means the "
            "register could not be read at all. The gateway publishes the key "
            "either way — requirement FW-12 — so the two never merge.\n"
            "It matters because this is a True-RMS AC analyser with nothing on "
            "its voltage or current inputs. The lamps are not a fault; they are "
            "the device correctly complaining about absent phases.",
            size=10.5, color=T.MUTED, spacing=1.38)

    T.text(s, 0.70, 5.36, 5.85, 0.26, "SUPPLY_VOLTAGE · REGISTER 40260",
           size=9, color=T.UYARI, font=T.DISP)
    T.rule(s, 0.70, 5.64, 5.85, color=T.HAIR2)
    for i, (v, when) in enumerate([("26.5 V", "2026-07-23"),
                                   ("13.2 V", "07-28 · gw + PC"),
                                   ("23.35 V", "07-28 · dial")]):
        x = 0.70 + i * 1.97
        T.text(s, x, 5.76, 1.9, 0.3, v, size=15,
               color=T.LCD if i == 2 else T.MUTED, font=T.MONO)
        T.text(s, x, 6.06, 1.9, 0.24, when, size=8.5, color=T.DIM, font=T.MONO)
    T.block(s, 0.70, 6.36, 5.85,
            "All three correct when recorded: a live readback of the bench "
            "dial, not a property of the meter — a staleness canary, never a "
            "reference.",
            size=10, color=T.MUTED, spacing=1.34)

    T.rich(s, 6.78, 6.26, 5.85, 0.6, [[
        ("OPEN · ", T.SEG, T.MONO, True, 10),
        ("the app reads ≈2 % above the supply's own display, always the same "
         "way. Cable loss has the wrong sign; one DMM across the meter's own "
         "terminals settles it.", T.MUTED, T.BODY, False, 10),
    ]], spacing=1.32)
    T.footer(s, num())
    return s


# =========================================================== c05 · OSI + bytes
def c_osi(prs):
    """s_osi + s_encap. The layer map, with the byte budget underneath it."""
    s = T.content(prs, "The whole system, on the OSI model",
                  "two hops, seven layers, one payload",
                  active=("meter", "gw", "broker", "phone"))

    x0, x1, x2, x3 = 0.70, 1.34, 3.10, 7.90
    w3 = 12.63 - x3
    T.text(s, x1, 1.58, 1.7, 0.24, "LAYER", size=8, color=T.LCD, font=T.DISP)
    T.text(s, x2, 1.58, 4.7, 0.24, "HOP 1   METER → GATEWAY", size=8,
           color=T.LCD, font=T.DISP)
    T.text(s, x3, 1.58, w3, 0.24, "HOP 2   GATEWAY → BROKER → PHONE", size=8,
           color=T.LCD, font=T.DISP)
    T.rule(s, x0, 1.86, 11.93, color=T.HAIR2)

    layers = [
        ("7", "Application",
         "Modbus  FC03 read holding registers",
         "MQTT 3.1.1  PUBLISH / SUBSCRIBE"),
        ("6", "Presentation",
         "IEEE-754 float32, big-endian word order",
         "JSON UTF-8   ·   weights as base64 LE float32"),
        ("5", "Session",
         "MBAP transaction id pairs reply to request",
         "MQTT session, keepalive, retained status + LWT"),
        ("4", "Transport",
         "TCP port 502",
         "TCP port 8883, wrapped in TLS 1.3"),
        ("3", "Network",
         "IPv4  192.169.10.75 → 192.169.10.74",
         "IPv4 → …ala.eu-central-1.emqxsl.com"),
        ("2", "Data link",
         "Ethernet II   MAC xx-xx-xx-xx-xx-xx",
         "802.11 b/g/n   CSMA/CA, SSID your-ssid"),
        ("1", "Physical",
         "Cat5e twisted pair, RJ45",
         "2.4 GHz ISM   RSSI −46 dBm at the bench"),
    ]
    y = 2.00
    rh = 0.545
    for i, (no, name, a, b) in enumerate(layers):
        band = T.PANEL2 if i % 2 == 0 else T.PANEL
        T.box(s, x0, y, 11.93, rh, fill=band)
        T.text(s, x0 + 0.10, y + 0.13, 0.5, 0.3, no, size=15, color=T.LCD_D,
               font=T.MONO)
        T.text(s, x1, y + 0.09, 1.7, 0.3, name, size=12.5, color=T.TEXT,
               font=T.DISP)
        T.text(s, x1, y + 0.32, 1.7, 0.2, f"L{no}", size=8, color=T.DIM,
               font=T.MONO)
        T.text(s, x2, y + 0.16, 4.65, 0.3, a, size=10.5, color=T.MUTED,
               font=T.MONO)
        T.text(s, x3, y + 0.16, w3, 0.3, b, size=10.5, color=T.MUTED,
               font=T.MONO)
        y += rh
    T.vrule(s, x3 - 0.28, 2.00, rh * 7, color=T.HAIR2)

    T.rule(s, x0, 5.90, 11.93, color=T.HAIR)
    T.text(s, 0.70, 5.99, 5.85, 0.24, "HOP 1 — 67 BYTES TO CARRY 4", size=8.5,
           color=T.LCD, font=T.DISP)
    T.text(s, 0.70, 6.20, 5.85, 0.24,
           "eth 14 · ip 20 · tcp 20 · mbap 7 · fc03 2 · float32 4",
           size=9.5, color=T.MUTED, font=T.MONO)
    T.text(s, 6.78, 5.99, 5.85, 0.24, "HOP 2 — ≈150 BYTES TO CARRY ONE VALUE",
           size=8.5, color=T.LCD, font=T.DISP)
    T.text(s, 6.78, 6.20, 5.85, 0.24,
           "802.11 34 · ip+tcp 40 · tls 22 · publish 28 · json 26",
           size=9.5, color=T.MUTED, font=T.MONO)
    T.rich(s, 0.70, 6.46, 11.93, 0.4, [[
        ("Representation changes twice; the value never.  ",
         T.TEXT, T.BODY, True, 10.5),
        ("float32 on the meter side, decimal text on the broker side — "
         "String(v, 3) is the only transformation in the chain, and nothing "
         "scales, offsets or corrects the reading anywhere.",
         T.MUTED, T.BODY, False, 10.5),
    ]], spacing=1.3)
    T.footer(s, num())
    return s


# =========================================================== c06 · modbus+uart
def c_modbus(prs):
    """s_modbus + s_uart. The exchange, and the constraint that shaped it."""
    s = T.content(prs, "One register read, byte for byte",
                  "function code 03 · big-endian float32 across two registers",
                  active=("meter", "gw"))

    T.code(s, 0.70, 1.68, 5.85, 2.30, [
        ("REQUEST                              12 bytes", T.LCD),
        "",
        ("00 01   transaction id", T.MUTED),
        ("00 00   protocol id (0 = Modbus)", T.MUTED),
        ("00 06   length of what follows", T.MUTED),
        ("01      unit id", T.TEXT),
        ("03      FC03 read holding registers", T.TEXT),
        ("01 04   start address 260", T.LCD),
        ("00 02   quantity: 2 registers", T.LCD),
    ], title="ESP8266  →  192.169.10.74:502", size=10)

    T.code(s, 6.78, 1.68, 5.85, 2.30, [
        ("RESPONSE                             13 bytes", T.LCD),
        "",
        ("00 01   transaction id — pairs the reply", T.MUTED),
        ("00 00   protocol id", T.MUTED),
        ("00 07   length", T.MUTED),
        ("01      unit id", T.TEXT),
        ("03      FC03 echoed", T.TEXT),
        ("04      byte count", T.TEXT),
        ("41 BA CC CD   →  23.350 V", T.LCD),
    ], title="192.169.10.74:502  →  ESP8266", size=10)

    T.card(s, 0.70, 4.42, 3.60, 2.08, accent=T.SEG)
    T.text(s, 0.92, 4.62, 3.2, 0.26, "THE DEVICE'S TEMPER", size=9, color=T.SEG,
           font=T.DISP)
    T.block(s, 0.92, 4.92, 3.2,
            "The DKM-440 stops answering a master that fires requests back to "
            "back. A property of the device, not the transport — it survived "
            "the move from RS-485 to TCP unchanged.",
            size=10.5, color=T.MUTED, spacing=1.38)
    T.text(s, 0.92, 5.98, 3.2, 0.26, "kReadGapMs = 30", size=11, color=T.SEG,
           font=T.MONO)
    T.text(s, 0.92, 6.22, 3.2, 0.26, "READ_RETRIES = 1", size=11, color=T.SEG,
           font=T.MONO)

    T.card(s, 4.48, 4.42, 3.60, 2.08, accent=T.UYARI)
    T.text(s, 4.70, 4.62, 3.2, 0.26, "AND TO CONCURRENT MASTERS", size=9,
           color=T.UYARI, font=T.DISP)
    T.kv_table(s, 4.70, 4.96, 3.2, [
        ("gateway alone", "22/22 ×15", T.GREEN),
        ("+ one PC client", "21/22", T.SEG),
    ], col1=1.85, row_h=0.40, size=10)
    T.block(s, 4.70, 5.92, 3.2,
            "Close QModMaster, server.py and every PC client before an "
            "acceptance run.",
            size=10.5, color=T.MUTED, spacing=1.38)

    T.card(s, 8.26, 4.42, 4.37, 2.08, accent=T.LCD)
    T.text(s, 8.50, 4.62, 3.9, 0.26, "WHY ETHERNET, NOT RS-485", size=9,
           color=T.LCD, font=T.DISP)
    T.block(s, 8.50, 4.92, 3.9,
            "The ESP8266 has one usable UART: UART1 cannot receive, so Modbus "
            "RTU would have to take the console port. Over TCP the serial "
            "console stays usable — and every diagnosis in this project was "
            "read off it.",
            size=10.5, color=T.MUTED, spacing=1.38)
    T.text(s, 8.50, 6.20, 3.9, 0.26, "seq=15  22/22 regs  besleme=23.350",
           size=9.5, color=T.LCD, font=T.MONO)
    T.footer(s, num())
    return s


# =========================================================== c08 · mqtt+cycle
def c_link(prs):
    """s_mqtt + s_cycle. One five-second cycle, and where it publishes to."""
    s = T.content(prs, "Getting it off the bench",
                  "MQTT over TLS 1.3 to EMQX Serverless · one five-second cycle",
                  active=("gw", "broker", "phone"))

    x0, xw = 0.70, 11.93
    by = 1.62
    for f0, f1, lab, c in [(0.0, 0.146, "22 register reads", T.LCD),
                           (0.146, 0.20, "encode", T.COPPER),
                           (0.20, 0.26, "publish", T.GREEN),
                           (0.26, 1.0, "idle", T.HAIR2)]:
        x = x0 + xw * f0
        w = xw * (f1 - f0)
        T.box(s, x, by, w, 0.44, fill=c if c != T.HAIR2 else T.PANEL2, line=c)
        if w > 0.9:
            T.text(s, x, by + 0.11, w, 0.3, lab, size=10.5,
                   color=T.PANEL if c != T.HAIR2 else T.MUTED, font=T.DISP,
                   align=PP_ALIGN.CENTER, bold=True)
    ty = 2.18
    T.rule(s, x0, ty, xw, color=T.HAIR2, weight=1.25)
    for f, lab in [(0.0, "0 ms"), (0.146, "~730 ms"), (0.20, "~1.0 s"),
                   (0.60, ""), (1.0, "5 000 ms")]:
        x = x0 + xw * f - (0.004 if f < 1 else 0.02)
        T.vrule(s, x, ty - 0.09, 0.20, color=T.HAIR2, weight=1.25)
        if lab:
            T.text(s, x - 0.5, ty + 0.16, 1.0, 0.24, lab, size=9, color=T.DIM,
                   font=T.MONO, align=PP_ALIGN.CENTER)

    lx = 0.70
    for c, lab in [(T.LCD, "22 × (request + 30 ms gap) ≈ 730 ms"),
                   (T.COPPER, "encode · ArduinoJson 7"),
                   (T.GREEN, "publish · one TLS record")]:
        T.box(s, lx, 2.60, 0.09, 0.09, fill=c)
        w = T.text_w(lab, T.MONO, 9.5)
        T.text(s, lx + 0.20, 2.53, w + 0.12, 0.24, lab, size=9.5, color=T.MUTED,
               font=T.MONO)
        lx += w + 0.72
    T.text(s, 0.70, 2.86, 11.93, 0.26,
           "The remaining ≈4 s is idle by design — alarm rules therefore live "
           "on the phone, over the stream the gateway already publishes.",
           size=10, color=T.DIM, font=T.BODY, spacing=1.3)

    T.code(s, 0.70, 3.22, 5.55, 2.80, [
        ('{ "ts": "2026-08-03T11:20:05Z",', T.MUTED),
        ('  "seq": 4127,', T.MUTED),
        ('  "buffered": false,', T.UYARI),
        ('  "meter_ok": true,', T.GREEN),
        '  "values": {',
        ('    "Supply_Voltage":     23.350,', T.LCD),
        ('    "MainBus_Voltage_L1":  0.000,', T.LCD),
        ('    "MainBus_Current_N":   null,', T.SEG),
        "    …  22 keys total",
        "  } }",
    ], title="osos/dkm440-gw1/telemetry", accent=T.LCD, size=10)

    T.rich(s, 0.70, 6.12, 5.55, 0.8, [
        [("seq", T.LCD, T.MONO, True, 9),
         ("  ·  monotonic per boot — a gap is detectable",
          T.MUTED, T.BODY, False, 9)],
        [("buffered", T.UYARI, T.MONO, True, 9),
         ("  ·  honestly false; store-and-forward did not fit in 36 KB",
          T.MUTED, T.BODY, False, 9)],
        [("null vs 0.000", T.SEG, T.MONO, True, 9),
         ("  ·  not read, versus read as genuinely zero",
          T.MUTED, T.BODY, False, 9)],
    ], spacing=1.24, space_after=3)

    T.text(s, 6.55, 3.22, 6.08, 0.26, "TOPICS", size=9, color=T.LCD,
           font=T.DISP)
    T.rule(s, 6.55, 3.50, 6.08, color=T.HAIR2)
    y = 3.66
    for t, meaning, c in [
            ("osos/{gw}/telemetry", "every 5 s · the 22 values", T.LCD),
            ("osos/{gw}/status", "retained · online/offline + LWT", T.LCD),
            ("osos/{gw}/event", "link loss, recovery, boot", T.LCD),
            ("osos/{gw}/cmd", "phone → gateway", T.UYARI),
            ("osos/{gw}/ack", "gateway → phone", T.UYARI)]:
        T.text(s, 6.55, y, 3.0, 0.26, t, size=11, color=c, font=T.MONO)
        T.text(s, 9.60, y + 0.02, 3.03, 0.26, meaning, size=9.5, color=T.MUTED,
               font=T.BODY)
        y += 0.33
    T.text(s, 6.55, y + 0.04, 6.08, 0.4,
           "cmd/ack are implemented on the phone, the ESP32-S3 build and now "
           "the ESP8266 v0.4 firmware — which compiles but has not been flashed.",
           size=9.5, color=T.UYARI, font=T.BODY, spacing=1.3)

    T.text(s, 6.55, 5.86, 6.08, 0.26, "TLS 1.3 — AND WHERE IT STOPS", size=9,
           color=T.LCD, font=T.DISP)
    T.rule(s, 6.55, 6.14, 6.08, color=T.HAIR2)
    T.rich(s, 6.55, 6.24, 6.08, 0.7, [[
        ("MFLN lets BearSSL run 1 KB receive buffers instead of 16 KB — the "
         "only reason TLS coexists with the JSON encoder at 92 % IRAM. Server "
         "verified against a DigiCert G2 anchor, config.h gitignored. ",
         T.MUTED, T.BODY, False, 10),
        ("Gateway and head-end still share one credential.",
         T.SEG, T.BODY, False, 10),
    ]], spacing=1.3)
    T.footer(s, num())
    return s


# =========================================================== c09 · the network
def c_nn(prs):
    """s_nn_idea + s_nn_train. One neuron, then the loop that fits it."""
    s = T.content(prs, "The network, from one neuron to training",
                  "neural_net_c/EXPLANATION.md · every derivative by hand",
                  active=("net",), accent=T.COPPER)

    T.text(s, 0.70, 1.60, 6.0, 0.26, "A NEURON IS A WEIGHTED SUM", size=9,
           color=T.COPPER, font=T.DISP)
    T.text(s, 0.70, 1.88, 6.0, 0.4, "zⱼ  =  Σᵢ ( Wⱼᵢ · inᵢ )  +  bⱼ",
           size=20, color=T.COPPER, font=T.MONO)
    T.block(s, 0.70, 2.34, 6.0,
            "Multiply each input by its own weight, add a bias, produce one "
            "number. Many in parallel is a layer, layers in sequence are a "
            "network, and choosing W and b automatically is training.",
            size=11, color=T.MUTED, spacing=1.40)

    T.text(s, 7.35, 1.60, 5.28, 0.26, "WHY THERE MUST BE A HIDDEN LAYER",
           size=9, color=T.COPPER, font=T.DISP)
    gx, gy, gs = 7.35, 1.92, 0.98
    T.box(s, gx, gy, gs, gs, fill=T.PANEL2, line=T.HAIR)
    for px, py, lab in [(0, 0, "0"), (0, 1, "1"), (1, 0, "1"), (1, 1, "0")]:
        cx = gx + 0.22 + px * (gs - 0.44)
        cy = gy + gs - 0.22 - py * (gs - 0.44)
        c = T.COPPER if lab == "1" else T.LCD
        T.box(s, cx - 0.10, cy - 0.10, 0.20, 0.20, fill=c, radius=0.5)
        T.text(s, cx - 0.10, cy - 0.068, 0.20, 0.2, lab, size=8.5,
               color=T.PANEL, font=T.MONO, align=PP_ALIGN.CENTER)
    T.arrow(s, gx + 0.07, gy + gs - 0.07, gx + gs - 0.07, gy + 0.07,
            color=T.SEG, width=1.5, head=False, dashed=True)
    T.text(s, gx, gy + gs + 0.06, gs, 0.24, "XOR", size=8.5, color=T.MUTED,
           font=T.MONO, align=PP_ALIGN.CENTER)
    T.block(s, 8.62, 1.92, 4.01,
            "No straight line separates XOR's ones from its zeros. Each hidden "
            "neuron draws its own line, building coordinates in which the "
            "classes become separable — and f must be non-linear, or any depth "
            "collapses back into a single matrix.",
            size=11, color=T.MUTED, spacing=1.40)

    steps = [
        ("FORWARD", "a^0 = x\nz^l = W^l·a^(l-1) + b^l\na^l = f(z^l)",
         "Each layer caches z and a — not an optimisation. Backprop needs both."),
        ("LOSS", "L = −Σ y_j log a_j",
         "Cross-entropy over softmax punishes a confident wrong answer far "
         "harder than MSE."),
        ("BACKWARD", "δ^L = a − y\nδ^l = (W^(l+1))^T·δ^(l+1)\n        ⊙ f′(z^l)",
         "The chain rule written out. With softmax + cross-entropy the output "
         "term collapses to a − y."),
        ("STEP", "W ← W − η·(1/n)·Σ δ·a^T",
         "Mini-batch SGD: shuffle, accumulate over 64 samples, take one "
         "averaged step."),
    ]
    w = 2.87
    for i, (head, math, body) in enumerate(steps):
        x = 0.70 + i * (w + 0.145)
        T.card(s, x, 3.30, w, 2.14, accent=T.COPPER)
        T.text(s, x + 0.20, 3.48, w - 0.4, 0.26, head, size=9, color=T.COPPER,
               font=T.DISP)
        T.text(s, x + 0.20, 3.76, w - 0.4, 0.9, math, size=11.5, color=T.TEXT,
               font=T.MONO, spacing=1.42)
        T.block(s, x + 0.20, 4.68, w - 0.4, body, size=9.5, color=T.MUTED,
                spacing=1.36)
        if i < 3:
            T.arrow(s, x + w + 0.015, 4.30, x + w + 0.13, 4.30,
                    color=T.COPPER, width=1.5)

    T.card(s, 0.70, 5.62, 5.85, 1.24, accent=T.GREEN)
    T.text(s, 0.92, 5.80, 5.4, 0.26, "HOW WE KNOW THE DERIVATIVES ARE RIGHT",
           size=9, color=T.GREEN, font=T.DISP)
    T.text(s, 0.92, 6.06, 5.4, 0.3, "max |analytic − numeric|  <  1e-9",
           size=14, color=T.GREEN, font=T.MONO)
    T.block(s, 0.92, 6.38, 5.4,
            "gradcheck.cpp perturbs every weight by ±ε and compares the finite "
            "difference against backprop.",
            size=9.5, color=T.MUTED, spacing=1.34)

    T.text(s, 6.78, 5.62, 5.85, 0.26, "THE REST OF IT — main_mnist.cpp", size=9,
           color=T.COPPER, font=T.DISP)
    T.rule(s, 6.78, 5.90, 5.85, color=T.HAIR2)
    T.text(s, 6.78, 6.02, 5.85, 0.26,
           "EPOCHS 10 · BATCH 64 · ETA 0.1 · Fisher–Yates shuffle per epoch",
           size=9.5, color=T.TEXT, font=T.MONO)
    T.text(s, 6.78, 6.26, 5.85, 0.26,
           "weights scaled by fan-in · softmax with max subtracted",
           size=9.5, color=T.MUTED, font=T.MONO)
    T.text(s, 6.78, 6.50, 5.85, 0.26,
           "sigmoid s′ = s(1−s) peaks at 0.25 · ReLU r′ = 1 does not vanish",
           size=9.5, color=T.DIM, font=T.MONO)
    T.footer(s, num())
    return s


# =========================================================== c10 · mnist+seam
def c_mnist(prs):
    """s_mnist + s_parity. The benchmark, and the seam to the phone."""
    s = T.content(prs, "MNIST, and the seam to the phone",
                  "70 000 handwritten digits · 60 k train / 10 k test",
                  active=("net", "phone"), accent=T.COPPER)

    T.picture(s, os.path.join(FIG, "mnist-strip.png"), 0.70, 1.66, w=7.15)
    T.caption(s, 0.70, 2.66, 7.15,
              "real samples, read straight out of data/t10k-images-idx3-ubyte")

    T.card(s, 8.30, 1.62, 4.33, 1.30, accent=T.COPPER)
    T.text(s, 8.54, 1.80, 3.9, 0.3, "TEST ACCURACY", size=9, color=T.COPPER,
           font=T.DISP)
    T.text(s, 8.54, 2.06, 3.9, 0.7, "97.65 %", size=32, color=T.COPPER,
           font=T.MONO)
    T.text(s, 11.20, 2.26, 1.2, 0.3, "10 000 unseen", size=8.5, color=T.DIM,
           font=T.MONO, align=PP_ALIGN.RIGHT)

    T.text(s, 0.70, 3.06, 7.15, 0.26,
           "ONE STROKE, EIGHT STEPS — AND TWO INDEPENDENT IMPLEMENTATIONS OF IT",
           size=9, color=T.COPPER, font=T.DISP)
    T.picture(s, os.path.join(FIG, "mnist-pipeline.png"), 0.70, 3.36, w=7.15)
    T.caption(s, 0.70, 4.94, 7.15,
              "280×280 canvas · stroke 20 round cap · R-channel · threshold 25 "
              "· ink ≥ 30 · fit 20 px block-average · centre-of-mass in 28×28")

    T.text(s, 8.30, 3.06, 4.33, 0.26, "WHY THIS SHAPE", size=9, color=T.COPPER,
           font=T.DISP)
    T.rule(s, 8.30, 3.34, 4.33, color=T.HAIR2)
    T.bullets(s, 8.30, 3.48, 4.33, 2.0, [
        ("784 in", "28 × 28 pixels flattened and divided by 255. No "
         "convolution, no augmentation at train time."),
        ("128 hidden, ReLU", "wide enough for stroke parts, small enough that "
         "the whole weight file is 407 KB and fits in a phone asset."),
        ("10 out, softmax", "ten probabilities summing to one — which is what "
         "makes a confidence gate meaningful."),
    ], size=10, marker=T.COPPER, gap=6)

    T.card(s, 0.70, 5.42, 7.15, 1.44, accent=T.SEG)
    T.text(s, 0.94, 5.60, 6.7, 0.26,
           "MX-2 IS THE ONE REAL PIECE OF TECHNICAL DEBT", size=9, color=T.SEG,
           font=T.DISP)
    T.block(s, 0.94, 5.88, 6.7,
            "draw.js and Preprocess.kt must produce byte-identical 784-vectors "
            "from the same stroke — two hand-ported implementations of that "
            "eight-step pipeline, with no test pinning them together. A "
            "divergence would not crash anything; it would silently change "
            "which command fires.",
            size=10, color=T.MUTED, spacing=1.36)

    T.card(s, 8.30, 5.42, 4.33, 1.44, accent=T.GREEN)
    T.text(s, 8.54, 5.60, 3.9, 0.26, "MX-1  WEIGHT PARITY", size=9,
           color=T.GREEN, font=T.DISP)
    T.block(s, 8.54, 5.88, 3.9,
            "w.bin exports to nnc-json-1 and loads bit-identically in www/nn.js "
            "and Android Weights.kt. One trained artifact, two consumers, zero "
            "re-training.",
            size=10, color=T.MUTED, spacing=1.36)
    T.footer(s, num(), "no TensorFlow, no PyTorch, no BLAS · ~900 lines of "
             "C++17, every derivative derived by hand")
    return s


# =========================================================== c12 · cmd + gate
def c_cmd(prs):
    """s_commands + s_gate. Adding a command, and what stands in front of it."""
    s = T.content(prs, "A drawing becomes a command",
                  "config/commands.json is the single source of truth",
                  active=("phone", "gw"), accent=T.UYARI)

    T.code(s, 0.70, 1.66, 6.10, 3.10, [
        "{",
        ('  "digits": {', T.MUTED),
        ('    "0": { "scope": "gateway", "action": "ping" },', T.UYARI),
        ('    "1": { "scope": "gateway", "action": "read_now" },', T.UYARI),
        ('    "2": { "scope": "gateway", "action": "set_interval",', T.UYARI),
        ('           "args": { "seconds": 2 } },', T.UYARI),
        ('    "4": { "scope": "local", "action": "view",', T.LCD),
        ('           "args": { "page": "L1" } },', T.LCD),
        ('    "9": { "scope": "none", "action": "unassigned" }', T.DIM),
        "  }",
        "}",
    ], title="config/commands.json", accent=T.LCD, size=10)

    T.block(s, 0.70, 4.92, 6.10,
            "To add one: pick a free digit — 9 is reserved and unassigned — "
            "choose a scope, name an action the firmware already keys off, and "
            "regenerate the assets. The same file is bundled into the app and "
            "served to the browser HMI, so the two cannot disagree.",
            size=10.5, color=T.MUTED, spacing=1.38)

    T.card(s, 0.70, 5.66, 2.96, 1.20, accent=T.LCD)
    T.text(s, 0.90, 5.84, 2.6, 0.26, "scope = local", size=11, color=T.LCD,
           font=T.MONO)
    T.block(s, 0.90, 6.12, 2.6,
            "Fires straight from the prediction. A misread switches to the "
            "wrong tile — harmless, and obvious.",
            size=9.5, color=T.MUTED, spacing=1.34)

    T.card(s, 3.84, 5.66, 2.96, 1.20, accent=T.UYARI)
    T.text(s, 4.04, 5.84, 2.6, 0.26, "scope = gateway", size=11, color=T.UYARI,
           font=T.MONO)
    T.block(s, 4.04, 6.12, 2.6,
            "Leaves the phone and reaches an industrial device. Never fires on "
            "recognition alone.",
            size=9.5, color=T.MUTED, spacing=1.34)

    T.text(s, 7.10, 1.66, 5.53, 0.8,
           "Recognition never actuates.\nIt only ever proposes.",
           size=21, color=T.TEXT, font=T.DISP, spacing=1.12)

    gates = [
        ("1", "Confidence gate", "softmax ≥ 0.90 for digits · head ≥ 0.85 with "
         "a cosine ≥ 0.80 check for custom symbols", T.LCD),
        ("2", "Human gate", "a gateway command arms a confirm bar and is "
         "published only after an explicit Send tap", T.UYARI),
        ("3", "Structural gate", "relay and dkm_write are absent from the "
         "firmware source — not flag-disabled, not commented out, absent",
         T.SEG),
    ]
    y = 2.66
    for no, head, body, c in gates:
        T.card(s, 7.10, y, 5.53, 1.22, accent=c)
        T.text(s, 7.32, y + 0.24, 0.4, 0.4, no, size=19, color=c, font=T.MONO)
        T.text(s, 7.90, y + 0.20, 4.5, 0.28, head, size=13, color=T.TEXT,
               font=T.DISP)
        T.block(s, 7.90, y + 0.52, 4.5, body, size=10, color=T.MUTED,
                spacing=1.34)
        y += 1.30

    T.block(s, 7.10, 6.58, 5.53,
            "The first two gates are policy; the third cannot be reached by "
            "any configuration.",
            size=9.5, color=T.DIM, spacing=1.3)
    T.footer(s, num())
    return s


# =========================================================== c13 · phone edge
def c_edge(prs):
    """s_custom + s_alarms. Both live on the phone for the same reason."""
    s = T.content(prs, "What the phone does that the gateway cannot",
                  "on-device learning and alarm rules · both sit here because "
                  "of a gateway constraint",
                  active=("phone", "net"))

    T.text(s, 0.70, 1.60, 5.85, 0.26, "TEACHING IT YOUR OWN SYMBOL", size=9,
           color=T.COPPER, font=T.DISP)
    T.rule(s, 0.70, 1.88, 5.85, color=T.HAIR2)
    T.block(s, 0.70, 2.00, 5.85,
            "There is no headroom on an ESP8266 for a model, so learning "
            "happens where the samples are drawn.",
            size=10.5, color=T.MUTED, spacing=1.36)

    stages = [
        ("Freeze the MLP", "the 784-128-10 network is not retrained; its "
         "128-unit ReLU layer is reused as an embedding"),
        ("Augment ×5", "±1 and ±2 px shifts turn 10–15 samples into 50–75 "
         "training vectors for free"),
        ("Train a head", "logistic regression 128 → N by SGD with L2, "
         "finishing in milliseconds and rerunning whenever samples change"),
        ("Gate twice", "head softmax ≥ 0.85 and best-sample cosine ≥ 0.80; "
         "under 10 samples the head is not trusted at all"),
    ]
    y = 2.52
    for i, (head, body) in enumerate(stages):
        T.text(s, 0.70, y + 0.01, 0.35, 0.28, f"{i + 1}", size=12,
               color=T.COPPER, font=T.MONO)
        T.text(s, 1.10, y, 5.45, 0.28, head, size=12, color=T.TEXT, font=T.DISP)
        y = T.block(s, 1.10, y + 0.28, 5.45, body, size=10, color=T.MUTED,
                    spacing=1.36, gap=0.22)

    T.rule(s, 0.70, 6.24, 5.85, color=T.HAIR)
    T.block(s, 0.70, 6.38, 5.85,
            "The inspector shows head softmax, per-class cosine and the digit "
            "MLP's top-3 after every recognition — a match is never a black box.",
            size=9.5, color=T.COPPER, spacing=1.32)

    T.text(s, 6.78, 1.60, 5.85, 0.26, "ADDING AN ALARM", size=9, color=T.SEG,
           font=T.DISP)
    T.rule(s, 6.78, 1.88, 5.85, color=T.HAIR2)
    T.block(s, 6.78, 2.00, 5.85,
            "The Modbus read budget is fixed by the report interval, so a "
            "threshold cannot be polled faster without breaking the "
            "polite-master rule. Rules are evaluated on the telemetry stream "
            "instead, and cost zero extra reads.",
            size=10.5, color=T.MUTED, spacing=1.36)

    T.text(s, 6.78, 3.06, 5.85, 0.26, "A RULE IS FOUR FIELDS", size=9,
           color=T.LCD, font=T.DISP)
    T.rule(s, 6.78, 3.34, 5.85, color=T.HAIR2)
    y = 3.50
    for f, meaning, ex in [("key", "which telemetry value",
                            "MainBus_Voltage_L1"),
                           ("min / max", "the acceptable band", "207.00…253.00"),
                           ("holdSec", "how long it must stay out", "30"),
                           ("enabled", "armed or not", "true")]:
        T.text(s, 6.78, y, 1.5, 0.26, f, size=10.5, color=T.LCD, font=T.MONO)
        T.text(s, 8.34, y + 0.02, 2.4, 0.26, meaning, size=10, color=T.MUTED,
               font=T.BODY)
        T.text(s, 10.80, y, 1.83, 0.26, ex, size=10, color=T.TEXT, font=T.MONO)
        y += 0.34
    T.block(s, 6.78, y + 0.04, 5.85,
            "The hold timer is what makes it usable: one noisy frame will not "
            "wake anyone at 3 a.m.",
            size=9.5, color=T.DIM, spacing=1.32)

    T.text(s, 6.78, 5.62, 5.85, 0.26, "THREE RULES YOU DO NOT HAVE TO WRITE",
           size=9, color=T.LCD, font=T.DISP)
    T.rule(s, 6.78, 5.90, 5.85, color=T.HAIR2)
    y = 6.04
    for a, b in [("meter_ok == false", "for ≥ 30 s"),
                 ("gateway LWT", "retained status says offline"),
                 ("telemetry silence", "no frame for > 3× the interval")]:
        T.text(s, 6.78, y, 2.3, 0.26, a, size=10, color=T.SEG, font=T.MONO)
        T.text(s, 9.20, y + 0.01, 3.43, 0.26, b, size=9.5, color=T.MUTED,
               font=T.BODY)
        y += 0.30
    T.footer(s, num())
    return s


# =========================================================== build
# The delivery deck, condensed. `--full` builds the original 29-slide cut to a
# separate file; the two share every slide function they have in common.
DECK17 = ["s_title", "s_summary", "s_bench", "c_meter", "c_osi", "c_modbus",
          "s_map", "c_link", "c_nn", "c_mnist", "s_app", "s_fleet", "c_cmd",
          "c_edge", "s_status", "s_next", "s_adopt", "s_close"]

DECK30 = ["s_title", "s_summary", "s_why", "d_bench", "s_bench", "s_meter",
          "s_supply", "d_path", "s_osi", "s_encap", "s_modbus", "s_uart",
          "s_map", "s_mqtt", "s_cycle", "d_net", "s_nn_idea", "s_nn_train",
          "s_mnist", "s_parity", "d_phone", "s_app", "s_fleet", "s_commands",
          "s_gate", "s_custom", "s_alarms", "s_status", "s_next", "s_adopt", "s_close"]

# The presented cut. DECK17 plus s_encap at position 6 - "Four bytes, wrapped
# twice" was added by hand to OSOS-DeliveryFinal.pptx, and putting it in the
# running order is what stops that file drifting out of sync again. It is
# generated now, not maintained by hand.
DECKFINAL = ["s_title", "s_summary", "s_bench", "c_meter", "c_osi", "s_encap",
             "c_modbus", "s_map", "c_link", "c_nn", "c_mnist", "s_app",
             "s_fleet", "c_cmd", "c_edge", "s_status", "s_next", "s_adopt", "s_close"]


def build(deck, outfile):
    global n
    n = 0
    prs = Presentation()
    prs.slide_width = T.SW
    prs.slide_height = T.SH
    for name in deck:
        globals()[name](prs)
    prs.save(outfile)
    print(f"{len(prs.slides._sldIdLst)} slides -> {outfile}")


def main():
    if "--full" in sys.argv:
        build(DECK30, os.path.join(HERE, "OSOS-Delivery-full.pptx"))
    elif "--final" in sys.argv:
        build(DECKFINAL, os.path.join(HERE, "OSOS-DeliveryFinal.pptx"))
    else:
        build(DECK17, OUTFILE)


if __name__ == "__main__":
    main()
