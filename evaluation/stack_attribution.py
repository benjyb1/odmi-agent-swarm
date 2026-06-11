"""Per-element attribution over the production swarm logs.

Quantifies how each element of the Researcher / Verifier / Adjudicator stack
affects final accuracy, using only rows already in the DB. No dispatch, no API
calls, so it cannot contend with a live experiment and is replayable by an
examiner from the SQLite file alone.

Analyses:

  A. Verifier discrimination. Treats each Verifier judgement of a definite
     Researcher candidate as a binary classification (pass = accept) and
     scores it against the ODMI gold for that pair: TPR = P(pass | candidate
     correct), TNR = P(fail | candidate wrong), Youden's J. Reported per
     country and pooled, per judgement and per pair (first attempt only),
     because retries repeat pairs.
  B. Retry dynamics. For pairs with at least one retry: did the loop recover
     a wrong first candidate, degrade a correct one, or end in abstention?
     Includes the false-reject cost: the final outcome of pairs whose correct
     first candidate the Verifier rejected.
  C. Adjudicator value. On adjudicated pairs: adjudicator answer vs gold,
     against the last Researcher candidate vs gold, with the flip table.
  D. Snippet utilisation. Per Researcher run: how many snippets were fetched,
     whether the cited source URL is one of the snippet URLs, whether the
     evidence quote occurs in the stored snippets, and the rank of the cited
     snippet in the result ordering.
  E. Substring gate. How often the deterministic gate fired and what verdict
     it accompanied.

Caveats inherited from D22: ODMI gold can be one cycle stale, so "candidate
correct" means "matches the published gold", not certified truth. A Verifier
fail of a gold-matching answer can still be epistemically defensible when the
evidence is weak; analysis B reports the downstream consequence, which is the
number that matters for the pipeline.

Usage:
  uv run python evaluation/stack_attribution.py
  uv run python evaluation/stack_attribution.py --countries MT NO FR EE
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.stats import wilson_interval

DB_PATH = REPO_ROOT / "data" / "odmi.db"

ABSTENTIONS = {"inconclusive", "not_applicable", "n/a", "i don't know", "other", ""}


def _norm(s: str | None) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", s.replace("_", " ").strip().lower())


def answers_match(answer: str | None, gold: str | None, shape: str | None) -> bool:
    """Mirrors the dashboard's _MATCH_STATUS_SQL match arm (exact + binary
    yes-prefix). Near-match band adjacency is deliberately NOT a match here."""
    a, g = _norm(answer), _norm(gold)
    if not a or not g:
        return False
    if a == g:
        return True
    if shape == "binary" and a == "yes" and g.startswith("yes"):
        return True
    if shape == "binary" and a == "no" and g == "no":
        return True
    return False


def is_definite(answer: str | None) -> bool:
    return _norm(answer) not in ABSTENTIONS


def _wilson_str(k: int, n: int) -> str:
    if n == 0:
        return "n=0"
    lo, hi = wilson_interval(k, n)
    return f"{k}/{n} = {k / n:.2f} [{lo:.2f}, {hi:.2f}]"


def load_rows(conn: sqlite3.Connection, countries: list[str]):
    ph = ",".join("?" for _ in countries)
    qshape = {
        r["question_id"]: r["answer_shape"]
        for r in conn.execute("SELECT question_id, answer_shape FROM questions")
    }
    gold = {
        (r["question_id"], r["country_code"]): r["response"]
        for r in conn.execute(
            f"SELECT question_id, country_code, response FROM ground_truth "
            f"WHERE country_code IN ({ph}) AND response IS NOT NULL AND TRIM(response) <> ''",
            countries,
        )
    }
    researcher = [
        dict(r)
        for r in conn.execute(
            f"""SELECT id, pair_run_id, question_id, country_code, retry_count,
                       answer, answer_confidence, evidence_quote, source_url,
                       search_snippets, failure_mode
                FROM phase2_researcher_runs
                WHERE country_code IN ({ph}) AND experiment_id IS NULL
                ORDER BY pair_run_id, retry_count, id""",
            countries,
        )
    ]
    verifier = [
        dict(r)
        for r in conn.execute(
            f"""SELECT id, pair_run_id, question_id, country_code, retry_count,
                       researcher_run_id, verdict, substring_check_result,
                       verifier_confidence, counter_evidence_quote
                FROM phase2_verifier_runs
                WHERE country_code IN ({ph}) AND experiment_id IS NULL""",
            countries,
        )
    ]
    adjudications = [
        dict(r)
        for r in conn.execute(
            f"""SELECT pair_run_id, question_id, country_code, adjudicator_verdict,
                       adjudicator_answer, adjudicator_confidence
                FROM phase2_adjudications
                WHERE country_code IN ({ph}) AND experiment_id IS NULL""",
            countries,
        )
    ]
    finals = [
        dict(r)
        for r in conn.execute(
            f"""SELECT pair_run_id, question_id, country_code, terminal_status,
                       final_answer, retry_count, adjudicator_involved
                FROM phase2_final
                WHERE country_code IN ({ph}) AND experiment_id IS NULL""",
            countries,
        )
    ]
    return qshape, gold, researcher, verifier, adjudications, finals


# ---------------------------------------------------------------------------
# A. Verifier discrimination
# ---------------------------------------------------------------------------

def verifier_discrimination(qshape, gold, researcher, verifier) -> dict:
    rbyid = {r["id"]: r for r in researcher}
    out: dict = {"per_country": {}, "pooled": {}, "pooled_first_attempt": {}}
    cells = defaultdict(Counter)  # country -> Counter over (verdict, cand_correct)
    first_cells = Counter()
    for v in verifier:
        r = rbyid.get(v["researcher_run_id"])
        if r is None or not is_definite(r["answer"]):
            continue
        g = gold.get((r["question_id"], r["country_code"]))
        if g is None:
            continue
        correct = answers_match(r["answer"], g, qshape.get(r["question_id"]))
        cells[r["country_code"]][(v["verdict"], correct)] += 1
        if v["retry_count"] == 0:
            first_cells[(v["verdict"], correct)] += 1

    def summarise(c: Counter) -> dict:
        tp = c[("pass", True)]
        fn = c[("fail", True)]
        fp = c[("pass", False)]
        tn = c[("fail", False)]
        n_correct, n_wrong = tp + fn, fp + tn
        tpr = tp / n_correct if n_correct else None
        tnr = tn / n_wrong if n_wrong else None
        return {
            "pass_correct": tp, "fail_correct": fn,
            "pass_wrong": fp, "fail_wrong": tn,
            "tpr_pass_given_correct": _wilson_str(tp, n_correct),
            "tnr_fail_given_wrong": _wilson_str(tn, n_wrong),
            "youden_j": round(tpr + tnr - 1, 3) if tpr is not None and tnr is not None else None,
            "false_reject_rate": _wilson_str(fn, n_correct),
            "false_accept_rate": _wilson_str(fp, n_wrong),
        }

    pooled = Counter()
    for cc, c in cells.items():
        out["per_country"][cc] = summarise(c)
        pooled.update(c)
    out["pooled"] = summarise(pooled)
    out["pooled_first_attempt"] = summarise(first_cells)
    return out


# ---------------------------------------------------------------------------
# B. Retry dynamics
# ---------------------------------------------------------------------------

def retry_dynamics(qshape, gold, researcher, verifier, finals) -> dict:
    rbypair = defaultdict(list)
    for r in researcher:
        rbypair[r["pair_run_id"]].append(r)
    vbyrid = defaultdict(list)
    for v in verifier:
        vbyrid[v["researcher_run_id"]].append(v)

    transitions = Counter()
    false_reject_outcomes = Counter()
    recovery_by_round = Counter()
    n_retried = 0
    for f in finals:
        g = gold.get((f["question_id"], f["country_code"]))
        if g is None:
            continue
        shape = qshape.get(f["question_id"])
        attempts = rbypair.get(f["pair_run_id"], [])
        if not attempts:
            continue
        a0 = attempts[0]
        a0_def = is_definite(a0["answer"])
        a0_ok = a0_def and answers_match(a0["answer"], g, shape)
        fin_def = is_definite(f["final_answer"])
        fin_ok = fin_def and answers_match(f["final_answer"], g, shape)

        if f["retry_count"] and f["retry_count"] > 0:
            n_retried += 1
            key = (
                ("correct" if a0_ok else ("wrong" if a0_def else "abstain")),
                ("correct" if fin_ok else ("wrong" if fin_def else "abstain")),
            )
            transitions[key] += 1
            if not a0_ok and fin_ok:
                recovery_by_round[f["retry_count"]] += 1

        # False-reject cost: first candidate matched gold but a Verifier
        # failed it on attempt 0.
        v0 = [v for v in vbyrid.get(a0["id"], []) if v["verdict"] == "fail"]
        if a0_ok and v0:
            false_reject_outcomes[
                "final_correct" if fin_ok else ("final_wrong" if fin_def else "final_abstain")
            ] += 1

    return {
        "pairs_with_retries": n_retried,
        "first_to_final_transitions": {f"{a}->{b}": n for (a, b), n in sorted(transitions.items())},
        "recovered_wrong_or_abstain_to_correct": sum(
            n for (a, b), n in transitions.items() if a != "correct" and b == "correct"
        ),
        "degraded_correct_to_wrong_or_abstain": sum(
            n for (a, b), n in transitions.items() if a == "correct" and b != "correct"
        ),
        "recovery_final_retry_count": dict(recovery_by_round),
        "false_reject_cost": dict(false_reject_outcomes),
    }


# ---------------------------------------------------------------------------
# C. Adjudicator value
# ---------------------------------------------------------------------------

def adjudicator_value(qshape, gold, researcher, adjudications, finals) -> dict:
    rbypair = defaultdict(list)
    for r in researcher:
        rbypair[r["pair_run_id"]].append(r)
    fbypair = {f["pair_run_id"]: f for f in finals}

    verdicts = Counter()
    flip = Counter()
    adj_committed = Counter()
    for a in adjudications:
        verdicts[a["adjudicator_verdict"]] += 1
        g = gold.get((a["question_id"], a["country_code"]))
        if g is None:
            continue
        shape = qshape.get(a["question_id"])
        attempts = rbypair.get(a["pair_run_id"], [])
        last_def = next(
            (r for r in reversed(attempts) if is_definite(r["answer"])), None
        )
        last_ok = last_def is not None and answers_match(last_def["answer"], g, shape)
        if a["adjudicator_verdict"] == "escalate_human" or not is_definite(a["adjudicator_answer"]):
            flip[("last_" + ("correct" if last_ok else "not"), "adj_abstain")] += 1
            continue
        adj_ok = answers_match(a["adjudicator_answer"], g, shape)
        adj_committed["correct" if adj_ok else "wrong"] += 1
        flip[(
            "last_" + ("correct" if last_ok else "not"),
            "adj_" + ("correct" if adj_ok else "wrong"),
        )] += 1

    n_adj = sum(adj_committed.values())
    return {
        "verdicts": dict(verdicts),
        "adjudicator_committed_accuracy": _wilson_str(adj_committed["correct"], n_adj),
        "flip_table_last_candidate_vs_adjudicator": {
            f"{a}|{b}": n for (a, b), n in sorted(flip.items())
        },
    }


# ---------------------------------------------------------------------------
# D. Snippet utilisation
# ---------------------------------------------------------------------------

def _norm_url(u: str | None) -> str:
    if not u:
        return ""
    u = u.strip().lower().rstrip("/")
    return re.sub(r"^https?://(www\.)?", "", u)


def snippet_utilisation(qshape, gold, researcher) -> dict:
    n_runs = 0
    snippet_counts = []
    cited_in_snippets = 0
    quote_in_snippets = 0
    cited_rank = Counter()
    correct_by_grounding = defaultdict(Counter)
    for r in researcher:
        if not r["search_snippets"] or not is_definite(r["answer"]):
            continue
        try:
            snips = json.loads(r["search_snippets"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not snips:
            continue
        n_runs += 1
        snippet_counts.append(len(snips))
        urls = [_norm_url(s.get("url")) for s in snips]
        cited = _norm_url(r["source_url"])
        in_snips = cited in urls and bool(cited)
        if in_snips:
            cited_in_snippets += 1
            cited_rank[urls.index(cited) + 1] += 1
        quote_ok = False
        if r["evidence_quote"]:
            qn = _norm(r["evidence_quote"])[:200]
            blob = _norm(" ".join(s.get("snippet") or "" for s in snips))
            quote_ok = bool(qn) and qn in blob
        if quote_ok:
            quote_in_snippets += 1
        g = gold.get((r["question_id"], r["country_code"]))
        if g is not None:
            ok = answers_match(r["answer"], g, qshape.get(r["question_id"]))
            correct_by_grounding["cited_in_snippets" if in_snips else "cited_outside"][
                "correct" if ok else "wrong"
            ] += 1

    ranks = dict(sorted(cited_rank.items()))
    grounded = {
        k: _wilson_str(v["correct"], v["correct"] + v["wrong"])
        for k, v in correct_by_grounding.items()
    }
    return {
        "runs_with_snippets_and_definite_answer": n_runs,
        "mean_snippets_per_run": round(sum(snippet_counts) / len(snippet_counts), 1)
        if snippet_counts else None,
        "cited_url_in_snippet_set": _wilson_str(cited_in_snippets, n_runs),
        "evidence_quote_found_in_snippets": _wilson_str(quote_in_snippets, n_runs),
        "cited_snippet_rank_distribution": ranks,
        "accuracy_by_citation_grounding": grounded,
    }


# ---------------------------------------------------------------------------
# E. Substring gate
# ---------------------------------------------------------------------------

def substring_gate(verifier) -> dict:
    c = Counter((v["substring_check_result"], v["verdict"]) for v in verifier)
    return {f"{sub}|{verdict}": n for (sub, verdict), n in sorted(c.items())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", nargs="+", default=["MT", "NO", "FR", "EE"])
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    qshape, gold, researcher, verifier, adjudications, finals = load_rows(
        conn, args.countries
    )

    report = {
        "countries": args.countries,
        "n_finals": len(finals),
        "n_researcher_runs": len(researcher),
        "n_verifier_runs": len(verifier),
        "n_adjudications": len(adjudications),
        "A_verifier_discrimination": verifier_discrimination(
            qshape, gold, researcher, verifier
        ),
        "B_retry_dynamics": retry_dynamics(qshape, gold, researcher, verifier, finals),
        "C_adjudicator_value": adjudicator_value(
            qshape, gold, researcher, adjudications, finals
        ),
        "D_snippet_utilisation": snippet_utilisation(qshape, gold, researcher),
        "E_substring_gate": substring_gate(verifier),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
        print(f"\nwritten to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
