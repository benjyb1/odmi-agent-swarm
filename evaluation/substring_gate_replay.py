"""Offline replay of substring-gate variants over stored Verifier rows.

The D34 gate checks the Researcher's evidence quote against the snippets the
Researcher actually read, with NFKC/casefold/punctuation normalisation
(agents/tools/substring.py). Production data shows the gate fires far more
often on gold-correct candidates than gold-wrong ones, so this replays gate
variants over the stored (quote, snippets) pairs to find out why it fires and
what a softer gate would do. No API calls.

Variants:
  V0 current   normalised full-quote substring (the production gate).
  V1 window    token-containment: >= 80 per cent of the quote's normalised
               tokens appear within a single stored snippet (order ignored).
               Tolerates stitching, ellipses, and trailing additions.
  V2 prefix    normalised substring of the quote's first 25 tokens. Tolerates
               quotes that start inside a snippet and run past its end.

For each variant: fire rate on gold-correct vs gold-wrong candidates (the
gate's job is fabrication detection, but gold-correctness is the only ground
truth available at scale; a gate that fires mostly on correct candidates is
miscalibrated for its downstream effect, which is reject-and-retry). Also
reports quote-length stats for fires vs passes, to test the hypothesis that
fires are length artefacts (quote longer than the ~300-char provider snippet)
rather than fabrication.

Usage:
  uv run python evaluation/substring_gate_replay.py --countries MT NO FR EE
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agents.tools.substring import normalise
from evaluation.stack_attribution import answers_match, is_definite, _wilson_str

DB_PATH = REPO_ROOT / "data" / "odmi.db"


def v0_current(quote: str, snippets: list[str]) -> bool:
    corpus = normalise("\n\n".join(snippets))
    return normalise(quote) in corpus


def v1_window(quote: str, snippets: list[str], threshold: float = 0.8) -> bool:
    q_tokens = normalise(quote).split()
    if not q_tokens:
        return False
    q_set = set(q_tokens)
    for s in snippets:
        s_set = set(normalise(s).split())
        if len(q_set & s_set) / len(q_set) >= threshold:
            return True
    return False


def v2_prefix(quote: str, snippets: list[str], n_tokens: int = 25) -> bool:
    prefix = " ".join(normalise(quote).split()[:n_tokens])
    if not prefix:
        return False
    corpus = normalise("\n\n".join(snippets))
    return prefix in corpus


VARIANTS = {"v0_current": v0_current, "v1_window": v1_window, "v2_prefix": v2_prefix}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=["MT", "NO", "FR", "EE"])
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ph = ",".join("?" for _ in args.countries)

    qshape = {
        r["question_id"]: r["answer_shape"]
        for r in conn.execute("SELECT question_id, answer_shape FROM questions")
    }
    gold = {
        (r["question_id"], r["country_code"]): r["response"]
        for r in conn.execute(
            f"SELECT question_id, country_code, response FROM ground_truth "
            f"WHERE country_code IN ({ph}) AND response IS NOT NULL AND TRIM(response) <> ''",
            args.countries,
        )
    }

    rows = conn.execute(
        f"""SELECT v.substring_check_result AS recorded, r.question_id,
                   r.country_code, r.answer, r.evidence_quote, r.search_snippets
            FROM phase2_verifier_runs v
            JOIN phase2_researcher_runs r ON r.id = v.researcher_run_id
            WHERE v.country_code IN ({ph}) AND v.experiment_id IS NULL
              AND r.evidence_quote IS NOT NULL AND r.search_snippets IS NOT NULL""",
        args.countries,
    ).fetchall()

    cells = {name: defaultdict(int) for name in VARIANTS}
    agree_with_recorded = defaultdict(int)
    n_scored = 0
    fire_quote_lens, pass_quote_lens = [], []
    for row in rows:
        if not is_definite(row["answer"]):
            continue
        g = gold.get((row["question_id"], row["country_code"]))
        if g is None:
            continue
        try:
            snips = [s.get("snippet") or "" for s in json.loads(row["search_snippets"])]
        except (TypeError, json.JSONDecodeError):
            continue
        if not any(snips):
            continue
        n_scored += 1
        correct = answers_match(row["answer"], g, qshape.get(row["question_id"]))
        quote = row["evidence_quote"]
        for name, fn in VARIANTS.items():
            fired = not fn(quote, snips)  # gate "fires" when the check fails
            cells[name][("fire" if fired else "pass", correct)] += 1
            if name == "v0_current":
                (fire_quote_lens if fired else pass_quote_lens).append(
                    len(normalise(quote).split())
                )
                recorded_fire = row["recorded"] == "fail"
                agree_with_recorded[fired == recorded_fire] += 1

    report: dict = {
        "n_scored_judgements": n_scored,
        "v0_replay_agreement_with_recorded_gate": _wilson_str(
            agree_with_recorded[True], sum(agree_with_recorded.values())
        ),
        "quote_token_length_when_v0_fires": {
            "median": statistics.median(fire_quote_lens) if fire_quote_lens else None,
            "n": len(fire_quote_lens),
        },
        "quote_token_length_when_v0_passes": {
            "median": statistics.median(pass_quote_lens) if pass_quote_lens else None,
            "n": len(pass_quote_lens),
        },
    }
    for name, c in cells.items():
        fc, fw = c[("fire", True)], c[("fire", False)]
        pc, pw = c[("pass", True)], c[("pass", False)]
        report[name] = {
            "fires_on_gold_correct": _wilson_str(fc, fc + pc),
            "fires_on_gold_wrong": _wilson_str(fw, fw + pw),
            "fire_precision_for_wrongness": _wilson_str(fw, fc + fw) if fc + fw else "n/a",
        }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)


if __name__ == "__main__":
    main()
