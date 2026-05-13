"""Generate the supervisor-meeting slide deck from live DB state.

Reads SQLite for current counts, costs, and per-country outcomes, then
writes a .pptx beside `docs/PROGRESS_SLIDES.md`. Re-runnable. The deck
is a status snapshot, not a polished talk, so headlines stay terse and
every number is read from the DB at generation time.

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
from pptx.util import Emu, Inches, Pt

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "odmi.db"
OUT_DIR = REPO_ROOT / "docs"

NAVY = RGBColor(0x14, 0x2B, 0x57)
GREEN = RGBColor(0x2C, 0xA0, 0x2C)
RED = RGBColor(0xD6, 0x27, 0x28)
GREY = RGBColor(0x55, 0x55, 0x55)


# ============================================================
# Data layer
# ============================================================

def fetch_stats() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        n_questions = cur.execute(
            "SELECT COUNT(*) FROM questions"
        ).fetchone()[0]
        n_hand_marks = cur.execute(
            "SELECT COUNT(*) FROM hand_marks"
        ).fetchone()[0]
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
        n_finals = cur.execute(
            "SELECT COUNT(*) FROM phase2_final"
        ).fetchone()[0]

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
            "SELECT COALESCE(SUM(estimated_cost_usd), 0) "
            "FROM claude_usage_log"
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
# Slide helpers
# ============================================================

def add_title_slide(prs: Presentation, title: str, subtitle: str) -> None:
    layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title
    if len(slide.placeholders) > 1:
        slide.placeholders[1].text = subtitle


def add_text_slide(prs: Presentation, title: str, bullets: list[str]) -> None:
    layout = prs.slide_layouts[1]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title

    body = slide.placeholders[1].text_frame
    body.clear()
    for i, bullet in enumerate(bullets):
        para = body.paragraphs[0] if i == 0 else body.add_paragraph()
        para.text = bullet
        para.font.size = Pt(18)


def add_two_col_slide(
    prs: Presentation, title: str,
    left_header: str, left_items: list[str],
    right_header: str, right_items: list[str],
) -> None:
    layout = prs.slide_layouts[5]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title

    width = Inches(4.4)
    height = Inches(5.2)
    top = Inches(1.4)

    for col_idx, (header, items, left) in enumerate([
        (left_header, left_items, Inches(0.5)),
        (right_header, right_items, Inches(5.1)),
    ]):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        head = tf.paragraphs[0]
        head.text = header
        head.font.bold = True
        head.font.size = Pt(20)
        head.font.color.rgb = NAVY
        for item in items:
            para = tf.add_paragraph()
            para.text = f"• {item}"
            para.font.size = Pt(15)
            para.space_before = Pt(6)


def add_country_chart_slide(
    prs: Presentation, title: str, country_outcomes: list[tuple]
) -> None:
    layout = prs.slide_layouts[5]
    slide = prs.slides.add_slide(layout)
    slide.shapes.title.text = title

    if not country_outcomes:
        box = slide.shapes.add_textbox(
            Inches(1), Inches(2), Inches(8), Inches(1)
        )
        box.text_frame.text = "No finalised pairs in the DB yet."
        return

    chart_left = Inches(1.0)
    chart_top = Inches(1.6)
    chart_width = Inches(8.0)
    chart_height = Inches(4.5)

    max_total = max(s + f for _, s, f in country_outcomes) or 1
    bar_slot = chart_width / len(country_outcomes)
    bar_width = Emu(int(bar_slot * 0.6))
    gap = (bar_slot - bar_width) / 2

    for i, (country, successful, failed) in enumerate(country_outcomes):
        total = successful + failed
        if total == 0:
            continue

        scale = chart_height / max_total
        s_height = Emu(int(scale * successful))
        f_height = Emu(int(scale * failed))

        bar_left = chart_left + Emu(int(bar_slot * i + gap))

        if failed > 0:
            fail_top = chart_top + chart_height - f_height
            shape = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                bar_left, fail_top, bar_width, f_height,
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = RED
            shape.line.fill.background()

        if successful > 0:
            succ_top = chart_top + chart_height - f_height - s_height
            shape = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                bar_left, succ_top, bar_width, s_height,
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = GREEN
            shape.line.fill.background()

        label_top = chart_top + chart_height + Inches(0.05)
        label = slide.shapes.add_textbox(
            bar_left - Inches(0.2), label_top,
            bar_width + Inches(0.4), Inches(0.4),
        )
        para = label.text_frame.paragraphs[0]
        para.text = f"{country} ({total})"
        para.font.size = Pt(14)
        para.font.bold = True

    legend = slide.shapes.add_textbox(
        Inches(1.0), Inches(6.4), Inches(8.0), Inches(0.3)
    )
    para = legend.text_frame.paragraphs[0]
    run1 = para.add_run()
    run1.text = "■ "
    run1.font.color.rgb = GREEN
    run1.font.size = Pt(13)
    run2 = para.add_run()
    run2.text = "Accepted by Verifier or Adjudicator    "
    run2.font.size = Pt(13)
    run3 = para.add_run()
    run3.text = "■ "
    run3.font.color.rgb = RED
    run3.font.size = Pt(13)
    run4 = para.add_run()
    run4.text = "Rejected or escalated"
    run4.font.size = Pt(13)


# ============================================================
# Main
# ============================================================

def build_deck(stats: dict) -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    today = datetime.now().strftime("%d %B %Y")
    add_title_slide(
        prs,
        "ODMI Agent Swarm",
        f"Status and next steps — supervisor meeting, {today}",
    )

    # ----- Slide 2: what's built -----
    add_text_slide(
        prs,
        "What is built",
        [
            f"Question bank parsed and loaded: {stats['n_questions']} ODMI 2025 items in SQLite.",
            f"Hand-mark workspace live: {stats['n_locked']} of {stats['n_hand_marks']} marks locked (D9 commit-SHA stamped).",
            "Three-agent swarm: Researcher → Verifier (4 strategies) → Adjudicator. LangGraph-style Coordinator.",
            "Streamlit dashboard with 9 pages: Run Console, Results, Questions, Strategy Lab, Hand-marks, Models, Costs, Prompts.",
            f"Live runs: {stats['n_researcher']} Researcher, {stats['n_verifier']} Verifier, "
            f"{stats['n_adjudications']} Adjudication, {stats['n_finals']} finalised pairs.",
            f"Spend to date: ${stats['cost_total']:.2f} via Claude Max through CLIProxyAPI.",
        ],
    )

    # ----- Slide 3: how the system works -----
    add_text_slide(
        prs,
        "How the swarm answers one question",
        [
            "Coordinator pulls (question, country), opens a subtrio with a UUID, retry count = 0.",
            "Researcher: Tavily search → fetch_url → reason → return {answer, source_url, evidence_quote, confidence}.",
            "Verifier: same source URL, adversarial prompt (default: 'find disproof'). Returns pass/fail.",
            "If Verifier rejects, Coordinator retries the Researcher up to 3 times.",
            "On exhaustion, Adjudicator reads the full history and picks a winner or escalates to a human queue.",
            "Every stage writes to SQLite. Every LLM call logs tokens, cost, latency, prompt version.",
        ],
    )

    # ----- Slide 4: evaluation methodology -----
    add_text_slide(
        prs,
        "How we will measure it",
        [
            "Answerability rubric (3 × 0–3 scales): Evidence Accessibility, Answer Determinism, Source Complexity. Composite 0–9 → 4 tiers.",
            "Rubric is an analytical lens, not a runtime classifier (D8). Hand-marks are the ground truth.",
            "D9 audit-trail rule: every hand-mark must be locked in git before any related swarm run.",
            "Headline RQ5: cost–accuracy surface across the rubric space. Token, latency, $ per correct answer.",
            "Optimisation experiments: prompt compression × retrieval scope × Verifier strategy × model variant (Haiku / Sonnet / Opus / tiered).",
            "External validity: 2025 cycle is primary; 2024 cycle is the held-out test set (D13).",
        ],
    )

    # ----- Slide 5: results so far -----
    add_country_chart_slide(
        prs,
        "Pairs finalised per country, success vs failure",
        stats["country_outcomes"],
    )

    # ----- Slide 6: decisions taken / open -----
    add_two_col_slide(
        prs,
        "Decisions: taken and open",
        "Locked (D-numbered)", [
            "D1: LLM via CLIProxyAPI on Claude Max.",
            "D2: SQLite as single store. Schema in setup_sqlite.py.",
            "D7: Phased rollout — FR → 6-country matrix → all 36.",
            "D8: Rubric is analytical, not a classifier.",
            "D12: Tokens, latency, cost are first-class research dimensions.",
            "D15: Verifier prompt strategies as experimental variable.",
            "D16: Adjudicator at retry exhaustion.",
            "D18: Model variants (Haiku/Sonnet/Opus/tiered) as experiments.",
        ],
        "Open questions", [
            "Q1: Final per-tier hand-mark sample size.",
            "Q4: Language-confidence table for Phase B.",
            "Q10: Trusted-domain JSON per country.",
            "Q12: Which Verifier strategy is the default.",
            "Q13: Adjudicator confidence threshold for picking a winner.",
            "Q14: Injected-hallucination arm for the strategy comparison.",
            "Q15: Researcher/Verifier/Adjudicator model mix in the tiered condition.",
        ],
    )

    # ----- Slide 7: short term -----
    add_text_slide(
        prs,
        "Short-term next steps (next 2 weeks)",
        [
            "Hand-mark 10 France questions across all four rubric tiers, commit + sync.",
            "Run swarm on the full 10-question pilot with verifier-disprove, all-Sonnet baseline.",
            "First real Family-1 cost-side experiments: prompt-compressed vs baseline on same 10.",
            "Begin Family-2 Verifier strategy comparison with the four prompts.",
            "First analysis pass: accuracy by rubric tier × dimension, cost per correct answer.",
            "Draft results + methodology sections of the dissertation as the data lands.",
        ],
    )

    # ----- Slide 8: long term -----
    add_text_slide(
        prs,
        "Long-term roadmap",
        [
            "Phase B — six-country matrix (FR, DE, NL, RO, HU, EE). Hand-marks re-run per country.",
            "Family-3 model variants: pure Haiku, pure Sonnet, pure Opus, tiered. Cost–accuracy surface.",
            "External validity: rerun the pipeline against the 2024 cycle, untouched, as held-out test.",
            "Phase C — all 36 EU countries (stretch). Live 2026 cycle deployment in parallel.",
            "Failure mode taxonomy as a primary research output.",
            "Final dissertation submission: 2 August 2026.",
        ],
    )

    # ----- Slide 9: KPIs / one-look snapshot -----
    avg_seconds = stats["avg_runtime_s"]
    add_text_slide(
        prs,
        "Snapshot today",
        [
            f"Questions in catalogue: {stats['n_questions']}.",
            f"Hand-marks locked: {stats['n_locked']}.",
            f"Subtrios finalised: {stats['n_finals']}.",
            f"Average subtrio runtime: {avg_seconds:.1f} s.",
            f"Total LLM spend: ${stats['cost_total']:.2f}.",
            "All 9 dashboard pages live and rendering against real data.",
        ],
    )

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
