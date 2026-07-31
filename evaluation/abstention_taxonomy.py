"""Abstention and failure taxonomy (read-only diagnostic).

Pulls every non-committed pair from phase2_final (final_answer='inconclusive'
OR terminal_status='agent_failure'), walks its full Researcher / Verifier /
Adjudicator trail, and classifies each into an empirically derived category.

Strictly read-only. Does not write to the DB and never feeds ground truth back
into any pipeline. Joins to ground_truth only to report whether the experts
committed an answer where the swarm abstained.

Run:  uv run python evaluation/abstention_taxonomy.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "odmi.db"

# Deny-listed evaluation-cycle hosts (D24). Matches the spirit of
# agents/tools/blocked_domains.py without importing it.
DENY_HOSTS = ("data.europa.eu",)
MQA_MARKERS = ("data.europa.eu/mqa", "/mqa/", "metadata-quality")

FETCH_ERROR_MARKERS = (
    "status 0",
    "head/get returned status",
    "timed out",
    "timeout",
    "connection",
    "ssl",
    "403",
    "404",
    "429",
    "500",
    "502",
    "503",
    "unreachable",
    "could not fetch",
    "failed to fetch",
)

# Phrases the agents emit when results existed but were in the national language
# or the answer lived behind a self-report / portal admin surface.
SELFREPORT_MARKERS = (
    "self-report",
    "self report",
    "self-assess",
    "self-asses",
    "would require explicit",
    "no formal policy",
    "no explicit policy",
    "not publicly documented",
    "no public documentation",
    "internal process",
    "administrative",
    "not published",
    "would need internal",
)

CONFIDENCE_FLOOR = 0.65


def col(cur, table):
    return [r[1] for r in cur.execute(f"PRAGMA table_info({table})").fetchall()]


def jload(s):
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else [v]
    except Exception:
        return []


def has_deny_contact(urls_blobs):
    for blob in urls_blobs:
        for u in jload(blob):
            if not isinstance(u, str):
                continue
            low = u.lower()
            if any(h in low for h in DENY_HOSTS):
                return True
    return False


def has_mqa_contact(urls_blobs):
    for blob in urls_blobs:
        for u in jload(blob):
            if isinstance(u, str) and any(m in u.lower() for m in MQA_MARKERS):
                return True
    return False


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # population: every non-committed pair
    finals = cur.execute(
        """
        SELECT * FROM phase2_final
        WHERE final_answer='inconclusive' OR terminal_status='agent_failure'
        """
    ).fetchall()

    pair_ids = [f["pair_run_id"] for f in finals]
    print(f"Non-committed pairs: {len(finals)}")

    # pull all trail rows for those pairs in bulk
    def rows_for(table):
        out = defaultdict(list)
        for r in cur.execute(f"SELECT * FROM {table}").fetchall():
            if r["pair_run_id"] in set(pair_ids):
                out[r["pair_run_id"]].append(r)
        return out

    res_by_pair = rows_for("phase2_researcher_runs")
    ver_by_pair = rows_for("phase2_verifier_runs")
    adj_by_pair = rows_for("phase2_adjudications")

    # ground truth lookup
    gt = {}
    for g in cur.execute(
        "SELECT question_id, country_code, response, dimension FROM ground_truth"
    ).fetchall():
        gt[(g["question_id"], g["country_code"])] = (g["response"], g["dimension"])

    # question dimension fallback from ground_truth (per question, any country)
    qdim = {}
    for g in cur.execute(
        "SELECT question_id, dimension FROM ground_truth WHERE dimension IS NOT NULL"
    ).fetchall():
        qdim.setdefault(g["question_id"], g["dimension"])

    records = []
    for f in finals:
        pid = f["pair_run_id"]
        qid, cc = f["question_id"], f["country_code"]
        res = sorted(res_by_pair.get(pid, []), key=lambda r: (r["retry_count"], r["id"]))
        ver = sorted(ver_by_pair.get(pid, []), key=lambda r: (r["retry_count"], r["id"]))
        adj = adj_by_pair.get(pid, [])

        # researcher signals across all attempts
        res_failure_modes = [r["failure_mode"] for r in res if r["failure_mode"]]
        notes_all = " ".join((r["notes"] or "") for r in res).lower()
        raw_all = " ".join((r["raw_response"] or "") for r in res).lower()
        explan_all = " ".join((r["answer_explanation"] or "") for r in res).lower()
        ans_seq = [(r["answer"] or "").strip().lower() for r in res]
        committed_answers = [
            a for a in ans_seq if a and a not in ("inconclusive", "other", "i don't know")
        ]
        ever_committed = len(committed_answers) > 0
        url_blobs = [r["fetched_urls"] for r in res] + [r["source_url"] for r in res]
        # source_url is a scalar; wrap so jload sees a list
        url_blobs = [b if (b and b.strip().startswith("[")) else json.dumps([b]) if b else "[]" for b in url_blobs]

        snippets_present = any(
            (r["search_snippets"] and r["search_snippets"] not in ("[]", "")) for r in res
        )
        any_search_empty = ("search_empty" in (f["final_failure_reason"] or "")) or (
            not snippets_present and len(res) > 0
        )

        # verifier signals
        ver_substr_fail = any(v["substring_check_result"] == "fail" for v in ver)
        last_ver = ver[-1] if ver else None
        ver_rej_all = " ".join((v["rejection_reason"] or "") for v in ver).lower()

        # adjudicator signals. D51/D52 renamed the abstain verdict
        # (`escalate_human` -> `abstain`) and terminal status
        # (`escalated_adjudicator` -> `abstained_adjudicator`); legacy rows
        # keep the old strings, so match both.
        adj_verdicts = [a["adjudicator_verdict"] for a in adj]
        adj_abstained = (
            "abstain" in adj_verdicts
            or "escalate_human" in adj_verdicts
            or f["terminal_status"] in ("abstained_adjudicator", "escalated_adjudicator")
        )

        # confidence
        ans_conf = f["final_answer_confidence"]
        ret_conf = f["final_retrieval_confidence"]
        max_res_ans_conf = max(
            [r["answer_confidence"] for r in res if r["answer_confidence"] is not None] or [None]
        )

        is_failure = f["terminal_status"] == "agent_failure"
        null_answer = (f["final_answer"] is None) or (f["final_answer"] == "")

        # classification (priority ordered)
        cat = None
        reason = ""

        # 1. hard agent failure with no answer at all
        if is_failure and null_answer:
            if "schema_invalid" in (f["final_failure_reason"] or ""):
                cat, reason = "F1_schema_invalid_failure", "schema_invalid"
            elif "no verifier output" in (f["final_failure_reason"] or ""):
                cat, reason = "F2_pipeline_no_verifier_output", "no verifier output for adjudication"
            elif any_search_empty or "search_empty" in (f["final_failure_reason"] or ""):
                cat, reason = "F3_search_empty_failure", "search_empty"
            else:
                cat, reason = "F4_other_agent_failure", (f["final_failure_reason"] or "uncategorised")

        # 2. thin web: no usable search results anywhere in the trail
        elif any_search_empty:
            cat, reason = "A_thin_web_no_results", "no snippets / search_empty across attempts"

        # 3. fetch error: pages found but could not be retrieved
        elif ("url_unreachable" in res_failure_modes) or any(
            m in notes_all for m in FETCH_ERROR_MARKERS
        ):
            cat, reason = "B_fetch_error", "url_unreachable / fetch markers in notes"

        # 4. deny-listed source contact (answer likely on data.europa.eu / MQA)
        elif has_mqa_contact(url_blobs):
            cat, reason = "C_denylist_mqa", "MQA / data.europa.eu metadata-quality contacted"
        elif has_deny_contact(url_blobs):
            cat, reason = "C_denylist_europa", "data.europa.eu in fetched/source urls"

        # 5. verification attrition: researcher committed but evidence ungrounded
        elif ever_committed and ver_substr_fail:
            cat, reason = "D_evidence_ungrounded", "researcher committed but substring gate failed"

        # 6. verification attrition: researcher committed, verifier rejected on relevance
        elif ever_committed and last_ver is not None and last_ver["verdict"] == "fail":
            cat, reason = "E_verifier_relevance_reject", "researcher committed, verifier failed on relevance"

        # 7. below confidence floor: had a committed answer but under 0.65
        elif ever_committed and (max_res_ans_conf is not None) and max_res_ans_conf < CONFIDENCE_FLOOR:
            cat, reason = "G_below_confidence_floor", f"best researcher answer_confidence {max_res_ans_conf} < {CONFIDENCE_FLOOR}"

        # 8. self-report / not-publicly-documented ceiling
        elif any(m in (explan_all + notes_all) for m in SELFREPORT_MARKERS):
            cat, reason = "H_selfreport_or_undocumented", "agent text cites no formal/public documentation"

        # 9. researcher never committed at all (genuinely could not answer)
        elif not ever_committed:
            cat, reason = "I_researcher_never_committed", "all attempts inconclusive/other"

        else:
            cat, reason = "Z_other", "uncategorised"

        # ground truth
        gt_resp, gt_dim = gt.get((qid, cc), (None, None))
        dim = gt_dim or qdim.get(qid)
        gt_committed = bool(gt_resp) and gt_resp.strip().lower() not in (
            "",
            "inconclusive",
            "n/a",
            "not applicable",
            "no data",
            "i don't know",
            "i dont know",
            "unknown",
        )

        records.append(
            dict(
                pair=f"{qid}:{cc}",
                qid=qid,
                cc=cc,
                exp=f["experiment_id"] or "(null)",
                terminal_status=f["terminal_status"],
                final_answer=f["final_answer"],
                cat=cat,
                reason=reason,
                ans_conf=ans_conf,
                ret_conf=ret_conf,
                retry_count=f["retry_count"],
                ever_committed=ever_committed,
                adj_abstained=adj_abstained,
                dimension=dim,
                gt_resp=gt_resp,
                gt_committed=gt_committed,
                notes_snip=notes_all[:140],
                explan_snip=(explan_all[:200]),
            )
        )

    # ----------------------------------------------------------------- output
    print("\n=== CATEGORY COUNTS ===")
    cats = Counter(r["cat"] for r in records)
    for c, n in sorted(cats.items()):
        gtc = sum(1 for r in records if r["cat"] == c and r["gt_committed"])
        print(f"{c:34s} {n:4d}   (GT committed an answer in {gtc}/{n})")

    print("\n=== BY EXPERIMENT ===")
    by_exp = Counter(r["exp"] for r in records)
    for e, n in by_exp.most_common():
        print(f"{e:38s} {n}")

    print("\n=== BY DIMENSION ===")
    by_dim = Counter((r["dimension"] or "UNKNOWN") for r in records)
    for d, n in by_dim.most_common():
        print(f"{d:14s} {n}")

    print("\n=== BY COUNTRY ===")
    by_cc = Counter(r["cc"] for r in records)
    for c, n in by_cc.most_common():
        print(f"{c:6s} {n}")

    print("\n=== GT-COMMITTED (honest abstain vs miss) overall ===")
    miss = sum(1 for r in records if r["gt_committed"])
    print(f"GT committed a real answer where we abstained: {miss}/{len(records)}")

    # write per-record CSV for the report appendix
    out = Path(__file__).resolve().parent / "abstention_records.csv"
    import csv

    with out.open("w", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "pair", "exp", "cat", "dimension", "terminal_status", "final_answer",
                "ans_conf", "ret_conf", "retry_count", "ever_committed",
                "adj_abstained", "gt_resp", "gt_committed", "reason",
                "explan_snip", "notes_snip",
            ],
        )
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    print(f"\nWrote {out}")

    # also dump category x dimension matrix
    print("\n=== CATEGORY x DIMENSION ===")
    mat = defaultdict(Counter)
    for r in records:
        mat[r["cat"]][r["dimension"] or "UNKNOWN"] += 1
    dims = ["policy_dimension", "portal_dimension", "quality_dimension", "impact_dimension", "UNKNOWN"]
    short = {d: d.replace("_dimension", "").title() for d in dims}
    print(f"{'category':34s} " + " ".join(f"{short.get(d,d):8s}" for d in dims))
    for c in sorted(mat):
        print(f"{c:34s} " + " ".join(f"{mat[c].get(d,0):8d}" for d in dims))

    # abstention RATE by dimension and country needs denominators (all finalised)
    print("\n=== DENOMINATORS for rate (all finalised pairs) ===")
    all_finals = cur.execute("SELECT question_id, country_code, final_answer, terminal_status, experiment_id FROM phase2_final").fetchall()
    tot_by_dim = Counter()
    tot_by_cc = Counter()
    abst_by_dim = Counter()
    abst_by_cc = Counter()
    noncommitted_keys = {(r["qid"], r["cc"], r["exp"]) for r in records}
    for a in all_finals:
        d = qdim.get(a["question_id"], "UNKNOWN")
        tot_by_dim[d] += 1
        tot_by_cc[a["country_code"]] += 1
        key = (a["question_id"], a["country_code"], a["experiment_id"] or "(null)")
        if key in noncommitted_keys:
            abst_by_dim[d] += 1
            abst_by_cc[a["country_code"]] += 1
    print(f"{'dimension':18s} {'abst':>6s} {'total':>6s} {'rate':>7s}")
    for d in dims:
        if tot_by_dim.get(d):
            print(f"{short.get(d,d):18s} {abst_by_dim[d]:6d} {tot_by_dim[d]:6d} {abst_by_dim[d]/tot_by_dim[d]*100:6.1f}%")
    print(f"{'country':18s} {'abst':>6s} {'total':>6s} {'rate':>7s}")
    for c, t in tot_by_cc.most_common():
        print(f"{c:18s} {abst_by_cc[c]:6d} {t:6d} {abst_by_cc[c]/t*100:6.1f}%")


if __name__ == "__main__":
    main()
