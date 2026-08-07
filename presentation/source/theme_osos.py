"""Design system for the OSOS delivery deck.

The palette is not invented: every colour is lifted off the bench hardware in
docs/img/. The DKM-440's backlit LCD is the primary accent, the CLASS 305D's
seven-segment display is the failure colour, the UYARI lamp is the warning
colour, and the ESP8266's gold antenna traces carry the neural-net thread.

Typography is DIN-derived condensed (Bahnschrift) for headings — the lineage of
European instrument panel lettering — Segoe UI for prose, and Consolas for every
number, register name, topic and payload. Data is always monospaced; that rule
is what makes the deck read as an instrument rather than a slide template.
"""
import os

from PIL import ImageFont
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn

# ---------------------------------------------------------------- palette
PANEL  = RGBColor(0x0D, 0x11, 0x17)   # bezel black   — slide ground
PANEL2 = RGBColor(0x16, 0x1C, 0x24)   # raised sub-panel — cards
PANEL3 = RGBColor(0x1E, 0x26, 0x30)   # table stripe
HAIR   = RGBColor(0x2C, 0x36, 0x44)   # hairline rules
HAIR2  = RGBColor(0x3D, 0x4A, 0x5C)   # brighter hairline

LCD    = RGBColor(0x63, 0xD2, 0xE8)   # DKM-440 backlight cyan — primary
LCD_D  = RGBColor(0x2E, 0x7D, 0x8E)   # dimmed LCD
SEG    = RGBColor(0xFF, 0x44, 0x38)   # CLASS 305D seven-segment red — failure
UYARI  = RGBColor(0xFF, 0xA9, 0x28)   # UYARI lamp amber — unproven / partial
COPPER = RGBColor(0xC8, 0x9A, 0x5B)   # ESP8266 gold traces — the neural thread
GREEN  = RGBColor(0x4A, 0xD9, 0x91)   # proven

TEXT   = RGBColor(0xE6, 0xED, 0xF3)
MUTED  = RGBColor(0x84, 0x94, 0xA6)
DIM    = RGBColor(0x5A, 0x68, 0x78)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)

# ---------------------------------------------------------------- type
DISP = "Bahnschrift SemiBold"   # headings
DISP_L = "Bahnschrift"          # light display, for large numerals
BODY = "Segoe UI"               # prose
MONO = "Consolas"               # every number, key, topic, payload

SW = Inches(13.333)
SH = Inches(7.5)

# the signature rail — five stages of the signal chain
CHAIN = [("meter", "METER"), ("gw", "GATEWAY"), ("broker", "BROKER"),
         ("phone", "PHONE"), ("net", "NET")]


# ---------------------------------------------------------------- measurement
# python-pptx cannot lay out text, and a textbox silently grows past whatever
# height you gave it — which is how slides end up with paragraphs sitting on
# top of each other. Measure with the real font files instead of guessing.
_WINF = r"C:\Windows\Fonts"
_FILES = {
    ("Bahnschrift SemiBold", False): ("bahnschrift.ttf", 1.06),
    ("Bahnschrift SemiBold", True): ("bahnschrift.ttf", 1.10),
    ("Bahnschrift", False): ("bahnschrift.ttf", 1.00),
    ("Segoe UI", False): ("segoeui.ttf", 1.0),
    ("Segoe UI", True): ("segoeuib.ttf", 1.0),
    ("Consolas", False): ("consola.ttf", 1.0),
    ("Consolas", True): ("consolab.ttf", 1.0),
}
_CACHE = {}
_PXPT = 96.0 / 72.0     # PowerPoint lays out at 96 dpi


def _pil(font, size, bold=False):
    key = (font, round(size, 1), bold)
    if key in _CACHE:
        return _CACHE[key]
    fname, fudge = _FILES.get((font, bold), _FILES.get((font, False),
                                                       ("segoeui.ttf", 1.0)))
    path = os.path.join(_WINF, fname)
    try:
        f = ImageFont.truetype(path, max(1, int(round(size * _PXPT * 4))))
    except Exception:
        f = ImageFont.load_default()
    _CACHE[key] = (f, fudge)
    return _CACHE[key]


def text_w(body, font=None, size=13, bold=False):
    """Rendered width of a single line, in inches."""
    font = font or BODY
    f, fudge = _pil(font, size, bold)
    return f.getlength(body) / 4.0 / 96.0 * fudge


def wrap(body, width, font=None, size=13, bold=False):
    """Greedy word wrap at `width` inches. Returns the list of lines."""
    font = font or BODY
    out = []
    for para in str(body).split("\n"):
        if not para:
            out.append("")
            continue
        line = ""
        for word in para.split(" "):
            trial = word if not line else line + " " + word
            if text_w(trial, font, size, bold) <= width or not line:
                line = trial
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


# PowerPoint applies line_spacing to the font's line box, not to the point
# size, and that box is about 1.2x the point size for every face used here.
# Getting this constant wrong is what pushes a code block out of its panel.
LINEBOX = 1.21


def text_h(body, width, font=None, size=13, spacing=1.12, bold=False,
           space_after=0):
    """Height a wrapped block will actually occupy, in inches."""
    lines = wrap(body, width, font, size, bold)
    paras = str(body).count("\n") + 1
    return (len(lines) * size * LINEBOX * spacing
            + max(0, paras - 1) * space_after) / 72.0


def shrink_to_fit(body, width, font=None, size=13, bold=False, min_size=11,
                  lines=1):
    """Largest size ≤ `size` at which `body` wraps to at most `lines` lines."""
    s = size
    while s > min_size and len(wrap(body, width, font, s, bold)) > lines:
        s -= 0.5
    return s


# ---------------------------------------------------------------- primitives
def _solid(shape, color):
    shape.fill.solid()
    shape.fill.fore_color.rgb = color


def _noline(shape):
    shape.line.fill.background()


def _shadow_off(shape):
    try:
        shape.shadow.inherit = False
    except Exception:
        pass


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def bg(slide, color=PANEL):
    """Full-bleed ground pushed behind everything else on the slide."""
    r = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, SH)
    _solid(r, color)
    _noline(r)
    _shadow_off(r)
    slide.shapes._spTree.remove(r._element)
    slide.shapes._spTree.insert(2, r._element)
    return r


def box(slide, x, y, w, h, fill=None, line=None, line_w=1.0, radius=0.0):
    shp = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    s = slide.shapes.add_shape(shp, Inches(x), Inches(y), Inches(w), Inches(h))
    if radius:
        try:
            s.adjustments[0] = radius
        except Exception:
            pass
    if fill is None:
        s.fill.background()
    else:
        _solid(s, fill)
    if line is None:
        _noline(s)
    else:
        s.line.color.rgb = line
        s.line.width = Pt(line_w)
    _shadow_off(s)
    s.text_frame.word_wrap = True
    return s


def rule(slide, x, y, w, color=HAIR, weight=0.75):
    """A hairline. Drawn as a thin rectangle so it renders identically everywhere."""
    return box(slide, x, y, w, Pt(weight).inches, fill=color)


def vrule(slide, x, y, h, color=HAIR, weight=0.75):
    return box(slide, x, y, Pt(weight).inches, h, fill=color)


def text(slide, x, y, w, h, body, size=13, color=TEXT, font=BODY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.12, space_after=0,
         italic=False):
    """Multi-line text box. `body` may contain \\n; each line becomes a paragraph."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(str(body).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.name = font
        r.font.bold = bold
        r.font.italic = italic
        r.font.color.rgb = color
    return tb


def rich(slide, x, y, w, h, parts, size=13, spacing=1.15, space_after=6,
         align=PP_ALIGN.LEFT):
    """Paragraphs built from (text, font, size, color, bold) runs.

    `parts` is a list of paragraphs; each paragraph is a list of run tuples.
    Run tuples are (text,) | (text, color) | (text, color, font) |
    (text, color, font, bold) | (text, color, font, bold, size).
    """
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, para in enumerate(parts):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        p.space_after = Pt(space_after)
        for run in para:
            t = run[0]
            color = run[1] if len(run) > 1 and run[1] is not None else TEXT
            font = run[2] if len(run) > 2 and run[2] is not None else BODY
            bold = run[3] if len(run) > 3 else False
            sz = run[4] if len(run) > 4 else size
            r = p.add_run()
            r.text = t
            r.font.size = Pt(sz)
            r.font.name = font
            r.font.bold = bold
            r.font.color.rgb = color
    return tb


def fit(shape, body, size=13, color=TEXT, font=BODY, bold=False,
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, spacing=1.1):
    """Put text inside an existing shape."""
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, ln in enumerate(str(body).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.name = font
        r.font.bold = bold
        r.font.color.rgb = color
    return shape


def arrow(slide, x1, y1, x2, y2, color=HAIR2, width=1.5, dashed=False, head=True):
    cn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                    Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    cn.line.color.rgb = color
    cn.line.width = Pt(width)
    ln = cn.line._get_or_add_ln()
    if dashed:
        ln.append(ln.makeelement(qn('a:prstDash'), {'val': 'dash'}))
    if head:
        ln.append(ln.makeelement(qn('a:tailEnd'),
                                 {'type': 'triangle', 'w': 'med', 'len': 'med'}))
    _shadow_off(cn)
    return cn


def picture(slide, path, x, y, w=None, h=None):
    kw = {}
    if w is not None:
        kw["width"] = Inches(w)
    if h is not None:
        kw["height"] = Inches(h)
    return slide.shapes.add_picture(path, Inches(x), Inches(y), **kw)


# ---------------------------------------------------------------- signature
def rail(slide, active=(), x=7.28, y=0.60, span=5.35):
    """The signal chain, top-right of every content slide.

    Five stages, hairline-linked. Whichever stages the slide is about are lit in
    LCD cyan; the rest stay dim. It answers 'where in the system are we now?'
    without a word of explanation, and it is the one element repeated on every
    slide — so it has to earn its place by carrying information, not decoration.
    """
    active = set(active)
    n = len(CHAIN)
    step = span / (n - 1)
    dot = 0.085
    cy = y + dot / 2
    for i, (key, lab) in enumerate(CHAIN):
        cx = x + i * step
        on = key in active
        if i < n - 1:
            nxt = CHAIN[i + 1][0]
            seg_on = on and nxt in active
            rule(slide, cx + dot * 0.9, cy - 0.004, step - dot * 1.8,
                 color=LCD_D if seg_on else HAIR, weight=1.0)
        d = box(slide, cx - dot / 2, y, dot, dot,
                fill=LCD if on else PANEL, line=LCD if on else HAIR2, line_w=1.0)
        _shadow_off(d)
        text(slide, cx - step / 2, y + 0.16, step, 0.22, lab,
             size=7.5, color=LCD if on else DIM, font=DISP,
             align=PP_ALIGN.CENTER, spacing=1.0)


# ---------------------------------------------------------------- chrome
def content(prs, title, kicker=None, active=(), accent=LCD):
    """Standard content slide: kicker, title, signal rail, header hairline.

    The title is bottom-anchored against the header rule and shrunk until it
    fits the space left of the rail, so a long title grows upward into the
    margin instead of sliding down through the rule.
    """
    s = blank(prs)
    bg(s)
    if kicker:
        text(s, 0.72, 0.30, 6.4, 0.24, kicker.upper(), size=9, color=accent,
             font=MONO, spacing=1.0)
    tw = 6.42
    size = shrink_to_fit(title, tw, DISP, 27, min_size=19, lines=1)
    if size < 21:                       # two lines beat a shrunken headline
        size = shrink_to_fit(title, tw, DISP, 27, min_size=20, lines=2)
    text(s, 0.70, 0.54, tw, 0.70, title, size=size, color=TEXT, font=DISP,
         spacing=1.0, anchor=MSO_ANCHOR.BOTTOM)
    rail(s, active)
    rule(s, 0.70, 1.34, 11.93, color=HAIR)
    box(s, 0.70, 1.335, 0.62, Pt(2.0).inches, fill=accent)
    return s


def block(slide, x, y, w, body, size=13, color=TEXT, font=BODY, bold=False,
          spacing=1.42, gap=0.0, align=PP_ALIGN.LEFT):
    """Draw a text block and return the y where the next element may start."""
    h = text_h(body, w, font, size, spacing, bold)
    text(slide, x, y, w, h, body, size=size, color=color, font=font, bold=bold,
         align=align, spacing=spacing)
    return y + h + gap


def divider(prs, kicker, title, blurb, accent=LCD, active=()):
    """Section break. Full-bleed panel, accent stripe down the left edge."""
    s = blank(prs)
    bg(s)
    box(s, 0, 0, 0.16, 7.5, fill=accent)
    text(s, 1.05, 2.62, 9.4, 0.28, kicker.upper(), size=11, color=accent,
         font=MONO, spacing=1.0)
    text(s, 1.02, 2.98, 10.4, 1.1, title, size=44, color=TEXT, font=DISP,
         spacing=0.96)
    rule(s, 1.05, 4.28, 1.5, color=accent, weight=2.0)
    if blurb:
        text(s, 1.05, 4.62, 8.2, 0.9, blurb, size=13.5, color=MUTED, font=BODY,
             spacing=1.35)
    rail(s, active, x=7.28, y=6.55)
    return s


def footer(slide, idx, left="OSOS · DKM-440 remote meter reading"):
    rule(slide, 0.70, 6.98, 11.93, color=HAIR)
    text(slide, 0.70, 7.10, 8.0, 0.26, left, size=8.5, color=DIM, font=MONO)
    text(slide, 11.13, 7.10, 1.5, 0.26, f"{idx:02d}", size=8.5, color=DIM,
         font=MONO, align=PP_ALIGN.RIGHT)


# ---------------------------------------------------------------- components
def card(slide, x, y, w, h, accent=None, fill=PANEL2):
    """Raised sub-panel. Optional accent stripe along the top edge."""
    c = box(slide, x, y, w, h, fill=fill, line=HAIR, line_w=1.0)
    if accent is not None:
        box(slide, x, y, w, Pt(2.5).inches, fill=accent)
    return c


def stat(slide, x, y, w, value, label, color=LCD, size=30, sub=None):
    """One measured number, monospaced, with its label beneath."""
    text(slide, x, y, w, 0.5, value, size=size, color=color, font=MONO,
         spacing=1.0)
    text(slide, x, y + size / 72.0 * 1.02, w, 0.24, label.upper(), size=8.5,
         color=MUTED, font=DISP, spacing=1.0)
    if sub:
        text(slide, x, y + size / 72.0 * 1.02 + 0.20, w, 0.24, sub, size=8.5,
             color=DIM, font=MONO, spacing=1.0)


def chip(slide, x, y, w, h, body, color, filled=False, size=8.5):
    c = box(slide, x, y, w, h,
            fill=color if filled else None,
            line=None if filled else color, line_w=1.0, radius=0.32)
    fit(c, body, size=size, color=PANEL if filled else color, font=DISP,
        bold=False)
    return c


def kv_table(slide, x, y, w, rows, col1=None, row_h=0.34, size=11,
             head=None, accent=LCD, mono_right=True):
    """Two-column key/value list on hairlines. No table object — full control."""
    col1 = col1 if col1 is not None else w * 0.46
    yy = y
    if head:
        text(slide, x, yy, col1, 0.22, head[0].upper(), size=8, color=accent,
             font=DISP, spacing=1.0)
        text(slide, x + col1, yy, w - col1, 0.22, head[1].upper(), size=8,
             color=accent, font=DISP, spacing=1.0)
        yy += 0.26
        rule(slide, x, yy, w, color=HAIR2)
        yy += 0.10
    for i, row in enumerate(rows):
        k, v = row[0], row[1]
        vcolor = row[2] if len(row) > 2 else TEXT
        text(slide, x, yy, col1 - 0.12, row_h, k, size=size, color=MUTED,
             font=BODY, spacing=1.05)
        text(slide, x + col1, yy, w - col1, row_h, v, size=size, color=vcolor,
             font=MONO if mono_right else BODY, spacing=1.05)
        yy += row_h
        if i < len(rows) - 1:
            rule(slide, x, yy - 0.08, w, color=HAIR)
    return yy


def bullets(slide, x, y, w, h, items, marker=LCD, size=12.5, gap=8):
    """Lead-in bold phrase then prose. Marker is a small square, not a glyph
    bullet — it matches the rail dots and keeps the instrument metaphor."""
    paras = []
    for head, body in items:
        para = []
        if head:
            para.append(("— ", marker, MONO, True, size))
            para.append((head, TEXT, BODY, True, size))
            if body:
                para.append(("  " + body, MUTED, BODY, False, size))
        else:
            para.append((body, MUTED, BODY, False, size))
        paras.append(para)
    return rich(slide, x, y, w, h, paras, size=size, spacing=1.22,
                space_after=gap)


def code(slide, x, y, w, h, lines, size=10.5, fill=RGBColor(0x0A, 0x0E, 0x13),
         accent=LCD, title=None):
    """Monospaced listing panel. `lines` may be (text, color) pairs.

    The panel grows if the listing needs more room than `h` — a code block that
    spills out of its own frame is the single ugliest thing a deck can do.
    """
    need = (len(lines) * size * LINEBOX * 1.30 / 72.0 + 0.30
            + (0.32 if title else 0.0))
    h = max(h, need)
    card(slide, x, y, w, h, fill=fill)
    box(slide, x, y, Pt(2.0).inches, h, fill=accent)
    ty = y + 0.14
    if title:
        text(slide, x + 0.22, ty, w - 0.44, 0.22, title, size=8.5, color=accent,
             font=DISP, spacing=1.0)
        ty += 0.30
    paras = []
    for ln in lines:
        if isinstance(ln, tuple):
            paras.append([(ln[0], ln[1], MONO, False, size)])
        else:
            paras.append([(ln, TEXT, MONO, False, size)])
    rich(slide, x + 0.22, ty, w - 0.44, h - (ty - y) - 0.12, paras, size=size,
         spacing=1.30, space_after=0)


def caption(slide, x, y, w, body, color=DIM, size=8.5):
    return text(slide, x, y, w, 0.5, body, size=size, color=color, font=MONO,
                spacing=1.25)
