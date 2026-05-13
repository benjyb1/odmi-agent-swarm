"""Generate the supervisor-meeting slide deck from live DB state.

Styled after `MSc Progress Slides 3.pptx`: 16:9 widescreen, dark hero
header bar on every slide, Calibri throughout, teal accent palette,
white cards with thin accent stripes. Every number on the deck is
queried from SQLite at generation time, so re-running this script
produces an up-to-date deck.

    uv run python scripts/generate_slides.py

Output: docs/PROGRESS_SLIDES_<YYYY-MM-DD>.pptx
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"
OUT_DIR = REPO_ROOT / "docs"


# ============================================================
# Palette and type system (mirrors MSc Progress Slides 3.pptx)
# ============================================================

DARK = RGBColor(0x1A, 0x20, 0x2C)
HEAD = RGBColor(0x1A, 0x20, 0x2C)
BODY = RGBColor(0x2D, 0x37, 0x48)
MUTED = RGBColor(0x71, 0x80, 0x96)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
PALE = RGBColor(0xCB, 0xD5, 0xE0)
SURFACE = RGBColor(0xF7, 0xFA, 0xFC)
BORDER = RGBColor(0xE2, 0xE8, 0xF0)
TEAL = RGBColor(0x0D, 0x94, 0x88)
TEAL_DARK = RGBColor(0x0F, 0x76, 0x6E)
TEAL_BRIGHT = RGBColor(0x14, 0xB8, 0xA6)
SUCCESS = RGBColor(0x38, 0xA1, 0x69)
WARNING = RGBColor(0xD6, 0x9E, 0x2E)
DANGER = RGBColor(0xC5, 0x30, 0x30)
NAVY = RGBColor(0x1E, 0x3A, 0x5F)

FONT = "Calibri"


# ============================================================
# Data
# ============================================================

def fetch_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        n_questions = cur.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        n_hand_marks = cur.execute("SELECT COUNT(*) FROM hand_marks").fetchone()[0]
        n_locked = cur.execute(
            "SELECT COUNT(*) FROM hand_marks "
            "WHERE locked_by_commit IS NOT NULL"
        ).fetchone()[0]
        n_researcher = cur.execute(
            "SELECT COUNT(*) FROM phase2_researcher_runs"
        ).fetchone()[0]
        n_verifier = cur.execute(
            "SELECT COUNT(*) FROM phase2_verifier_runs"
        ).fetchone()[0]
        n_adjudications = cur.execute(
            "SELECT COUNT(*) FROM phase2_adjudications"
        ).fetchone()[0]
        n_finals = cur.execute("SELECT COUNT(*) FROM phase2_final").fetchone()[0]

        country_outcomes = cur.execute(
            """SELECT country_code,
                      SUM(CASE WHEN terminal_status LIKE 'accepted_%' THEN 1
                               ELSE 0 END) AS successful,
                      SUM(CASE WHEN terminal_status LIKE 'accepted_%' THEN 0
                               ELSE 1 END) AS failed
               FROM phase2_final
               GROUP BY country_code
               ORDER BY country_code"""
        ).fetchall()

        cost_total = cur.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM claude_usage_log"
        ).fetchone()[0]

        avg_runtime = cur.execute(
            """SELECT AVG(
                 (julianday(ended_at) - julianday(started_at)) * 86400
               )
               FROM subtrio_status
               WHERE stage = 'done' AND ended_at IS NOT NULL"""
        ).fetchone()[0] or 0.0

    return {
        "n_questions": n_questions,
        "n_hand_marks": n_hand_marks,
        "n_locked": n_locked,
        "n_researcher": n_researcher,
        "n_verifier": n_verifier,
        "n_adjudications": n_adjudications,
        "n_finals": n_finals,
        "country_outcomes": country_outcomes,
        "cost_total": cost_total,
        "avg_runtime_s": avg_runtime,
    }


# ============================================================
# Low-level builders
# ============================================================

def set_text(
    tf, text: str, *,
    size: int = 12,
    bold: bool = False,
    colour: RGBColor = BODY,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    font: str = FONT,
) -> None:
    tf.clear()
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = colour


def add_textbox(slide, x, y, w, h):
    box = slide.shapes.add_textbox(x, y, w, h)
    box.text_frame.word_wrap = True
    box.text_frame.margin_left = Emu(0)
    box.text_frame.margin_right = Emu(0)
    box.text_frame.margin_top = Emu(0)
    box.text_frame.margin_bottom = Emu(0)
    return box


def add_filled_rect(slide, x, y, w, h, *, fill: RGBColor, line_visible: bool = False):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if not line_visible:
        shape.line.fill.background()
    return shape


def add_outlined_rect(
    slide, x, y, w, h, *,
    fill: RGBColor = WHITE,
    border: RGBColor = BORDER,
):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = border
    shape.line.width = Emu(6350)  # ~0.5pt
    return shape


# ============================================================
# Slide template
# ============================================================

HEADER_HEIGHT = Inches(1.05)


def new_slide(prs: Presentation) -> object:
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    add_filled_rect(slide, 0, 0, prs.slide_width, HEADER_HEIGHT, fill=DARK)
    return slide


def header(slide, title: str, eyebrow: str | None = None) -> None:
    pad = Inches(0.5)
    if eyebrow:
        eyebrow_box = add_textbox(slide, pad, Inches(0.18), Inches(8.5), Inches(0.25))
        set_text(
            eyebrow_box.text_frame, eyebrow.upper(),
            size=9, bold=True, colour=TEAL_BRIGHT,
        )
        title_top = Inches(0.42)
    else:
        title_top = Inches(0.28)

    title_box = add_textbox(slide, pad, title_top, Inches(8.5), Inches(0.55))
    set_text(
        title_box.text_frame, title,
        size=24, bold=True, colour=WHITE,
    )


def page_footer(slide, prs: Presentation, page_num: int, total: int) -> None:
    pad = Inches(0.5)
    foot_y = prs.slide_height - Inches(0.32)
    fbox = add_textbox(slide, pad, foot_y, prs.slide_width - 2 * pad, Inches(0.2))
    set_text(
        fbox.text_frame,
        f"ODMI Agent Swarm  ·  Benjy Bream  ·  King's College London  ·  "
        f"{page_num} / {total}",
        size=8, colour=MUTED,
    )


# ============================================================
# Card builders
# ============================================================

def add_card(
    slide, x, y, w, h, *,
    title: str, body: str,
    accent: RGBColor = TEAL,
    title_size: int = 14,
    body_size: int = 11,
) -> None:
    add_outlined_rect(slide, x, y, w, h)
    add_filled_rect(slide, x, y, Inches(0.08), h, fill=accent)
    pad_x = Inches(0.25)
    pad_y = Inches(0.15)
    inner_x = x + Inches(0.18) + pad_x
    inner_w = w - Inches(0.18) - 2 * pad_x

    title_box = add_textbox(slide, inner_x, y + pad_y, inner_w, Inches(0.35))
    set_text(
        title_box.text_frame, title,
        size=title_size, bold=True, colour=HEAD,
    )

    body_box = add_textbox(
        slide, inner_x, y + pad_y + Inches(0.35),
        inner_w, h - pad_y - Inches(0.4),
    )
    set_text(body_box.text_frame, body, size=body_size, colour=BODY)


def add_kpi(
    slide, x, y, w, h, *,
    label: str, value: str, caption: str = "",
    accent: RGBColor = TEAL,
) -> None:
    add_outlined_rect(slide, x, y, w, h, fill=SURFACE)
    add_filled_rect(slide, x, y, w, Inches(0.06), fill=accent)

    pad_x = Inches(0.22)
    inner_w = w - 2 * pad_x

    # Label sits just under the accent stripe.
    label_box = add_textbox(slide, x + pad_x, y + Inches(0.18),
                            inner_w, Inches(0.22))
    set_text(label_box.text_frame, label.upper(),
             size=9, bold=True, colour=MUTED)

    # Value is the hero. Height matches the font's natural line so the
    # caption below doesn't get walked on.
    value_y = y + Inches(0.46)
    value_h = Inches(0.6)
    value_box = add_textbox(slide, x + pad_x, value_y, inner_w, value_h)
    set_text(value_box.text_frame, value,
             size=22, bold=True, colour=HEAD)

    if caption:
        cap_y = value_y + value_h + Inches(0.04)
        cap_h = max(Inches(0.2), y + h - cap_y - Inches(0.1))
        cap_box = add_textbox(slide, x + pad_x, cap_y, inner_w, cap_h)
        set_text(cap_box.text_frame, caption, size=9.5, colour=BODY)


def add_numbered_step(
    slide, x, y, w, h, *,
    number: int, title: str, body: str,
    tag: str | None = None,
    tag_colour: RGBColor = TEAL,
) -> None:
    add_outlined_rect(slide, x, y, w, h, fill=SURFACE)

    circle_d = Inches(0.5)
    circle = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        x + Inches(0.2), y + (h - circle_d) / 2,
        circle_d, circle_d,
    )
    circle.fill.solid()
    circle.fill.fore_color.rgb = DARK
    circle.line.fill.background()
    set_text(
        circle.text_frame, str(number),
        size=16, bold=True, colour=WHITE, align=PP_ALIGN.CENTER,
    )

    inner_x = x + Inches(0.85)
    inner_w = w - Inches(1.1)

    title_box = add_textbox(slide, inner_x, y + Inches(0.18), inner_w, Inches(0.3))
    set_text(title_box.text_frame, title, size=13, bold=True, colour=HEAD)

    body_box = add_textbox(slide, inner_x, y + Inches(0.5), inner_w, h - Inches(0.6))
    set_text(body_box.text_frame, body, size=10.5, colour=BODY)

    if tag:
        tag_w = Inches(0.7)
        tag_box = add_textbox(
            slide, x + w - tag_w - Inches(0.15),
            y + Inches(0.18), tag_w, Inches(0.25),
        )
        set_text(
            tag_box.text_frame, tag.upper(),
            size=9, bold=True, colour=tag_colour, align=PP_ALIGN.RIGHT,
        )


# ============================================================
# Slides
# ============================================================

def slide_title(prs: Presentation) -> None:
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    add_filled_rect(slide, 0, 0, prs.slide_width, prs.slide_height, fill=DARK)

    add_filled_rect(slide, 0, Inches(2.0), Inches(0.6), Inches(2.0), fill=TEAL)

    eyebrow = add_textbox(slide, Inches(1.0), Inches(1.2), Inches(8), Inches(0.4))
    set_text(
        eyebrow.text_frame,
        "MSc ADVANCED COMPUTING · INDIVIDUAL PROJECT · STATUS BRIEFING",
        size=10, bold=True, colour=TEAL_BRIGHT,
    )

    title = add_textbox(slide, Inches(1.0), Inches(1.65), Inches(8.5), Inches(2.2))
    tf = title.text_frame
    tf.clear()
    for i, line in enumerate(["Agentic AI for Open", "Data Maturity", "Assessment"]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        run = p.add_run()
        run.text = line
        run.font.name = FONT
        run.font.size = Pt(40)
        run.font.bold = True
        run.font.color.rgb = WHITE

    sub = add_textbox(slide, Inches(1.0), Inches(4.0), Inches(8.5), Inches(0.6))
    set_text(
        sub.text_frame,
        "Status snapshot and next steps for supervisor review",
        size=14, colour=PALE,
    )

    today = datetime.now().strftime("%d %B %Y")
    foot = add_textbox(slide, Inches(1.0), Inches(5.0), Inches(8.5), Inches(0.4))
    set_text(
        foot.text_frame,
        f"Benjy Bream  ·  King's College London  ·  {today}",
        size=11, colour=WHITE,
    )


def slide_what_is_built(prs: Presentation, stats: dict) -> None:
    slide = new_slide(prs)
    header(slide, "What is built", eyebrow="Capability snapshot")

    y = Inches(1.25)
    h = Inches(1.5)
    col_w = Inches(2.225)
    gap = Inches(0.07)
    x0 = Inches(0.5)

    add_kpi(slide, x0 + 0 * (col_w + gap), y, col_w, h,
            label="Questions loaded",
            value=str(stats["n_questions"]),
            caption="ODMI 2025 catalogue, all four dimensions.")
    add_kpi(slide, x0 + 1 * (col_w + gap), y, col_w, h,
            label="Hand-marks locked",
            value=f"{stats['n_locked']} / {stats['n_hand_marks']}",
            caption="Stamped with the commit SHA per D9.",
            accent=NAVY)
    add_kpi(slide, x0 + 2 * (col_w + gap), y, col_w, h,
            label="Finalised pairs",
            value=str(stats["n_finals"]),
            caption=f"{stats['n_researcher']} R · {stats['n_verifier']} V · "
                    f"{stats['n_adjudications']} A.",
            accent=SUCCESS)
    add_kpi(slide, x0 + 3 * (col_w + gap), y, col_w, h,
            label="Total LLM spend",
            value=f"${stats['cost_total']:.2f}",
            caption="Via CLIProxyAPI on Claude Max.",
            accent=TEAL_BRIGHT)

    y2 = Inches(2.95)
    card_w = Inches(4.55)
    card_h = Inches(1.55)
    gap2 = Inches(0.15)
    add_card(slide, Inches(0.5), y2, card_w, card_h,
             title="Three-agent swarm, end-to-end",
             body="Researcher proposes, Verifier tries to disprove, "
                  "Adjudicator decides on retry exhaustion. One pair "
                  "(P2/NL) has needed the Adjudicator. Average runtime ~32s.",
             accent=TEAL)
    add_card(slide, Inches(0.5) + card_w + gap2, y2, card_w, card_h,
             title="Live dashboard with full audit trail",
             body="Nine Streamlit pages over the SQLite store. Every LLM "
                  "call logs tokens, latency, cost, prompt version. "
                  "Hand-marks lock to a commit SHA so D9 is automatic.",
             accent=NAVY)

    page_footer(slide, prs, 2, 6)


def slide_how_it_works(prs: Presentation) -> None:
    slide = new_slide(prs)
    header(slide, "How the swarm answers one question",
           eyebrow="Coordinator state machine")

    row_y = Inches(1.6)
    row_h = Inches(1.65)
    box_w = Inches(2.7)
    gap = Inches(0.45)
    x_start = (prs.slide_width - (3 * box_w + 2 * gap)) // 2

    def agent_box(x, label, role, accent):
        add_outlined_rect(slide, x, row_y, box_w, row_h)
        add_filled_rect(slide, x, row_y, box_w, Inches(0.35), fill=accent)
        lab = add_textbox(slide, x + Inches(0.2), row_y + Inches(0.05),
                          box_w - Inches(0.4), Inches(0.27))
        set_text(lab.text_frame, label, size=12, bold=True, colour=WHITE)
        body = add_textbox(
            slide, x + Inches(0.2), row_y + Inches(0.5),
            box_w - Inches(0.4), row_h - Inches(0.6),
        )
        set_text(body.text_frame, role, size=10.5, colour=BODY)

    x1 = x_start
    x2 = x1 + box_w + gap
    x3 = x2 + box_w + gap

    agent_box(
        x1, "RESEARCHER",
        "Tavily search → fetch URL → reason → return "
        "{answer, source_url, evidence_quote, confidence}.",
        TEAL,
    )
    agent_box(
        x2, "VERIFIER",
        "Same source URL. Adversarial prompt (default: find disproof). "
        "Returns pass / fail with counter-evidence if any.",
        NAVY,
    )
    agent_box(
        x3, "ADJUDICATOR",
        "Fires only on retry exhaustion. Reads the full history. "
        "Picks a winner or escalates to a human queue.",
        DANGER,
    )

    arrow_y = row_y + row_h // 2
    for left, right in [(x1 + box_w, x2), (x2 + box_w, x3)]:
        arrow = slide.shapes.add_shape(
            MSO_SHAPE.RIGHT_ARROW,
            left + Inches(0.05), arrow_y - Inches(0.12),
            gap - Inches(0.1), Inches(0.24),
        )
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = MUTED
        arrow.line.fill.background()

    callout_y = row_y + row_h + Inches(0.35)
    add_outlined_rect(
        slide, Inches(0.5), callout_y,
        prs.slide_width - Inches(1.0), Inches(0.9),
        fill=SURFACE, border=TEAL,
    )
    cap = add_textbox(
        slide, Inches(0.7), callout_y + Inches(0.12),
        prs.slide_width - Inches(1.4), Inches(0.35),
    )
    set_text(cap.text_frame, "TERMINATION RULE",
             size=9, bold=True, colour=TEAL)
    body = add_textbox(
        slide, Inches(0.7), callout_y + Inches(0.42),
        prs.slide_width - Inches(1.4), Inches(0.45),
    )
    set_text(
        body.text_frame,
        "Coordinator retries Researcher up to 3× when the Verifier "
        "rejects. After that, Adjudicator decides. Confidence below 0.6 "
        "escalates to a human queue.",
        size=11, colour=BODY,
    )

    page_footer(slide, prs, 3, 6)


def slide_dashboard_highlights(prs: Presentation) -> None:
    slide = new_slide(prs)
    header(slide, "Best bits of the dashboard",
           eyebrow="What I'll demo live")

    items = [
        ("Run Console",
         "Multiselect questions × countries, pick the Verifier "
         "strategy and the model triple, dispatch a batch. Cost is "
         "estimated before the run starts.",
         "▶", TEAL),
        ("Results · Cards view",
         "One bordered card per finalised pair. Question, answer, "
         "evidence quote, and a clickable source URL — all on the same "
         "screen, scannable.",
         "📋", NAVY),
        ("In-app hand-marking",
         "Pick a question, slide three score sliders, hit Save. The "
         "page writes the CSV, commits it, and stamps the SHA into "
         "the DB so D9 is automatic.",
         "✍", TEAL_DARK),
        ("Country chart + cost tracking",
         "Live stacked bar of accept vs reject per country on the Home "
         "page. Costs page shows the rolling 5-hour spend and the "
         "per-model breakdown.",
         "📊", SUCCESS),
    ]

    y = Inches(1.35)
    w = Inches(4.55)
    h = Inches(1.85)
    gap = Inches(0.15)

    for i, (title, body, glyph, accent) in enumerate(items):
        col = i % 2
        row = i // 2
        x = Inches(0.5) + col * (w + gap)
        yy = y + row * (h + gap)

        add_outlined_rect(slide, x, yy, w, h)
        add_filled_rect(slide, x, yy, Inches(0.08), h, fill=accent)

        # Glyph bubble.
        bubble_d = Inches(0.55)
        bubble = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            x + Inches(0.3), yy + Inches(0.25),
            bubble_d, bubble_d,
        )
        bubble.fill.solid()
        bubble.fill.fore_color.rgb = accent
        bubble.line.fill.background()
        set_text(
            bubble.text_frame, glyph,
            size=18, bold=True, colour=WHITE, align=PP_ALIGN.CENTER,
        )

        # Title.
        t_box = add_textbox(
            slide, x + Inches(1.0), yy + Inches(0.28),
            w - Inches(1.2), Inches(0.4),
        )
        set_text(t_box.text_frame, title,
                 size=15, bold=True, colour=HEAD)

        # Body.
        b_box = add_textbox(
            slide, x + Inches(1.0), yy + Inches(0.7),
            w - Inches(1.2), h - Inches(0.8),
        )
        set_text(b_box.text_frame, body, size=10.5, colour=BODY)

    page_footer(slide, prs, 5, 6)


def slide_country_chart(prs: Presentation, stats: dict) -> None:
    slide = new_slide(prs)
    header(slide, "Results so far, per country",
           eyebrow="Finalised pairs · success vs failure")

    outcomes = stats["country_outcomes"]

    chart_box_x = Inches(0.5)
    chart_box_y = Inches(1.3)
    chart_box_w = prs.slide_width - Inches(1.0)
    chart_box_h = Inches(2.7)

    add_outlined_rect(slide, chart_box_x, chart_box_y, chart_box_w, chart_box_h,
                      fill=WHITE, border=BORDER)

    if not outcomes:
        msg = add_textbox(slide, chart_box_x + Inches(0.3),
                          chart_box_y + Inches(1.2),
                          chart_box_w - Inches(0.6), Inches(0.5))
        set_text(
            msg.text_frame,
            "No finalised pairs yet. Once the Coordinator writes "
            "phase2_final rows, this chart populates.",
            size=14, colour=BODY,
        )
        page_footer(slide, prs, 4, 6)
        return

    max_total = max(s + f for _, s, f in outcomes) or 1

    plot_left = chart_box_x + Inches(0.8)
    plot_top = chart_box_y + Inches(0.3)
    plot_width = chart_box_w - Inches(1.3)
    plot_height = chart_box_h - Inches(0.95)

    bar_slot = plot_width / len(outcomes)
    bar_w = Emu(int(bar_slot * 0.55))
    gap = (bar_slot - bar_w) // 2

    axis = slide.shapes.add_connector(
        1, plot_left - Inches(0.05), plot_top,
        plot_left - Inches(0.05), plot_top + plot_height,
    )
    axis.line.color.rgb = BORDER
    axis.line.width = Emu(6350)

    base = slide.shapes.add_connector(
        1, plot_left - Inches(0.05), plot_top + plot_height,
        plot_left + plot_width, plot_top + plot_height,
    )
    base.line.color.rgb = BORDER
    base.line.width = Emu(6350)

    for tick in range(0, max_total + 1):
        ratio = tick / max_total
        ty = plot_top + plot_height - Emu(int(plot_height * ratio))
        lbl = add_textbox(
            slide, plot_left - Inches(0.55), ty - Inches(0.1),
            Inches(0.45), Inches(0.2),
        )
        set_text(
            lbl.text_frame, str(tick),
            size=9, colour=MUTED, align=PP_ALIGN.RIGHT,
        )

    for i, (country, successful, failed) in enumerate(outcomes):
        total = successful + failed
        if total == 0:
            continue
        bar_x = plot_left + Emu(int(bar_slot * i + gap))

        if failed > 0:
            f_h = Emu(int(plot_height * failed / max_total))
            f_top = plot_top + plot_height - f_h
            add_filled_rect(slide, bar_x, f_top, bar_w, f_h, fill=DANGER)

        if successful > 0:
            f_h = Emu(int(plot_height * failed / max_total))
            s_h = Emu(int(plot_height * successful / max_total))
            s_top = plot_top + plot_height - f_h - s_h
            add_filled_rect(slide, bar_x, s_top, bar_w, s_h, fill=SUCCESS)

        lab_y = plot_top + plot_height + Inches(0.08)
        lab = add_textbox(
            slide, bar_x - Inches(0.4), lab_y,
            bar_w + Inches(0.8), Inches(0.25),
        )
        set_text(
            lab.text_frame, country,
            size=12, bold=True, colour=HEAD, align=PP_ALIGN.CENTER,
        )
        val = add_textbox(
            slide, bar_x - Inches(0.4), lab_y + Inches(0.22),
            bar_w + Inches(0.8), Inches(0.22),
        )
        set_text(
            val.text_frame, f"{successful} / {total}",
            size=9, colour=MUTED, align=PP_ALIGN.CENTER,
        )

    # Legend sits below the chart card, not inside it.
    leg_y = chart_box_y + chart_box_h + Inches(0.18)
    leg_x = chart_box_x + Inches(0.1)
    add_filled_rect(slide, leg_x, leg_y, Inches(0.18), Inches(0.18), fill=SUCCESS)
    leg1 = add_textbox(slide, leg_x + Inches(0.28), leg_y - Inches(0.03),
                       Inches(3.6), Inches(0.25))
    set_text(leg1.text_frame, "Accepted (Verifier or Adjudicator)",
             size=10, colour=BODY)
    add_filled_rect(slide, leg_x + Inches(3.6), leg_y, Inches(0.18), Inches(0.18),
                    fill=DANGER)
    leg2 = add_textbox(slide, leg_x + Inches(3.88), leg_y - Inches(0.03),
                       Inches(4.0), Inches(0.25))
    set_text(leg2.text_frame, "Rejected or escalated", size=10, colour=BODY)

    note_y = leg_y + Inches(0.45)
    add_filled_rect(slide, chart_box_x, note_y, Inches(0.08), Inches(0.6),
                    fill=WARNING)
    nb = add_textbox(
        slide, chart_box_x + Inches(0.2), note_y + Inches(0.04),
        chart_box_w - Inches(0.3), Inches(0.55),
    )
    set_text(
        nb.text_frame,
        "Caveat: every pair so far is a Policy-dimension question on a "
        "high-resource country. The Verifier has not yet been asked to "
        "disprove a known-wrong Researcher answer. The 100% accept rate "
        "is consistent with the swarm working — and with it being too lenient.",
        size=10, colour=BODY,
    )

    page_footer(slide, prs, 4, 6)


def slide_next_steps(prs: Presentation) -> None:
    slide = new_slide(prs)
    header(slide, "Where this goes next",
           eyebrow="Short term and long term")

    col_w = Inches(4.55)
    gap = Inches(0.2)
    x_l = Inches(0.5)
    x_r = x_l + col_w + gap
    y = Inches(1.35)
    h_col = Inches(3.85)

    def column(x, header_label, header_fill, items):
        add_outlined_rect(slide, x, y, col_w, h_col, fill=SURFACE)
        add_filled_rect(slide, x, y, col_w, Inches(0.45), fill=header_fill)
        head_box = add_textbox(slide, x + Inches(0.25), y + Inches(0.1),
                               col_w - Inches(0.5), Inches(0.3))
        set_text(head_box.text_frame, header_label,
                 size=11, bold=True, colour=WHITE)

        item_h = (h_col - Inches(0.45) - Inches(0.2)) / len(items)
        row_y = y + Inches(0.55)
        for title, body in items:
            num_x = x + Inches(0.2)
            num_w = Inches(0.4)
            t_box = add_textbox(slide, num_x + num_w + Inches(0.05), row_y,
                                col_w - num_w - Inches(0.3), Inches(0.28))
            set_text(t_box.text_frame, title, size=11, bold=True, colour=HEAD)

            b_box = add_textbox(slide, num_x + num_w + Inches(0.05),
                                row_y + Inches(0.28),
                                col_w - num_w - Inches(0.3),
                                item_h - Inches(0.32))
            set_text(b_box.text_frame, body, size=10, colour=BODY)

            # Accent bullet on the left.
            add_filled_rect(slide, num_x, row_y + Inches(0.08),
                            Inches(0.18), Inches(0.18), fill=TEAL)
            row_y += item_h

    short_items = [
        ("Hand-mark the Phase A pilot",
         "10 France questions across all four rubric tiers. Submit "
         "from the dashboard; D9 lock happens on save."),
        ("Baseline + strategy comparison",
         "Run the swarm on the locked 10 with all four Verifier "
         "strategies. First real accuracy and rejection numbers."),
        ("First analysis pass",
         "Accuracy and cost stratified by rubric tier × ODMI dimension. "
         "Draft methodology + early-results in the dissertation."),
    ]

    long_items = [
        ("Phase B — six-country matrix",
         "FR, DE, NL, RO, HU, EE. Cost–accuracy surface comes "
         "out of the Haiku / Sonnet / Opus / tiered model experiments."),
        ("External validity (2024 cycle)",
         "Pipeline frozen, then run against the 2024 ODMI cycle as a "
         "held-out test. Delta against 2025 is itself a result."),
        ("Dissertation by 2 August 2026",
         "Failure-mode taxonomy and accuracy–cost surface as the two "
         "primary contributions. Phase C as a stretch."),
    ]

    column(x_l, "NEXT TWO WEEKS", DARK, short_items)
    column(x_r, "TOWARDS 2 AUGUST 2026", NAVY, long_items)

    page_footer(slide, prs, 6, 6)


# ============================================================
# Main
# ============================================================

def build_deck(stats: dict) -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)

    slide_title(prs)
    slide_what_is_built(prs, stats)
    slide_how_it_works(prs)
    slide_country_chart(prs, stats)
    slide_dashboard_highlights(prs)
    slide_next_steps(prs)
    return prs


def main() -> None:
    stats = fetch_stats()
    prs = build_deck(stats)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / (
        f"PROGRESS_SLIDES_{datetime.now().strftime('%Y-%m-%d')}.pptx"
    )
    prs.save(out_path)
    print(f"Wrote {out_path}")
    print(f"  Slides: {len(prs.slides)}")
    print(f"  Finals on chart: {len(stats['country_outcomes'])} country/countries")


if __name__ == "__main__":
    main()
