"""Builds the SIH 2026 presentation for SatQuery AI.

Every shape is a native PowerPoint object, so the deck stays fully editable:
re-run this script after changing content, or edit the .pptx directly.

    python presentation/build_deck.py
"""

from __future__ import annotations

import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

# ============================================================
# DESIGN TOKENS
# ============================================================
SW, SH = 13.333, 7.5
M = 0.42                      # page margin
CW = SW - 2 * M               # content width  = 12.493
TOP = 0.82                    # first usable y on a content slide
BOT = 7.14                    # last usable y

FONT = "Segoe UI"

NAVY = RGBColor(0x0B, 0x25, 0x45)
NAVY2 = RGBColor(0x14, 0x3A, 0x66)
BLUE = RGBColor(0x1B, 0x59, 0xA6)
BLUE_L = RGBColor(0xE7, 0xEE, 0xF8)
BLUE_LL = RGBColor(0xF4, 0xF7, 0xFC)
ORANGE = RGBColor(0xF5, 0x82, 0x20)
ORANGE_D = RGBColor(0xC4, 0x5F, 0x0A)
ORANGE_L = RGBColor(0xFD, 0xEF, 0xDF)
GREEN = RGBColor(0x1B, 0x7A, 0x4B)
GREEN_L = RGBColor(0xE3, 0xF3, 0xEA)
AMBER = RGBColor(0xA9, 0x73, 0x00)
AMBER_L = RGBColor(0xFD, 0xF4, 0xDC)
RED = RGBColor(0xB3, 0x33, 0x28)
RED_L = RGBColor(0xFB, 0xE8, 0xE6)
GRAY = RGBColor(0x5C, 0x69, 0x7A)
GRAY_L = RGBColor(0xF1, 0xF4, 0xF8)
GRAY_B = RGBColor(0xC6, 0xCF, 0xDA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
TEXT = RGBColor(0x15, 0x1E, 0x2B)
MUTED = RGBColor(0x6B, 0x78, 0x89)
PALE = RGBColor(0xB9, 0xC7, 0xDB)

L, C, R = PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.RIGHT
TOP_A, MID_A = MSO_ANCHOR.TOP, MSO_ANCHOR.MIDDLE

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(SW), Inches(SH)
BLANK = prs.slide_layouts[6]


# ============================================================
# PRIMITIVES
# ============================================================
def t(txt, s=10, b=False, c=TEXT, align=None, i=False, space=None, ls=None):
    return {"t": txt, "s": s, "b": b, "c": c, "align": align, "i": i,
            "space": space, "ls": ls}


def fill_text(shape, items, anchor=MID_A, align=C, margin=0.05):
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    first = True
    for it in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = it["align"] or align
        if it["space"]:
            p.space_before = Pt(it["space"])
        if it["ls"]:
            p.line_spacing = it["ls"]
        r = p.add_run()
        r.text = it["t"]
        f = r.font
        f.name, f.size, f.bold, f.italic = FONT, Pt(it["s"]), it["b"], it["i"]
        f.color.rgb = it["c"]
    return shape


def no_shadow(shape):
    try:
        shape.shadow.inherit = False
    except Exception:
        pass


def dash(shape, val="dash"):
    ln = shape.line._get_or_add_ln()
    for old in ln.findall(qn("a:prstDash")):
        ln.remove(old)
    ln.append(ln.makeelement(qn("a:prstDash"), {"val": val}))


def vertical_text(shape, val="vert270"):
    shape.text_frame._txBody.bodyPr.set("vert", val)


def box(sl, x, y, w, h, items=None, fill=WHITE, line=None, lw=1.0,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, rad=0.14, anchor=MID_A,
        align=C, margin=0.05, dashed=False):
    sh = sl.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    no_shadow(sh)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sh.adjustments[0] = rad
        except Exception:
            pass
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
        if dashed:
            dash(sh)
    if items:
        fill_text(sh, items, anchor=anchor, align=align, margin=margin)
    else:
        sh.text_frame.text = ""
    return sh


def tb(sl, x, y, w, h, items, anchor=TOP_A, align=L):
    sh = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    fill_text(sh, items, anchor=anchor, align=align, margin=0.0)
    return sh


def arrow(sl, x, y, w, h, direction="right", fill=GRAY_B):
    shp = {"right": MSO_SHAPE.RIGHT_ARROW, "down": MSO_SHAPE.DOWN_ARROW,
           "up": MSO_SHAPE.UP_ARROW, "left": MSO_SHAPE.LEFT_ARROW}[direction]
    sh = sl.shapes.add_shape(shp, Inches(x), Inches(y), Inches(w), Inches(h))
    no_shadow(sh)
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.fill.background()
    return sh


def chain_arrow(sl, x, ycenter, w=0.20):
    arrow(sl, x, ycenter - 0.075, w, 0.15, "right", GRAY_B)


def label(sl, x, y, w, txt, c=NAVY, s=12.5):
    """A small section heading with an orange tick in front of it."""
    box(sl, x, y + 0.045, 0.055, 0.17, fill=ORANGE, line=None,
        shape=MSO_SHAPE.RECTANGLE)
    tb(sl, x + 0.14, y, w, 0.26, [t(txt.upper(), s=s, b=True, c=c)],
       anchor=MID_A, align=L)


def slide(title=None, num=None):
    sl = prs.slides.add_slide(BLANK)
    if title is not None:
        box(sl, 0, 0, SW, 0.60, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
        box(sl, 0, 0.60, SW, 0.055, fill=ORANGE, shape=MSO_SHAPE.RECTANGLE)
        tb(sl, M, 0.02, 8.6, 0.56, [t(title, s=21, b=True, c=WHITE)],
           anchor=MID_A, align=L)
        tb(sl, 8.2, 0.02, SW - 8.2 - M, 0.56,
           [t("SIH 2026   ·   SatQuery AI   ·   PS SIH26167", s=9.5, c=PALE)],
           anchor=MID_A, align=R)
    if num is not None:
        tb(sl, SW - 1.2, SH - 0.36, 0.8, 0.24, [t(str(num), s=9, c=MUTED)],
           anchor=MID_A, align=R)
    return sl


def stat(sl, x, y, w, h, big, small, accent=BLUE, fill=BLUE_L):
    box(sl, x, y, w, h, [
        t(big, s=27, b=True, c=accent, ls=0.95),
        t(small, s=8.5, c=TEXT, space=2, ls=0.95),
    ], fill=fill, line=None)


def status_row(sl, x, y, w, h, pill, pill_fill, pill_c, text_main, text_sub):
    box(sl, x, y, w, h, fill=GRAY_L, line=None)
    box(sl, x + 0.06, y + 0.06, 1.46, h - 0.12,
        [t(pill, s=7.8, b=True, c=pill_c)], fill=pill_fill, line=None, rad=0.3)
    tb(sl, x + 1.62, y, w - 1.72, h, [
        t(text_main, s=9.5, b=True, c=TEXT, ls=0.95),
        t(text_sub, s=8, c=MUTED, ls=0.95),
    ], anchor=MID_A, align=L)


def card(sl, x, y, w, h, head, body, accent=BLUE, fill=WHITE, head_s=10.5,
         body_s=8.3, line=GRAY_B):
    sh = box(sl, x, y, w, h, fill=fill, line=line, lw=0.75, anchor=TOP_A)
    box(sl, x, y, 0.06, h, fill=accent, line=None, shape=MSO_SHAPE.RECTANGLE)
    fill_text(sh, [
        t(head, s=head_s, b=True, c=accent, align=L, ls=0.95),
        t(body, s=body_s, c=TEXT, align=L, space=4, ls=1.0),
    ], anchor=TOP_A, align=L, margin=0.13)
    return sh


# ============================================================
# SLIDE 1 — TITLE
# ============================================================
def slide1():
    sl = slide()
    box(sl, 0, 0, SW, SH, fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
    box(sl, 0, 0, SW, 0.13, fill=ORANGE, shape=MSO_SHAPE.RECTANGLE)
    box(sl, 0, SH - 1.62, SW, 1.62, fill=NAVY2, shape=MSO_SHAPE.RECTANGLE)

    tb(sl, M + 0.1, 1.05, 8.8, 0.5,
       [t("SMART INDIA HACKATHON 2026", s=12, b=True, c=ORANGE)], align=L)
    tb(sl, M + 0.05, 1.48, 9.0, 1.15,
       [t("SatQuery AI", s=54, b=True, c=WHITE, ls=0.9)], align=L)
    box(sl, M + 0.1, 2.62, 1.7, 0.05, fill=ORANGE, shape=MSO_SHAPE.RECTANGLE)
    tb(sl, M + 0.1, 2.82, 8.6, 0.9, [
        t("Natural language in.  Validated remote-sensing workflows out.",
          s=17, b=True, c=WHITE, ls=1.0),
    ], align=L)
    tb(sl, M + 0.1, 3.62, 8.6, 1.5, [
        t("An agentic reasoning and orchestration layer that turns a geospatial "
          "question into a decomposed, capability-matched, deterministically "
          "validated remote-sensing workflow — and returns an interpretable "
          "answer with its evidence.", s=11.5, c=PALE, ls=1.15),
    ], align=L)

    # Right-hand mini pipeline
    stages = [("Natural-language intent", ORANGE),
              ("Reason · decompose · plan", ORANGE),
              ("Deterministic validation", WHITE),
              ("Specialist RS execution", WHITE),
              ("Evidence-backed answer", WHITE)]
    x, w, y, h, gap = 9.55, 3.35, 1.05, 0.62, 0.24
    for i, (txt, c) in enumerate(stages):
        yy = y + i * (h + gap)
        outline = ORANGE if c == ORANGE else RGBColor(0x3E, 0x62, 0x8E)
        box(sl, x, yy, w, h, [t(txt, s=10, b=True, c=c)],
            fill=None, line=outline, lw=1.25)
        if i < len(stages) - 1:
            arrow(sl, x + w / 2 - 0.09, yy + h + 0.045, 0.18, 0.15, "down",
                  RGBColor(0x3E, 0x62, 0x8E))

    # Footer identity grid
    fields = [("Problem Statement ID", "SIH26167"),
              ("Problem Statement Title", "[ FILL FROM SIH PORTAL ]"),
              ("Theme", "[ FILL ]"),
              ("PS Category", "Software"),
              ("Team ID", "[ FILL ]"),
              ("Team Name", "[ FILL ]")]
    fw = (CW - 5 * 0.16) / 6
    for i, (k, v) in enumerate(fields):
        xx = M + i * (fw + 0.16)
        tb(sl, xx, SH - 1.30, fw, 0.24, [t(k.upper(), s=7.5, b=True, c=ORANGE)],
           align=L)
        tb(sl, xx, SH - 1.03, fw, 0.52, [t(v, s=10, b=True, c=WHITE, ls=1.0)],
           align=L)
    return sl


# ============================================================
# SLIDE 2 — PROPOSED SOLUTION
# ============================================================
def slide2():
    sl = slide("Proposed Solution", 2)

    # Thesis banner
    box(sl, M, 0.84, CW, 0.66, fill=BLUE_L, line=None)
    box(sl, M, 0.84, 0.07, 0.66, fill=ORANGE, line=None,
        shape=MSO_SHAPE.RECTANGLE)
    tb(sl, M + 0.24, 0.84, CW - 0.4, 0.66, [
        t("The model decides WHAT should happen.  Deterministic code verifies "
          "WHETHER it can safely happen.", s=13.5, b=True, c=NAVY, ls=1.0),
    ], anchor=MID_A, align=L)

    label(sl, M, 1.62, 6.0, "One question, end to end")

    box(sl, M, 1.94, CW, 0.46, [
        t("“Identify areas where vegetation decreased significantly "
          "between 2023 and 2025.”", s=12.5, b=True, c=WHITE, i=True)
    ], fill=NAVY, line=None)

    steps = [
        ("1  UNDERSTAND", "intent, entities,\nregion, 2023 ↔ 2025", ORANGE),
        ("2  DECOMPOSE", "7 subtasks planned\nfor this question", ORANGE),
        ("3  INFER INPUTS", "optical · RED+NIR\n2 dated scenes · CRS", ORANGE),
        ("4  SELECT", "change_detection\n(index = NDVI)", BLUE),
        ("5  VALIDATE", "bands ✓ count ✓\nCRS ✓ dates ✓", RED),
        ("6  EXECUTE", "NDVI ×2 → align\n→ Δ → σ-threshold", GREEN),
        ("7  INTEGRATE", "evidence → map,\nstats, explanation", NAVY),
    ]
    bw, gap, by, bh = 1.55, 0.27, 2.52, 1.42
    for i, (head, sub, accent) in enumerate(steps):
        x = M + i * (bw + gap)
        tint = {ORANGE: ORANGE_L, BLUE: BLUE_L, RED: RED_L,
                GREEN: GREEN_L, NAVY: BLUE_L}[accent]
        box(sl, x, by, bw, bh, [
            t(head, s=9, b=True, c=accent, ls=0.95),
            t(sub, s=7.6, c=TEXT, space=4, ls=1.05),
        ], fill=tint, line=accent, lw=0.9)
        if i < len(steps) - 1:
            chain_arrow(sl, x + bw + 0.035, by + bh / 2)

    box(sl, M, 4.12, CW, 0.60, [
        t("Output:   loss percentage  ·  spatial hotspot map  ·  "
          "per-region statistics  ·  plain-language explanation  ·  "
          "full provenance of every step",
          s=11, b=True, c=NAVY)
    ], fill=ORANGE_L, line=ORANGE, lw=1.0)

    label(sl, M, 4.90, 6.0, "Innovation and uniqueness")
    cards = [
        ("Reasoning ≠ verification",
         "The model proposes a workflow; the registry and validator decide "
         "whether it may run. A reasoning error becomes a precise rejection, "
         "never a confident wrong map."),
        ("Capability-aware selection",
         "Tools are matched against declared contracts — modality, required "
         "bands, image count, temporal pairing — not by keyword similarity."),
        ("Composable operations",
         "A single question can chain index computation, co-registration, "
         "differencing, thresholding and spatial aggregation into one workflow."),
        ("Extensible by declaration",
         "A new model joins by adding a registry entry and a binding. The "
         "controller, validator and API stay unchanged."),
    ]
    cw = (CW - 3 * 0.27) / 4
    for i, (h, b) in enumerate(cards):
        card(sl, M + i * (cw + 0.27), 5.22, cw, 1.55, h, b,
             accent=[ORANGE, BLUE, GREEN, NAVY][i], fill=BLUE_LL)
    return sl


# ============================================================
# SLIDE 3 — TECHNICAL APPROACH (architecture)
# ============================================================
def slide3():
    sl = slide("Technical Approach", 3)

    tb(sl, M, 0.80, 7.3, 0.30, [
        t("AI reasoning proposes  →  deterministic layers verify, execute "
          "and explain", s=11.5, b=True, c=ORANGE_D)], anchor=MID_A, align=L)
    leg = [("AI reasoning", ORANGE_L, ORANGE), ("Deterministic", BLUE_L, BLUE),
           ("Live today", GREEN_L, GREEN), ("Planned", GRAY_L, GRAY_B)]
    lx = 7.85
    for name, f, ln in leg:
        w = 1.24
        box(sl, lx, 0.83, 0.16, 0.16, fill=f, line=ln, lw=0.9,
            shape=MSO_SHAPE.RECTANGLE)
        tb(sl, lx + 0.22, 0.78, w, 0.26, [t(name, s=8, c=MUTED)],
           anchor=MID_A, align=L)
        lx += w + 0.09

    GX, GW = M, 1.62                    # gutter
    BX, BW = 2.16, 10.05                # band
    RX, RW = 12.30, 0.61                # right rail

    def gutter(y, h, name, sub, c=NAVY):
        tb(sl, GX, y, GW, h, [
            t(name, s=9.2, b=True, c=c, align=R, ls=0.95),
            t(sub, s=7.3, c=MUTED, align=R, space=2, ls=0.95),
        ], anchor=MID_A, align=R)

    y = 1.22
    g = 0.11

    # 1 — interface
    h = 0.50
    gutter(y, h, "INTERFACE", "what the user gives")
    box(sl, BX, y, BW, h, [
        t("Natural-language question   +   satellite imagery (GeoTIFF / "
          "Sentinel-2 / Landsat)   +   optional region and dates",
          s=9.5, b=True, c=NAVY)], fill=WHITE, line=NAVY, lw=1.0)
    y += h + g

    # 2 — reasoning
    h = 0.80
    gutter(y, h, "REASONING", "LLM proposes", ORANGE_D)
    box(sl, BX, y, BW, h, fill=ORANGE_L, line=ORANGE, lw=1.1)
    inner = [("Query understanding",
              "intent · entities · spatial + temporal constraints"),
             ("Task decomposition",
              "one question → ordered executable subtasks"),
             ("Input requirement inference",
              "modality · bands · image count · metadata")]
    iw = (BW - 0.30 - 2 * 0.14) / 3
    for i, (a, b) in enumerate(inner):
        box(sl, BX + 0.15 + i * (iw + 0.14), y + 0.10, iw, h - 0.20, [
            t(a, s=9, b=True, c=ORANGE_D, ls=0.95),
            t(b, s=7.3, c=TEXT, space=2, ls=0.95)], fill=WHITE, line=None)
    y += h + g

    # 3 — registry
    h = 0.56
    gutter(y, h, "CAPABILITY REGISTRY", "the contract", BLUE)
    box(sl, BX, y, BW, h, fill=WHITE, line=BLUE, lw=1.4)
    tb(sl, BX + 0.16, y, 3.15, h, [
        t("8 versioned capabilities", s=9.5, b=True, c=BLUE, ls=0.95),
        t("the only functions the agent may call", s=7.3, c=MUTED, ls=0.95)],
       anchor=MID_A, align=L)
    box(sl, BX + 3.35, y + 0.09, BW - 3.51, h - 0.18, [
        t("tool_id  ·  description  ·  supported modalities  ·  required "
          "bands  ·  min/max images  ·  temporal-pair flag  ·  parameter "
          "schema", s=8, c=TEXT, ls=1.0),
        t("constrains capability selection AND supplies the constraints the "
          "validation gate enforces", s=7.3, b=True, c=BLUE, space=2, ls=0.95)],
        fill=BLUE_L, line=None)
    y += h + g

    # 4 — orchestration
    h = 0.80
    gutter(y, h, "ORCHESTRATION", "planning the run", BLUE)
    box(sl, BX, y, BW, h, fill=BLUE_L, line=BLUE, lw=1.1)
    inner = [("Capability selection",
              "match subtask against registry contracts"),
             ("Execution planning",
              "order, dependencies, intermediate artefacts"),
             ("Parameter configuration",
              "bands, scale/offset, thresholds, masking")]
    for i, (a, b) in enumerate(inner):
        box(sl, BX + 0.15 + i * (iw + 0.14), y + 0.10, iw, h - 0.20, [
            t(a, s=9, b=True, c=BLUE, ls=0.95),
            t(b, s=7.3, c=TEXT, space=2, ls=0.95)], fill=WHITE, line=None)
    y += h + g

    # 5 — validation gate
    h = 0.84
    gutter(y, h, "VALIDATION GATE", "hard boundary", RED)
    box(sl, BX, y, BW, h, fill=RED_L, line=RED, lw=2.0)
    tb(sl, BX + 0.18, y + 0.06, 7.05, h - 0.12, [
        t("DETERMINISTIC INPUT AND COMPATIBILITY VALIDATION",
          s=9.5, b=True, c=RED, ls=0.95),
        t("image count  ·  metadata present  ·  modality  ·  temporal "
          "information  ·  CRS  ·  required spectral bands (cross-vocabulary: "
          "B4 ≡ red)  ·  optical / SAR  ·  temporal-pair distinctness",
          s=7.6, c=TEXT, space=3, ls=1.05),
        t("No LLM opinion can bypass this. Nothing executes until it passes.",
          s=7.8, b=True, c=RED, space=3, ls=0.95)],
       anchor=MID_A, align=L)
    box(sl, BX + 7.40, y + 0.09, 1.20, h - 0.18,
        [t("✓  proceed", s=9, b=True, c=GREEN)], fill=GREEN_L, line=GREEN)
    box(sl, BX + 8.70, y + 0.09, BW - 8.86, h - 0.18, [
        t("✗  reject", s=9, b=True, c=RED, ls=0.95),
        t("with the exact reason", s=6.8, c=RED, ls=0.9)],
        fill=WHITE, line=RED)
    y += h + g

    # 6 — execution
    h = 1.02
    gutter(y, h, "REMOTE-SENSING EXECUTION", "specialist compute", GREEN)
    box(sl, BX, y, BW, h, fill=WHITE, line=GRAY_B, lw=1.0)
    live = ["NDVI", "NDWI", "NDBI", "Bi-temporal change detection"]
    planned = ["Satellite VQA", "Land-cover classification",
               "Object detection", "SAR analysis"]
    ew = (BW - 0.30 - 3 * 0.12) / 4
    for i, name in enumerate(live):
        box(sl, BX + 0.15 + i * (ew + 0.12), y + 0.09, ew, 0.38,
            [t(name, s=8.5, b=True, c=GREEN)], fill=GREEN_L, line=GREEN, lw=0.9)
    for i, name in enumerate(planned):
        s = box(sl, BX + 0.15 + i * (ew + 0.12), y + 0.55, ew, 0.38,
                [t(name, s=8.5, c=MUTED)], fill=GRAY_L, line=GRAY_B, lw=0.9)
        dash(s)
    y += h + g

    # 7 — evidence
    h = 0.72
    gutter(y, h, "EVIDENCE & RESULT", "making it an answer", NAVY)
    box(sl, BX, y, BW, h, fill=NAVY, line=None)
    tb(sl, BX + 0.18, y, 5.5, h, [
        t("Heterogeneous outputs", s=8.6, b=True, c=ORANGE, ls=0.95),
        t("raster · mask · bounding boxes · classes · statistics · "
          "temporal delta · confidence", s=7.6, c=PALE, ls=1.0)],
       anchor=MID_A, align=L)
    arrow(sl, BX + 5.72, y + h / 2 - 0.075, 0.22, 0.15, "right", ORANGE)
    box(sl, BX + 6.10, y + 0.10, BW - 6.26, h - 0.20, [
        t("Aggregated → spatially and temporally interpreted → "
          "human-readable answer + map + statistics + provenance",
          s=8.4, b=True, c=NAVY, ls=1.0)], fill=WHITE, line=None)

    # feedback rail
    top_of_reasoning = 1.22 + 0.50 + g
    bottom = y + h
    arrow(sl, RX, top_of_reasoning, RW, bottom - top_of_reasoning, "up",
          ORANGE)
    lbl = box(sl, RX - 0.02, top_of_reasoning + 0.55, RW + 0.04,
              bottom - top_of_reasoning - 1.0, fill=None, line=None)
    fill_text(lbl, [t("RE-PLAN  on failure, rejection or low confidence",
                      s=8, b=True, c=WHITE)], anchor=MID_A, align=C)
    vertical_text(lbl)
    return sl


# ============================================================
# SLIDE 4 — FEASIBILITY AND VIABILITY
# ============================================================
def slide4():
    sl = slide("Feasibility and Viability", 4)
    LX, LW_ = M, 7.30
    RX_, RW_ = 7.95, 4.96

    label(sl, LX, 0.84, 5.0, "Already built and proven")
    tiles = [("326", "automated tests\npassing"),
             ("8", "capabilities in the\nregistry"),
             ("4", "specialist tools\nexecuting today"),
             ("2", "interchangeable\nraster backends")]
    tw = (LW_ - 3 * 0.14) / 4
    for i, (big, small) in enumerate(tiles):
        stat(sl, LX + i * (tw + 0.14), 1.16, tw, 1.02, big, small,
             accent=[BLUE, BLUE, GREEN, ORANGE_D][i],
             fill=[BLUE_L, BLUE_L, GREEN_L, ORANGE_L][i])

    rows = [
        ("VALIDATED", GREEN_L, GREEN, "Ten-stage controller pipeline",
         "understanding → classification → planning → requirements → "
         "selection → validation → configuration → execution → integration"),
        ("VALIDATED", GREEN_L, GREEN, "Deterministic validator — 8 check families",
         "count, metadata, modality, temporal, CRS, bands, optical/SAR, pair distinctness"),
        ("VALIDATED", GREEN_L, GREEN, "Capability registry + implementation binding",
         "an implementation can never expose a capability the registry has not sanctioned"),
        ("VALIDATED", GREEN_L, GREEN, "NDVI, NDWI, NDBI on real rasters",
         "sensor scale/offset handling, SCL / QA_PIXEL cloud and shadow masking"),
        ("VALIDATED", GREEN_L, GREEN, "Bi-temporal change detection",
         "co-registration guard, Δ-index arithmetic, σ-based significance thresholding"),
        ("VALIDATED", GREEN_L, GREEN, "Dual raster backend",
         "rasterio/GDAL, plus a dependency-free GeoTIFF codec; tests prove both agree"),
        ("VALIDATED", GREEN_L, GREEN, "HTTP service — 8 endpoints",
         "submit, validate-only, list, fetch, artefact download, registry, health"),
        ("INTEGRATING", AMBER_L, AMBER, "LLM reasoning and decomposition layer",
         "the pipeline is already shaped to receive it; registry + validator keep the veto"),
        ("NEXT STAGE", GRAY_L, GRAY, "VQA, land-cover, detection, SAR specialists",
         "declared in the registry today; the executor reports them honestly as unbound"),
    ]
    ry, rh = 2.36, 0.46
    for i, (pill, pf, pc, m, s) in enumerate(rows):
        status_row(sl, LX, ry + i * (rh + 0.055), LW_, rh, pill, pf, pc, m, s)

    label(sl, RX_, 0.84, 4.0, "Risks and how we contain them")
    risks = [
        ("Reasoning proposes an invalid workflow",
         "The registry bounds what can be called and the validator bounds what "
         "can run. A bad plan is refused with a reason, not executed."),
        ("Heavy GDAL dependency blocks deployment",
         "A dependency-free GeoTIFF path ships alongside rasterio, and the test "
         "suite proves the two backends produce identical results."),
        ("A misaligned image pair yields a confident, wrong change map",
         "Alignment is checked on grid, CRS, pixel size and origin before any "
         "arithmetic — and refuses rather than silently resampling."),
        ("Cloud contamination distorts index statistics",
         "Sentinel-2 SCL and Landsat QA_PIXEL masking, plus baseline 04.00 "
         "scale/offset correction, are applied before aggregation."),
        ("New models force a core rewrite",
         "Adding a capability is a registry entry plus a binding. The "
         "controller, validator and API are untouched."),
    ]
    cy, ch = 1.16, 1.08
    for i, (h, b) in enumerate(risks):
        card(sl, RX_, cy + i * (ch + 0.075), RW_, ch, h, b,
             accent=[RED, ORANGE_D, RED, ORANGE_D, BLUE][i], fill=WHITE,
             head_s=9.5, body_s=8.0)
    return sl


# ============================================================
# SLIDE 5 — IMPACT AND BENEFITS
# ============================================================
def slide5():
    sl = slide("Impact and Benefits", 5)

    label(sl, M, 0.84, 6.0, "The change SatQuery makes")

    def strip(y, tag, tag_fill, tag_c, items, item_fill, item_line, item_c,
              bold=False):
        box(sl, M, y, 1.42, 0.56, [t(tag, s=8.5, b=True, c=tag_c)],
            fill=tag_fill, line=None)
        n = len(items)
        w = (CW - 1.42 - 0.12 - (n - 1) * 0.09) / n
        for i, it in enumerate(items):
            x = M + 1.54 + i * (w + 0.09)
            box(sl, x, y, w, 0.56, [t(it, s=7.8, b=bold, c=item_c, ls=1.0)],
                fill=item_fill, line=item_line, lw=0.8)
            if i < n - 1:
                chain_arrow(sl, x + w + 0.005, y + 0.28, 0.08)

    strip(1.16, "TODAY", GRAY_L, GRAY,
          ["Raw satellite\ndata", "Domain expert\nrequired",
           "Manual\npreprocessing", "Manual tool\nselection",
           "Isolated\nalgorithms", "Fragmented,\nunexplained results"],
          WHITE, GRAY_B, MUTED)
    strip(1.86, "SATQUERY", ORANGE, WHITE,
          ["Natural-language\nintent", "Task\nreasoning", "Workflow\ndecomposition",
           "Capability\nselection", "Deterministic\nvalidation",
           "Specialist RS\nexecution", "Evidence\nintegration",
           "Interpretable\ngeospatial answer"],
          BLUE_L, BLUE, NAVY, bold=True)

    label(sl, M, 2.66, 6.0, "Who this reaches")
    who = [
        ("Agriculture\ndepartments", "crop stress, sowing extent and seasonal "
         "vegetation loss without a GIS analyst in the loop"),
        ("Disaster\nresponse", "rapid before/after assessment of flood, fire "
         "and landslide extent from a plain question"),
        ("Urban planning\nbodies", "built-up growth and encroachment measured "
         "over time with a reproducible method"),
        ("Forest and\nenvironment", "deforestation and water-body change "
         "tracked with auditable, repeatable evidence"),
        ("Space and defence\nanalysts", "a controlled, extensible surface for "
         "adding new specialist models safely"),
        ("Students and\nresearchers", "remote-sensing analysis becomes "
         "accessible without mastering the toolchain first"),
    ]
    ww = (CW - 5 * 0.12) / 6
    for i, (h, b) in enumerate(who):
        box(sl, M + i * (ww + 0.12), 2.98, ww, 1.28, [
            t(h, s=9.5, b=True, c=NAVY, ls=0.95),
            t(b, s=7.4, c=TEXT, space=4, ls=1.05)],
            fill=BLUE_LL, line=GRAY_B, lw=0.75, anchor=TOP_A, margin=0.11)

    label(sl, M, 4.44, 6.0, "Benefits")
    bens = [
        ("Social", "Geospatial evidence stops being the preserve of trained "
         "specialists. A district officer can ask a question in their own "
         "words and receive a defensible, explained answer."),
        ("Economic", "Removes repeated manual preprocessing and per-task "
         "scripting. One controlled workflow layer serves many departments "
         "instead of each rebuilding its own analysis chain."),
        ("Environmental", "Makes routine monitoring of vegetation loss, water "
         "extent and built-up encroachment cheap enough to run often — which "
         "is what turns monitoring into intervention."),
        ("Operational", "Every answer carries its provenance: which tool ran, "
         "on which imagery, with which parameters. Results are reproducible "
         "and auditable, not one-off outputs."),
    ]
    bw = (CW - 3 * 0.27) / 4
    for i, (h, b) in enumerate(bens):
        card(sl, M + i * (bw + 0.27), 4.76, bw, 2.05, h, b,
             accent=[ORANGE_D, BLUE, GREEN, NAVY][i], fill=WHITE,
             head_s=12, body_s=9.0)
    return sl


# ============================================================
# SLIDE 6 — RESEARCH AND REFERENCES
# ============================================================
def slide6():
    sl = slide("Research and References", 6)

    label(sl, M, 0.84, 8.0,
          "Why the architecture is shaped this way")

    items = [
        ("Agentic planning and task decomposition",
         "Interleaved reasoning and acting lets one question become an ordered "
         "set of executable subtasks instead of a single opaque call.",
         "→ Reasoning layer", ORANGE_D),
        ("Schema-constrained tool calling",
         "A model calling arbitrary functions is unsafe on real data. Calls are "
         "restricted to declared signatures with typed parameters.",
         "→ Capability registry", BLUE),
        ("Capability-aware orchestration",
         "Selection is driven by each tool's declared input contract — modality, "
         "bands, image count — not by name similarity to the query.",
         "→ Selection stage", BLUE),
        ("Deterministic verification of model output",
         "Language models are strong proposers and unreliable verifiers, so "
         "technical admissibility is decided by code that cannot be persuaded.",
         "→ Validation gate", RED),
        ("Remote-sensing foundation models and VQA",
         "Pretrained geospatial and multimodal models supply scene-level "
         "understanding that index arithmetic alone cannot express.",
         "→ Execution layer (next stage)", GREEN),
        ("Multi-temporal analysis and provenance",
         "Change is only meaningful on co-registered pairs, and an answer is "
         "only trustworthy when the path that produced it is recorded.",
         "→ Execution + evidence integration", NAVY),
    ]
    cw = (CW - 2 * 0.18) / 3
    ch = 1.62
    for i, (h, b, where, c) in enumerate(items):
        x = M + (i % 3) * (cw + 0.18)
        y = 1.16 + (i // 3) * (ch + 0.16)
        sh = box(sl, x, y, cw, ch, fill=WHITE, line=GRAY_B, lw=0.75,
                 anchor=TOP_A)
        box(sl, x, y, 0.06, ch, fill=c, line=None, shape=MSO_SHAPE.RECTANGLE)
        fill_text(sh, [
            t(h, s=11, b=True, c=c, align=L, ls=0.95),
            t(b, s=9.0, c=TEXT, align=L, space=5, ls=1.1),
            t(where, s=8.5, b=True, c=MUTED, align=L, space=6, ls=0.95),
        ], anchor=TOP_A, align=L, margin=0.14)

    label(sl, M, 4.72, 8.0, "References")
    box(sl, M, 5.02, CW, 1.98, fill=GRAY_L, line=None, anchor=TOP_A)
    col_w = (CW - 0.5) / 2
    left_refs = [
        "Yao et al., ReAct: Synergizing Reasoning and Acting in Language "
        "Models, ICLR 2023.",
        "Schick et al., Toolformer: Language Models Can Teach Themselves to "
        "Use Tools, NeurIPS 2023.",
        "Patil et al., Gorilla: Large Language Model Connected with Massive "
        "APIs, 2023.",
        "Jakubik et al., Foundation Models for Generalist Geospatial "
        "Artificial Intelligence (Prithvi, IBM–NASA), 2023.",
    ]
    right_refs = [
        "Lobry et al., RSVQA: Visual Question Answering for Remote Sensing "
        "Data, IEEE TGRS 2020.",
        "Bastani et al., SatlasPretrain: A Large-Scale Dataset for Remote "
        "Sensing Image Understanding, ICCV 2023.",
        "ESA, Sentinel-2 Level-2A Product Specification — Scene "
        "Classification (SCL) and processing baseline 04.00 offsets.",
        "USGS, Landsat Collection 2 Level-2 Science Products — QA_PIXEL "
        "bit definitions.",
    ]
    for j, refs in enumerate((left_refs, right_refs)):
        blocks = []
        for k, r in enumerate(refs):
            blocks.append(t("•  " + r, s=8.6, c=TEXT, align=L,
                            space=0 if k == 0 else 7, ls=1.05))
        tb(sl, M + 0.22 + j * (col_w + 0.16), 5.16, col_w, 1.35, blocks,
           anchor=TOP_A, align=L)
    tb(sl, M + 0.22, 6.42, CW - 0.44, 0.34, [
        t("Implementation:  github.com/VinayakGupta-1/SatQuery-AI     ·     "
          "Live demo:  [ INSERT WEB DEMO LINK ]", s=9.5, b=True, c=NAVY)],
       anchor=MID_A, align=L)
    return sl


# ============================================================
# APPENDIX A1 — REGISTRY + VALIDATION DEEP DIVE
# ============================================================
def slideA1():
    sl = slide("Appendix — Capability contracts and the validation gate", 7)

    label(sl, M, 0.84, 6.0, "A registry entry is a contract")
    box(sl, M, 1.16, 6.05, 4.65, fill=WHITE, line=BLUE, lw=1.4, anchor=TOP_A)
    box(sl, M, 1.16, 6.05, 0.42, [t("change_detection", s=11, b=True, c=WHITE)],
        fill=BLUE, line=None)
    fields = [
        ("name", "Bi-Temporal Change Detection"),
        ("tool_type", "change_detection"),
        ("supported_modalities", "optical, SAR"),
        ("min / max images", "2 / 2"),
        ("requires_temporal_pair", "true"),
        ("parameters", "index, band overrides, threshold,\n"
                       "threshold_method, sigma_multiplier,\n"
                       "scale, offset, mask_band, sensor"),
        ("enabled", "true"),
    ]
    fy = 1.78
    for k, v in fields:
        lines = v.count("\n") + 1
        hh = 0.30 + 0.17 * (lines - 1)
        tb(sl, M + 0.18, fy, 1.95, hh, [t(k, s=9.2, b=True, c=BLUE)],
           anchor=TOP_A, align=L)
        tb(sl, M + 2.20, fy, 3.65, hh, [t(v, s=9.2, c=TEXT, ls=1.1)],
           anchor=TOP_A, align=L)
        fy += hh + 0.09
    tb(sl, M + 0.18, 5.24, 5.7, 0.48, [
        t("The agent may call this and nothing else. Capability selection and "
          "the validation gate both read from here.",
          s=8.6, b=True, i=True, c=MUTED, ls=1.05)],
       anchor=TOP_A, align=L)

    label(sl, 6.88, 0.84, 6.0, "The gate, in practice")
    ex = [
        ("Two images supplied?", "count checked against min/max from the registry", GREEN),
        ("Both optical?", "modality read from metadata, compared to the contract", GREEN),
        ("RED and NIR present?", "band names canonicalised first, so B4 ≡ red ≡ B04", GREEN),
        ("Acquisition dates present and different?", "a “change” between one date and itself is refused", GREEN),
        ("Same CRS, grid, pixel size and origin?", "checked before arithmetic — refuses, never silently resamples", GREEN),
    ]
    ey, eh = 1.16, 0.62
    for i, (q, why, c) in enumerate(ex):
        yy = ey + i * (eh + 0.09)
        box(sl, 6.88, yy, CW - 6.46, eh, fill=GRAY_L, line=None)
        box(sl, 6.96, yy + 0.09, 0.38, eh - 0.18, [t("✓", s=12, b=True, c=WHITE)],
            fill=c, line=None)
        tb(sl, 7.44, yy, CW + M - 7.60, eh, [
            t(q, s=9.3, b=True, c=TEXT, ls=0.95),
            t(why, s=7.8, c=MUTED, ls=0.95)], anchor=MID_A, align=L)

    box(sl, 6.88, 4.71, CW + M - 6.88, 1.10, fill=RED_L, line=RED, lw=1.2,
        anchor=TOP_A)
    fill_text(sl.shapes[-1], [
        t("When a check fails", s=10, b=True, c=RED, align=L, ls=0.95),
        t("The run stops before execution and returns the failing check, the "
          "field it applies to and a machine-readable error code — so the user "
          "is told what to fix, and a re-plan has something concrete to act on.",
          s=8.8, c=TEXT, align=L, space=4, ls=1.1)],
        anchor=TOP_A, align=L, margin=0.14)

    box(sl, M, 5.96, CW, 1.14, fill=NAVY, line=None, anchor=MID_A)
    fill_text(sl.shapes[-1], [
        t("Declared ≠ implemented", s=10.5, b=True, c=ORANGE, align=L, ls=0.95),
        t("Four of the eight registered capabilities have real implementations "
          "bound today. The other four are declared contracts with no binding — "
          "and the executor reports exactly that instead of returning a "
          "placeholder result. Being honest about what actually runs is part of "
          "the design, not a gap in it.",
          s=9.0, c=PALE, align=L, space=4, ls=1.1)],
        anchor=MID_A, align=L, margin=0.20)
    return sl


# ============================================================
# APPENDIX A2 — INTERFACE AND DEMO
# ============================================================
def slideA2():
    sl = slide("Appendix — Interface, demo and code", 8)

    label(sl, M, 0.84, 6.0, "Web interface")
    ph = box(sl, M, 1.16, 8.15, 5.51, fill=GRAY_L, line=GRAY_B, lw=1.5,
             rad=0.03)
    dash(ph)
    fill_text(ph, [
        t("[  INSERT WEB INTERFACE SCREENSHOT  ]", s=15, b=True, c=MUTED),
        t("query box  ·  uploaded scenes  ·  validation verdict  ·  "
          "workflow trace  ·  result map and statistics",
          s=9, c=MUTED, space=8)], anchor=MID_A, align=C)

    RX_ = 8.85
    RW_ = SW - M - RX_
    label(sl, RX_, 0.84, 4.0, "Sample outputs")
    for i, cap in enumerate(["[ NDVI RASTER OUTPUT ]",
                             "[ CHANGE HOTSPOT MAP ]"]):
        s = box(sl, RX_, 1.16 + i * (1.42 + 0.14), RW_, 1.42,
                [t(cap, s=9.5, b=True, c=MUTED)], fill=GRAY_L, line=GRAY_B,
                lw=1.2, rad=0.05)
        dash(s)

    label(sl, RX_, 4.30, 4.0, "Code and demo")
    box(sl, RX_, 4.62, RW_, 2.05, fill=NAVY, line=None, anchor=TOP_A)
    qr = box(sl, RX_ + 0.16, 4.78, 1.30, 1.30, [t("[ QR ]", s=9, b=True, c=MUTED)],
             fill=WHITE, line=None, rad=0.05)
    tb(sl, RX_ + 1.62, 4.80, RW_ - 1.78, 1.85, [
        t("GITHUB", s=8, b=True, c=ORANGE),
        t("github.com/VinayakGupta-1/\nSatQuery-AI", s=9, b=True, c=WHITE, ls=1.05),
        t("LIVE DEMO", s=8, b=True, c=ORANGE, space=8),
        t("[ INSERT WEB DEMO LINK ]", s=9, b=True, c=WHITE, ls=1.05),
    ], anchor=TOP_A, align=L)
    return sl


# ============================================================
# APPENDIX A3 — SCALING
# ============================================================
def slideA3():
    sl = slide("Appendix — Scaling beyond the current implementation", 9)

    label(sl, M, 0.84, 6.0, "What grows, stage by stage")
    phases = [
        ("NOW", "Deterministic core",
         "Ten-stage pipeline, registry, validator and four executing "
         "remote-sensing tools, covered by 326 passing tests.", GREEN, GREEN_L),
        ("INTEGRATING", "Reasoning layer",
         "An LLM proposes the interpretation, decomposition and parameters. "
         "The registry and validator keep their veto over everything it "
         "proposes.", AMBER, AMBER_L),
        ("NEXT", "Specialist model tier",
         "VQA, land-cover classification, object detection and SAR analysis "
         "bind to contracts that already exist in the registry.", BLUE, BLUE_L),
        ("THEN", "Data and scale tier",
         "Catalogue-backed imagery search, tiled and distributed execution, "
         "cached intermediate artefacts, multi-step composed workflows.",
         NAVY, BLUE_LL),
    ]
    pw = (CW - 3 * 0.24) / 4
    for i, (tag, head, body, c, f) in enumerate(phases):
        x = M + i * (pw + 0.24)
        sh = box(sl, x, 1.16, pw, 1.90, fill=f, line=c, lw=1.1, anchor=TOP_A)
        fill_text(sh, [
            t(tag, s=8.5, b=True, c=c, align=L),
            t(head, s=13.5, b=True, c=TEXT, align=L, space=3, ls=0.95),
            t(body, s=9.0, c=TEXT, align=L, space=6, ls=1.12)],
            anchor=TOP_A, align=L, margin=0.16)
        if i < 3:
            chain_arrow(sl, x + pw + 0.02, 2.11, 0.20)

    label(sl, M, 3.32, 8.0, "What does not change as it grows")
    fixed = [
        ("The validation gate stays in the path",
         "Every new capability is validated against its own declared contract "
         "by the same deterministic code. Adding models never widens the "
         "trust boundary."),
        ("The registry stays the only door",
         "A capability that is not declared cannot be selected and cannot be "
         "executed, however the reasoning layer is prompted."),
        ("The controller stays untouched",
         "Extending the system is a registry entry plus a bound "
         "implementation. No orchestration rewrite, no API change."),
    ]
    fw = (CW - 2 * 0.24) / 3
    for i, (h, b) in enumerate(fixed):
        card(sl, M + i * (fw + 0.24), 3.64, fw, 1.48, h, b,
             accent=[RED, BLUE, NAVY][i], fill=WHITE, head_s=11, body_s=9.0)

    box(sl, M, 5.55, CW, 1.42, fill=NAVY, line=None)
    fill_text(sl.shapes[-1], [
        t("SatQuery AI is not a chatbot over satellite imagery. It is a "
          "reasoning and orchestration layer that turns natural-language "
          "geospatial intent into validated, executable remote-sensing "
          "workflows.", s=14, b=True, c=WHITE, ls=1.1)],
        anchor=MID_A, align=C, margin=0.5)
    return sl


NOTES = [
    # 1 — Title
    "We are presenting SatQuery AI for problem statement SIH26167. In one "
    "line: SatQuery turns a plain-language geospatial question into a "
    "validated, executable remote-sensing workflow. The important word is "
    "validated. Through this deck we will show you exactly where AI reasoning "
    "stops and deterministic engineering takes over, because that boundary is "
    "the core of our design.",

    # 2 — Proposed Solution
    "Take this question. A person asks it in one sentence, but answering it "
    "requires spatial reasoning, temporal reasoning, band selection, index "
    "computation, co-registration, differencing and statistical thresholding. "
    "SatQuery derives all seven stages from the sentence. Look closely at "
    "stages four and five. A capability is chosen from a registry, and only "
    "then does deterministic code check whether the imagery can actually "
    "support it. The model proposes; the system verifies.",

    # 3 — Technical Approach
    "This is the architecture. Orange is where the language model reasons: "
    "understanding, decomposition, requirement inference. Everything below it "
    "is deterministic. The registry is the only door — the agent cannot call "
    "a function that is not declared there, and those same declarations supply "
    "the constraints the validation gate enforces. The gate is a hard "
    "boundary; no model opinion crosses it. Execution is a separate "
    "specialist layer. And when a run is rejected or returns low confidence, "
    "the system re-plans rather than failing silently.",

    # 4 — Feasibility and Viability
    "This is what already runs, not what we intend to build. Three hundred "
    "and twenty-six automated tests pass. Eight capabilities are declared and "
    "four execute on real rasters today, including bi-temporal change "
    "detection. We ship two interchangeable raster backends and the tests "
    "prove they agree, so a GDAL-free deployment is possible. We are explicit "
    "about status: the reasoning layer is being integrated, and four "
    "specialists are declared but not yet bound. On risk — our containment is "
    "not a promise that the model behaves. It is that the registry and the "
    "validator hold the veto regardless of what the model proposes.",

    # 5 — Impact and Benefits
    "Today, answering a geospatial question needs an expert, manual "
    "preprocessing and manual tool selection, and the results arrive "
    "fragmented. SatQuery collapses that into a question. That matters most "
    "where expertise is scarce — a district agriculture office, or a disaster "
    "cell in the first hours of a flood. And because every answer carries its "
    "provenance, the output is auditable and reproducible rather than a "
    "one-off image someone produced once.",

    # 6 — Research and References
    "Each design choice traces to a body of work rather than to a trend. "
    "Agentic planning gives us decomposition. Schema-constrained tool calling "
    "is why we built a registry instead of allowing free-form function "
    "access. The most important is the fourth: language models are strong "
    "proposers and unreliable verifiers. That finding is precisely why our "
    "validation gate is code, and not a prompt.",

    # A1 — Registry and gate
    "If you want the mechanism: this is a real registry entry. It declares "
    "modality, band requirements, image count, temporal pairing and a "
    "parameter schema. Selection reads it and the validator reads it. On the "
    "right are the five checks that run before a single pixel is touched. "
    "Note the last one — a misaligned pair would produce a confident and "
    "completely wrong change map, so we refuse rather than silently "
    "resampling the user’s imagery. And we state plainly that four "
    "capabilities are declared without implementations.",

    # A2 — Interface and demo
    "This is the web interface and the repository. We are happy to run a live "
    "query on real imagery now if you would like to see the full trace.",

    # A3 — Scaling
    "On scale: the reasoning tier is being integrated now, the specialist "
    "models bind to contracts that already exist in the registry, and the "
    "data tier follows. The point of this slide is the bottom row. None of "
    "that growth widens the trust boundary. Every new capability is validated "
    "by the same deterministic code against its own declared contract. "
    "Extending SatQuery is a registry entry and a binding — never a rewrite.",
]

for fn, note in zip((slide1, slide2, slide3, slide4, slide5, slide6,
                     slideA1, slideA2, slideA3), NOTES):
    sl = fn()
    sl.notes_slide.notes_text_frame.text = note

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "SatQuery_AI_Presentation_Deck.pptx")
prs.save(out)
print("Wrote", out)
print("Slides:", len(prs.slides.__iter__.__self__._sldIdLst))
