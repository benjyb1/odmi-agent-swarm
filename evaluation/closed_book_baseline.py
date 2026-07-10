"""Closed-book baseline: what share of the 2025 ODMI answers does the bare
model reproduce from parametric memory alone, with retrieval disabled?

Two purposes (see docs/SPEC.md, the closed-book decision):

1. Contamination bound. A high closed-book match rate would mean the model
   already carries the published 2025 answers, so a swarm "match" is not proof
   the pipeline found the evidence. This replaces the "structurally impossible"
   overclaim with a measured number. Reported against a majority-class floor,
   because a yes-heavy gold set is easy to hit by base rate alone.

2. RQ1's missing floor. Retrieval-plus-verification is only worth its cost if
   it beats the model's own memory. This gives the memory-only number to sit
   under the swarm's match rate on the same pairs.

No retrieval, no tools, no evidence. One structured call per (question,
country): the ODMI question, the allowed labels, and an instruction to answer
only from recalled knowledge or abstain. Every row is logged to
`closed_book_answers` with the full prompt and raw response for replay.

Universe (D-closed-book): 20% of the full dev set, stratified by dimension
within each dev country (NL, MT, NO, FR, AL), fixed seed for reproducibility.

Usage:
    uv run python evaluation/closed_book_baseline.py --dry-run
    uv run python evaluation/closed_book_baseline.py --run-id cb_YYYYMMDD
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from agents.tools import llm  # noqa: E402

_DB_PATH = _REPO_ROOT / "data" / "odmi.db"

DEV_COUNTRIES = ["NL", "MT", "NO", "FR", "AL"]
SAMPLE_FRACTION = 0.20
SEED = 20260709
PROMPT_VERSION = "closed_book_v1"


class ClosedBookAnswer(BaseModel):
    answer: str = Field(description="Exactly one label from the allowed set, "
                                    "or 'inconclusive' if you do not recall it.")
    known: bool = Field(description="True only if you actually recall this "
                                    "country's situation, not a general prior.")
    rationale: str = Field(description="One short sentence, 40 words max.")


def _now() -> str:
    return (datetime.now(timezone.utc).replace(tzinfo=None)
            .isoformat(timespec="seconds") + "Z")


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS closed_book_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            question_id TEXT NOT NULL,
            country_code TEXT NOT NULL,
            model TEXT,
            prompt_version TEXT,
            prompt_text TEXT,
            raw_response TEXT,
            parsed_answer TEXT,
            known INTEGER,
            gt_response TEXT,
            decision TEXT,
            dimension TEXT,
            answer_shape TEXT,
            match_status TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            estimated_cost_usd REAL,
            created_at TEXT
        )
        """
    )
    conn.commit()


def _select_sample(conn: sqlite3.Connection) -> list[dict]:
    """Deterministic 20% stratified by dimension within each dev country."""
    rows = conn.execute(
        """
        SELECT g.question_id, g.country_code, g.country_name, g.dimension,
               g.response AS gt_response, g.decision,
               q.question_text, q.allowed_answers, q.answer_shape
        FROM ground_truth g
        JOIN questions q ON q.question_id = g.question_id
        WHERE g.country_code IN (%s)
        """ % ",".join("?" * len(DEV_COUNTRIES)),
        DEV_COUNTRIES,
    ).fetchall()
    cols = [d[0] for d in conn.execute(
        "SELECT g.question_id, g.country_code, g.country_name, g.dimension, "
        "g.response AS gt_response, g.decision, q.question_text, "
        "q.allowed_answers, q.answer_shape FROM ground_truth g "
        "JOIN questions q ON q.question_id=g.question_id LIMIT 0").description]
    recs = [dict(zip(cols, r)) for r in rows]

    sample: list[dict] = []
    for cc in DEV_COUNTRIES:
        by_dim: dict[str, list[dict]] = {}
        for r in recs:
            if r["country_code"] == cc:
                by_dim.setdefault(r["dimension"], []).append(r)
        for dim, items in by_dim.items():
            items = sorted(items, key=lambda x: x["question_id"])
            k = max(1, round(len(items) * SAMPLE_FRACTION))
            rng = random.Random(f"{SEED}:{cc}:{dim}")
            sample.extend(rng.sample(items, k))
    sample.sort(key=lambda x: (x["country_code"], x["question_id"]))
    return sample


def classify(final: str | None, gt: str | None) -> str:
    """Python mirror of dashboard/lib/db.py::_MATCH_STATUS_SQL (essentials)."""
    if gt is None or gt.strip() == "":
        return "no_ground_truth"
    if final is None or final.strip() == "":
        return "no_swarm_answer"
    g = gt.strip().lower().replace("_", " ")
    f = final.strip().lower().replace("_", " ")
    if g in ("not applicable", "n/a", "na"):
        return "match" if f in ("inconclusive", "not applicable", "n/a", "na") \
            else "flag_review"
    if final.strip().lower() == "inconclusive":
        return "abstained"
    if f == g:
        return "match"
    return "differ"


def _build_prompt(rec: dict) -> tuple[str, str]:
    allowed = json.loads(rec["allowed_answers"])
    system = (
        "You are completing the EU Open Data Maturity Index (ODMI) questionnaire "
        f"for {rec['country_name']} for the 2025 assessment cycle. Answer "
        "entirely from your own prior knowledge. You have NO web access, NO "
        "documents and NO retrieval of any kind. Do not infer from general "
        "priors about how countries usually score. Answer only if you actually "
        "recall this country's specific situation. Choose exactly one label from "
        "the allowed answers. If you do not recall it, set known=false and "
        "answer 'inconclusive'."
    )
    user = (
        f"Country: {rec['country_name']} ({rec['country_code']})\n\n"
        f"Question ({rec['question_id']}):\n{rec['question_text']}\n\n"
        f"Allowed answers (choose exactly one, verbatim): {allowed}\n\n"
        "Return the single allowed label, whether you actually recall it, and a "
        "one-sentence rationale."
    )
    return system, user


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the sample and one example prompt, no LLM calls.")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap the number of pairs (smoke test).")
    ap.add_argument("--db", default=str(_DB_PATH),
                    help="SQLite path. Point at the canonical checkout DB so "
                         "results persist where the dashboard reads them, not "
                         "the diverging worktree copy.")
    args = ap.parse_args()

    run_id = args.run_id or f"cb_{datetime.now(timezone.utc):%Y%m%d}"

    conn = sqlite3.connect(args.db, timeout=30.0)
    sample = _select_sample(conn)
    if args.limit:
        sample = sample[: args.limit]

    print(f"run_id={run_id}  sample={len(sample)} pairs "
          f"(20% of {len(DEV_COUNTRIES)}x143 dev)")
    by_cc: dict[str, int] = {}
    for r in sample:
        by_cc[r["country_code"]] = by_cc.get(r["country_code"], 0) + 1
    print("  by country:", by_cc)

    if args.dry_run:
        ex = sample[0]
        sys_p, usr_p = _build_prompt(ex)
        print("\n--- example prompt (", ex["country_code"], ex["question_id"],
              ") ---")
        print("[system]", sys_p)
        print("[user]", usr_p[:600], "...")
        print("\n[gt]", ex["gt_response"], "| decision", ex["decision"])
        conn.close()
        return

    _ensure_table(conn)
    done = {
        (r[0], r[1]) for r in conn.execute(
            "SELECT question_id, country_code FROM closed_book_answers "
            "WHERE run_id = ?", (run_id,)).fetchall()
    }
    if done:
        print(f"  resume: {len(done)} pairs already logged for {run_id}, skipping")
    counts: dict[str, int] = {}
    for i, rec in enumerate(sample, 1):
        if (rec["question_id"], rec["country_code"]) in done:
            continue
        sys_p, usr_p = _build_prompt(rec)
        try:
            parsed, usage = llm.call_for_structured(
                system=sys_p,
                user_message=usr_p,
                output_schema=ClosedBookAnswer,
                model="claude-sonnet-4-6",
                temperature=0.0,
                max_tokens=400,
                usage_context=f"closed_book:{run_id}",
            )
            answer, known, raw = parsed.answer, parsed.known, parsed.model_dump_json()
            in_t, out_t, cost = (usage.input_tokens, usage.output_tokens,
                                 usage.estimated_cost_usd)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(sample)}] {rec['country_code']} "
                  f"{rec['question_id']} ERROR {type(exc).__name__}: {exc}")
            raise
        status = classify(answer, rec["gt_response"])
        counts[status] = counts.get(status, 0) + 1
        conn.execute(
            """INSERT INTO closed_book_answers
               (run_id, question_id, country_code, model, prompt_version,
                prompt_text, raw_response, parsed_answer, known, gt_response,
                decision, dimension, answer_shape, match_status,
                input_tokens, output_tokens, estimated_cost_usd, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, rec["question_id"], rec["country_code"], "claude-sonnet-4-6",
             PROMPT_VERSION, sys_p + "\n\n" + usr_p, raw, answer,
             1 if known else 0, rec["gt_response"], rec["decision"],
             rec["dimension"], rec["answer_shape"], status,
             in_t, out_t, cost, _now()),
        )
        conn.commit()
        print(f"  [{i}/{len(sample)}] {rec['country_code']} {rec['question_id']} "
              f"-> {answer!r} vs {rec['gt_response']!r} = {status}")

    # Summary from the DB so a resumed run totals every logged pair, not just
    # the ones this invocation ran.
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT match_status, COUNT(*) FROM closed_book_answers "
        "WHERE run_id = ? GROUP BY match_status", (run_id,)).fetchall()}
    scored = {k: v for k, v in counts.items()
              if k in ("match", "differ", "abstained")}
    denom = sum(scored.values())
    acc = counts.get("match", 0) / denom if denom else 0.0
    print("\n=== closed-book summary ===")
    print("status counts:", counts)
    print(f"match rate (match / match+differ+abstained) = {acc:.3f} "
          f"(n={denom})")

    art = _REPO_ROOT / "evaluation" / "runs" / f"{run_id}.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps(
        {"run_id": run_id, "model": "claude-sonnet-4-6",
         "prompt_version": PROMPT_VERSION, "seed": SEED,
         "sample_size": len(sample), "by_country": by_cc,
         "status_counts": counts, "match_rate": acc}, indent=2))
    print("artifact:", art)
    conn.close()


if __name__ == "__main__":
    main()
