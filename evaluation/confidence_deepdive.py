#!/usr/bin/env python3
"""Confidence-framework deep dive (read-only replay).

Answers three questions about the swarm's two self-reported confidences
(retrieval_confidence, answer_confidence) without any LLM call or DB write:

  A. Calibration. Does a stated answer_confidence of c correspond to an
     empirical accuracy of c? Reliability table, expected/maximum calibration
     error (ECE/MCE) and Brier score, split by route (catalogue vs web),
     answer shape, ODMI dimension and country.

  B. Threshold sweep 0.50..0.90. Precision, coverage, recall and the
     false-positive rate on negative (`no`) golds at every floor, pooled and
     per class, so we can read the achievable precision-recall frontier and
     judge whether any single floor on this confidence can separate right from
     wrong.

  C. Two-confidence predictive power. Does each of retrieval_confidence and
     answer_confidence independently rank correct above incorrect (AUROC), how
     correlated are they, and does retrieval add anything beyond answer?

Populations. The project's prior numbers pool every phase2_final row across all
experiments with no de-duplication per (question, country); that is reproduced
here as `pooled` for continuity, but it is not a set of independent units (a
pair recurs across experiment arms) and it mixes configurations. The honest
cuts are `production` (experiment_id IS NULL, de-duplicated to the latest row
per pair) and `dev` (the five D47 development countries NL MT NO FR AL). The
eight held-out countries are reported only as an out-of-sample diagnostic row
and are never used to choose a threshold.

  uv run python evaluation/confidence_deepdive.py            # full report
  uv run python evaluation/confidence_deepdive.py --json     # also dump JSON

Read-only by construction: opens the DB with mode=ro.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import evaluation.stats as stats  # noqa: E402
from evaluation._replay_common import is_correct  # noqa: E402

DB = REPO / "data" / "odmi.db"
RESULTS = REPO / "evaluation" / "results" / "confidence_deepdive.json"

ABST = {"inconclusive", "not_applicable", "not applicable", "other",
        "i don't know", "idk", "", None}
DEV = {"NL", "MT", "NO", "FR", "AL"}
HELD_OUT = {"BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE"}
SWEEP_FLOORS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]


def norm(s):
    return (s or "").strip().lower()


def is_committed(answer) -> bool:
    return norm(answer) not in ABST


# ----------------------------------------------------------------------------
# Record building
# ----------------------------------------------------------------------------

def ro(db=None):
    conn = sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_records(conn) -> list[dict]:
    """One record per phase2_final row, with the trail signals the analysis
    needs: the committed answer and its confidences, the best pre-abstention
    candidate (for the threshold sweep), the route, and ground truth.
    """
    catalogue_pairs = {
        r["pair_run_id"] for r in conn.execute(
            "SELECT DISTINCT pair_run_id FROM phase2_researcher_runs "
            "WHERE notes LIKE '%catalogue_computed%'")
    }
    qmeta = {
        r["question_id"]: (r["answer_shape"] or "binary")
        for r in conn.execute("SELECT question_id, answer_shape FROM questions")
    }
    gt = {
        (r["question_id"], r["country_code"]): (r["response"], r["dimension"])
        for r in conn.execute(
            "SELECT question_id, country_code, response, dimension FROM ground_truth")
    }

    res_by_pair = defaultdict(list)
    for r in conn.execute(
        "SELECT pair_run_id, retry_count, id, answer, answer_confidence, "
        "retrieval_confidence FROM phase2_researcher_runs"):
        res_by_pair[r["pair_run_id"]].append(r)
    adj_by_pair = {}
    for r in conn.execute(
        "SELECT pair_run_id, adjudicator_answer, adjudicator_confidence "
        "FROM phase2_adjudications"):
        adj_by_pair[r["pair_run_id"]] = r
    ver_last_verdict = {}
    for r in conn.execute(
        "SELECT pair_run_id, retry_count, id, verdict FROM phase2_verifier_runs "
        "ORDER BY retry_count, id"):
        ver_last_verdict[r["pair_run_id"]] = r["verdict"]  # last wins

    recs = []
    for f in conn.execute("SELECT * FROM phase2_final"):
        pid = f["pair_run_id"]
        qid, cc = f["question_id"], f["country_code"]
        gold, dim = gt.get((qid, cc), (None, None))
        if not norm(gold):
            continue  # no ground truth: nothing to score
        shape = qmeta.get(qid, "binary")
        committed = is_committed(f["final_answer"])

        # candidate the floor would judge: committed answer, else adjudicator,
        # else the latest researcher run that carried a real label.
        if committed:
            cand_ans = f["final_answer"]
            cand_conf = f["final_answer_confidence"]
            cand_ret = f["final_retrieval_confidence"]
        else:
            cand_ans = cand_conf = cand_ret = None
            adj = adj_by_pair.get(pid)
            if adj and is_committed(adj["adjudicator_answer"]):
                cand_ans = adj["adjudicator_answer"]
                cand_conf = adj["adjudicator_confidence"]
            else:
                runs = sorted(res_by_pair.get(pid, []),
                              key=lambda r: (r["retry_count"] or 0, r["id"]))
                for r in reversed(runs):
                    if is_committed(r["answer"]):
                        cand_ans = r["answer"]
                        cand_conf = r["answer_confidence"]
                        cand_ret = r["retrieval_confidence"]
                        break

        recs.append(dict(
            pair_run_id=pid, qid=qid, cc=cc, shape=shape, dim=dim,
            experiment_id=f["experiment_id"], final_id=f["id"],
            gold=gold, gold_n=norm(gold),
            is_catalogue=pid in catalogue_pairs,
            committed=committed,
            final_answer=f["final_answer"],
            final_conf=f["final_answer_confidence"],
            final_ret=f["final_retrieval_confidence"],
            correct=is_correct(qid, f["final_answer"], gold) if committed else False,
            cand_ans=cand_ans, cand_conf=cand_conf, cand_ret=cand_ret,
            cand_correct=is_correct(qid, cand_ans, gold) if cand_ans else False,
            is_negative_gold=norm(gold) == "no",
            last_verifier_verdict=ver_last_verdict.get(pid),
        ))
    return recs


def dedup_latest(recs: list[dict]) -> list[dict]:
    """Keep the latest phase2_final row per (question, country)."""
    best = {}
    for r in recs:
        k = (r["qid"], r["cc"])
        if k not in best or r["final_id"] > best[k]["final_id"]:
            best[k] = r
    return list(best.values())


def population(recs, *, scope="pooled", shape=None, countries=None,
              committed_only=True, binary_yesno=True):
    out = list(recs)
    if scope == "production":
        out = [r for r in out if r["experiment_id"] is None]
        out = dedup_latest(out)
    if countries is not None:
        out = [r for r in out if r["cc"] in countries]
    if shape is not None:
        out = [r for r in out if r["shape"] == shape]
    if binary_yesno:
        out = [r for r in out if r["shape"] == "binary" and r["gold_n"] in ("yes", "no")]
    if committed_only:
        out = [r for r in out if r["committed"]]
    return out


# ----------------------------------------------------------------------------
# A. Calibration
# ----------------------------------------------------------------------------

def calibration(pop, conf_key="final_conf", correct_key="correct", nbins=10):
    """Reliability table over equal-width bins, plus ECE, MCE and Brier."""
    pts = [(r[conf_key], int(r[correct_key])) for r in pop if r[conf_key] is not None]
    n = len(pts)
    if not n:
        return None
    bins = []
    ece = mce = 0.0
    for b in range(nbins):
        lo, hi = b / nbins, (b + 1) / nbins
        sel = [(c, y) for c, y in pts if (lo <= c < hi or (b == nbins - 1 and c == 1.0))]
        if not sel:
            continue
        nb = len(sel)
        acc = sum(y for _, y in sel) / nb
        conf = sum(c for c, _ in sel) / nb
        gap = abs(acc - conf)
        ece += (nb / n) * gap
        mce = max(mce, gap)
        lo_ci, hi_ci = stats.wilson_interval(sum(y for _, y in sel), nb)
        bins.append(dict(lo=lo, hi=hi, n=nb, conf=conf, acc=acc,
                         gap=acc - conf, ci=(lo_ci, hi_ci)))
    brier = sum((c - y) ** 2 for c, y in pts) / n
    return dict(n=n, ece=ece, mce=mce, brier=brier, bins=bins)


def calib_by_commit_band(pop, conf_key="final_conf", correct_key="correct"):
    """Accuracy in the project's natural commit bands (matches the brief)."""
    bands = [(0.0, 0.50), (0.50, 0.65), (0.65, 0.80), (0.80, 0.90), (0.90, 1.0001)]
    rows = []
    for lo, hi in bands:
        sel = [r for r in pop if r[conf_key] is not None and lo <= r[conf_key] < hi]
        if not sel:
            continue
        c = sum(int(r[correct_key]) for r in sel)
        lo_ci, hi_ci = stats.wilson_interval(c, len(sel))
        rows.append(dict(band=f"[{lo:.2f},{min(hi,1.0):.2f})", n=len(sel),
                         acc=c / len(sel), ci=(lo_ci, hi_ci)))
    return rows


# ----------------------------------------------------------------------------
# B. Threshold sweep (candidate confidence is the gate)
# ----------------------------------------------------------------------------

def threshold_sweep(pop_with_candidates, floors=SWEEP_FLOORS):
    """For each floor t, COMMIT a pair iff its candidate confidence >= t.

    pop_with_candidates: records with cand_ans/cand_conf/cand_correct, both
    committed and abstained-with-candidate pairs. N is every pair with a real
    ground-truth answer (the denominator for recall/coverage). The verifier
    verdict is held fixed at what it actually was; see `verifier_optimism`.
    """
    cand = [r for r in pop_with_candidates if r["cand_ans"] is not None
            and r["cand_conf"] is not None]
    N = len(pop_with_candidates)  # all gold-answerable pairs
    neg_total = sum(1 for r in pop_with_candidates if r["is_negative_gold"])
    rows = []
    for t in floors:
        committed = [r for r in cand if r["cand_conf"] >= t]
        k = len(committed)
        correct = sum(1 for r in committed if r["cand_correct"])
        neg_committed = [r for r in committed if r["is_negative_gold"]]
        neg_fp = sum(1 for r in neg_committed if not r["cand_correct"])
        prec = correct / k if k else None
        prec_ci = stats.wilson_interval(correct, k) if k else (None, None)
        rows.append(dict(
            t=t, committed=k, correct=correct,
            precision=prec, precision_ci=prec_ci,
            coverage=k / N if N else None,
            recall=correct / N if N else None,           # correct over all gold pairs
            neg_committed=len(neg_committed), neg_fp=neg_fp,
            neg_fp_rate=(neg_fp / len(neg_committed)) if neg_committed else None,
            neg_fp_rate_all=(neg_fp / neg_total) if neg_total else None,
        ))
    return dict(N=N, neg_total=neg_total, rows=rows)


def verifier_optimism(pop_with_candidates):
    """How much of the downward sweep is optimistic: of the abstained pairs
    that carry a candidate, how many had the verifier actually reject them
    (so lowering the floor would NOT have recovered them in reality)."""
    abst = [r for r in pop_with_candidates if not r["committed"] and r["cand_ans"]]
    rejected = sum(1 for r in abst if r["last_verifier_verdict"] == "fail")
    passed = sum(1 for r in abst if r["last_verifier_verdict"] == "pass")
    return dict(abstained_with_candidate=len(abst),
                verifier_rejected=rejected, verifier_passed=passed,
                other=len(abst) - rejected - passed)


# ----------------------------------------------------------------------------
# C. Two-confidence predictive power
# ----------------------------------------------------------------------------

def auroc(scores, labels):
    """Area under ROC = P(score of a positive > score of a negative), ties .5.
    Mann-Whitney U via average ranks."""
    pairs = sorted(zip(scores, labels))
    n = len(pairs)
    npos = sum(labels)
    nneg = n - npos
    if npos == 0 or nneg == 0:
        return None
    # average ranks
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and pairs[j][0] == pairs[i][0]:
            j += 1
        avg = (i + 1 + j) / 2.0  # 1-based average rank for ties [i, j)
        for k in range(i, j):
            ranks[k] = avg
        i = j
    sum_pos = sum(ranks[k] for k in range(n) if pairs[k][1] == 1)
    return (sum_pos - npos * (npos + 1) / 2.0) / (npos * nneg)


def auroc_ci(scores, labels):
    """AUROC with a Hanley & McNeil (1982) standard-error 95% interval."""
    auc = auroc(scores, labels)
    if auc is None:
        return None
    npos = sum(labels)
    nneg = len(labels) - npos
    q1 = auc / (2 - auc)
    q2 = 2 * auc * auc / (1 + auc)
    var = (auc * (1 - auc) + (npos - 1) * (q1 - auc * auc)
           + (nneg - 1) * (q2 - auc * auc)) / (npos * nneg)
    se = math.sqrt(max(var, 0.0))
    return dict(auc=auc, lo=max(0.0, auc - 1.96 * se), hi=min(1.0, auc + 1.96 * se), se=se)


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def predictive_power(pop):
    rows = [r for r in pop if r["final_conf"] is not None and r["final_ret"] is not None]
    y = [int(r["correct"]) for r in rows]
    ans = [r["final_conf"] for r in rows]
    ret = [r["final_ret"] for r in rows]
    combo = [(a + b) / 2 for a, b in zip(ans, ret)]
    out = dict(
        n=len(rows),
        auc_answer=auroc_ci(ans, y),
        auc_retrieval=auroc_ci(ret, y),
        auc_mean=auroc(combo, y),
        corr_answer_retrieval=pearson(ans, ret),
        base_accuracy=sum(y) / len(y) if y else None,
    )
    # incremental value of retrieval within the two modal answer_confidence values
    incr = {}
    for v in (0.65, 0.72):
        sub = [r for r in rows if abs(r["final_conf"] - v) < 1e-9]
        if len(sub) >= 20:
            ys = [int(r["correct"]) for r in sub]
            rs = [r["final_ret"] for r in sub]
            incr[v] = dict(n=len(sub), acc=sum(ys) / len(ys),
                           auc_retrieval=auroc(rs, ys))
    out["retrieval_within_fixed_answer_conf"] = incr

    # Why the single number cannot work: the confidence tracks the *label*, not
    # correctness. Mean confidence is higher for `yes` commits than `no` commits;
    # so on positive golds (correct=yes) confidence is pro-predictive, on negative
    # golds (correct=no) it is anti-predictive, and the two cancel to AUC ~ 0.5.
    yes_conf = [r["final_conf"] for r in rows if norm(r["final_answer"]) == "yes"]
    no_conf = [r["final_conf"] for r in rows if norm(r["final_answer"]) == "no"]
    out["mean_conf_pred_yes"] = sum(yes_conf) / len(yes_conf) if yes_conf else None
    out["mean_conf_pred_no"] = sum(no_conf) / len(no_conf) if no_conf else None
    pos = [r for r in rows if r["gold_n"].startswith("yes")]
    neg = [r for r in rows if r["gold_n"] == "no"]
    out["auc_within_positive_gold"] = auroc([r["final_conf"] for r in pos],
                                            [int(r["correct"]) for r in pos])
    out["auc_within_negative_gold"] = auroc([r["final_conf"] for r in neg],
                                            [int(r["correct"]) for r in neg])
    return out


# ----------------------------------------------------------------------------
# Theory 1: are the false positives the swarm's MOST confident commits?
# ----------------------------------------------------------------------------

def theory1(pop):
    """Compare answer_confidence of correct vs false-positive vs false-negative
    binary commits, and the negative-gold FP rate per (non-cumulative)
    confidence band. If FPs are at least as confident as correct answers, the
    confidence is not flagging them: support for the fluency-not-evidence theory.
    """
    def stat(sel):
        v = [r["final_conf"] for r in sel if r["final_conf"] is not None]
        return dict(n=len(v),
                    mean=(sum(v) / len(v) if v else None),
                    median=(statistics.median(v) if v else None))
    correct = [r for r in pop if r["correct"]]
    fp = [r for r in pop if norm(r["final_answer"]) == "yes" and r["gold_n"] == "no"]
    fn = [r for r in pop if norm(r["final_answer"]) == "no" and r["gold_n"].startswith("yes")]
    bands = [(0.5, 0.65), (0.65, 0.80), (0.80, 0.90), (0.90, 1.0001)]
    neg = [r for r in pop if r["is_negative_gold"]]
    per_band = []
    for lo, hi in bands:
        b = [r for r in neg if r["final_conf"] is not None and lo <= r["final_conf"] < hi]
        if not b:
            continue
        fpn = sum(1 for r in b if norm(r["final_answer"]) == "yes")
        ci = stats.wilson_interval(fpn, len(b))
        per_band.append(dict(band=f"[{lo:.2f},{min(hi,1.0):.2f})", n=len(b),
                             fp_rate=fpn / len(b), ci=ci))
    return dict(correct=stat(correct), false_positive=stat(fp),
                false_negative=stat(fn), neg_fp_per_band=per_band)


# ----------------------------------------------------------------------------
# Reliability-diagram SVG (manuscript drop-in)
# ----------------------------------------------------------------------------

def reliability_svg(series, path):
    """series: list of (label, colour, calibration_dict). Plots mean_conf (x)
    against accuracy (y) per bin, point radius ~ sqrt(n), with the y=x line."""
    W = H = 460
    m = 60  # margin
    span = W - 2 * m

    def X(v):
        return m + v * span

    def Y(v):
        return H - m - v * span

    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
             f'font-family="sans-serif" font-size="12">']
    parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="white"/>')
    # axes
    parts.append(f'<line x1="{m}" y1="{H-m}" x2="{W-m}" y2="{H-m}" stroke="#333"/>')
    parts.append(f'<line x1="{m}" y1="{m}" x2="{m}" y2="{H-m}" stroke="#333"/>')
    # gridlines + ticks
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        parts.append(f'<line x1="{X(t):.0f}" y1="{H-m}" x2="{X(t):.0f}" y2="{H-m+5}" stroke="#333"/>')
        parts.append(f'<text x="{X(t):.0f}" y="{H-m+18}" text-anchor="middle">{t:.2f}</text>')
        parts.append(f'<line x1="{m-5}" y1="{Y(t):.0f}" x2="{m}" y2="{Y(t):.0f}" stroke="#333"/>')
        parts.append(f'<text x="{m-10}" y="{Y(t)+4:.0f}" text-anchor="end">{t:.2f}</text>')
    # perfect-calibration diagonal
    parts.append(f'<line x1="{X(0)}" y1="{Y(0)}" x2="{X(1)}" y2="{Y(1)}" '
                 f'stroke="#999" stroke-dasharray="5 4"/>')
    parts.append(f'<text x="{X(0.72)}" y="{Y(0.78):.0f}" fill="#999" '
                 f'transform="rotate(-45 {X(0.72):.0f} {Y(0.78):.0f})">perfect calibration</text>')
    # axis labels
    parts.append(f'<text x="{W/2:.0f}" y="{H-12}" text-anchor="middle" '
                 f'font-size="13">stated answer_confidence (bin mean)</text>')
    parts.append(f'<text x="18" y="{H/2:.0f}" text-anchor="middle" font-size="13" '
                 f'transform="rotate(-90 18 {H/2:.0f})">empirical accuracy</text>')
    # series
    legend_y = m + 4
    for label, colour, cal in series:
        if not cal:
            continue
        pts = []
        for b in cal["bins"]:
            r = 3 + math.sqrt(b["n"])
            cx, cy = X(b["conf"]), Y(b["acc"])
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
                         f'fill="{colour}" fill-opacity="0.45" stroke="{colour}"/>')
            pts.append(f"{cx:.1f},{cy:.1f}")
        parts.append(f'<polyline points="{" ".join(pts)}" fill="none" '
                     f'stroke="{colour}" stroke-width="1.5"/>')
        parts.append(f'<rect x="{W-m-150}" y="{legend_y-9}" width="12" height="12" '
                     f'fill="{colour}" fill-opacity="0.45" stroke="{colour}"/>')
        parts.append(f'<text x="{W-m-134}" y="{legend_y+1}">{label} '
                     f'(ECE {cal["ece"]:.2f})</text>')
        legend_y += 18
    parts.append('</svg>')
    Path(path).write_text("\n".join(parts))


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------

def _p(s=""):
    print(s)


def report(db=None):
    conn = ro(db)
    recs = load_records(conn)
    n_final = conn.execute("SELECT COUNT(*) FROM phase2_final").fetchone()[0]
    conn.close()

    out = {}

    _p("=" * 80)
    _p("CONFIDENCE DEEP DIVE  —  read-only replay over phase2_final")
    _p(f"DB: {db or DB}  ({n_final} phase2_final rows)")
    _p("=" * 80)

    # ---- headline reproduction + population decomposition ------------------
    _p("\n## Headline: binary committed answers, by population")
    _p(f"  {'population':28s} {'n':>5s} {'acc':>6s} {'FP':>5s} {'FN':>5s} "
       f"{'neg':>5s} {'negFP%':>7s}")
    pops = {
        "pooled (all rows)": population(recs, scope="pooled"),
        "pooled, dev only": population(recs, scope="pooled", countries=DEV),
        "production (dedup)": population(recs, scope="production"),
        "production, dev": population(recs, scope="production", countries=DEV),
        "NL only (all arms)": population(recs, scope="pooled", countries={"NL"}),
        "MT only (all arms)": population(recs, scope="pooled", countries={"MT"}),
        "held-out (diagnostic)": population(recs, scope="pooled", countries=HELD_OUT),
    }
    out["headline"] = {}
    for label, pop in pops.items():
        n = len(pop)
        if not n:
            continue
        correct = sum(int(r["correct"]) for r in pop)
        fp = sum(1 for r in pop if norm(r["final_answer"]) == "yes" and r["gold_n"] == "no")
        fn = sum(1 for r in pop if norm(r["final_answer"]) == "no" and r["gold_n"].startswith("yes"))
        neg = sum(1 for r in pop if r["is_negative_gold"])
        negfp = sum(1 for r in pop if r["is_negative_gold"] and norm(r["final_answer"]) == "yes")
        _p(f"  {label:28s} {n:5d} {correct/n:6.1%} {fp:5d} {fn:5d} {neg:5d} "
           f"{(negfp/neg if neg else float('nan')):7.0%}")
        out["headline"][label] = dict(n=n, acc=correct / n, fp=fp, fn=fn,
                                      neg=neg, neg_fp=negfp)

    # ---- A. calibration ----------------------------------------------------
    _p("\n" + "=" * 80)
    _p("A. CALIBRATION of answer_confidence (committed binary answers)")
    _p("=" * 80)
    out["calibration"] = {}
    for label, pop in [("pooled", pops["pooled (all rows)"]),
                       ("pooled-dev", pops["pooled, dev only"]),
                       ("production", pops["production (dedup)"]),
                       ("NL-only", pops["NL only (all arms)"])]:
        cb = calib_by_commit_band(pop)
        cal = calibration(pop)
        if not cal:
            continue
        _p(f"\n--- {label} (n={cal['n']}) "
           f"ECE={cal['ece']:.3f}  MCE={cal['mce']:.3f}  Brier={cal['brier']:.3f} ---")
        _p("  commit band   n   acc    [95% CI]")
        for row in cb:
            lo, hi = row["ci"]
            _p(f"  {row['band']:12s} {row['n']:4d} {row['acc']:5.0%}  "
               f"[{lo:.0%},{hi:.0%}]")
        out["calibration"][label] = dict(
            ece=cal["ece"], mce=cal["mce"], brier=cal["brier"], n=cal["n"],
            commit_bands=[dict(band=r["band"], n=r["n"], acc=r["acc"]) for r in cb])

    # reliability (fine bins) for pooled
    cal = calibration(pops["pooled (all rows)"])
    _p("\n--- pooled reliability diagram (0.1 bins): perfect = acc==conf ---")
    _p("  bin          n   mean_conf   acc    gap")
    for b in cal["bins"]:
        _p(f"  [{b['lo']:.1f},{b['hi']:.1f})  {b['n']:4d}   {b['conf']:.2f}     "
           f"{b['acc']:.2f}  {b['gap']:+.2f}")

    # ---- catalogue theory --------------------------------------------------
    _p("\n" + "=" * 80)
    _p("A'. Catalogue-route theory: is the high-confidence band 'largely catalogue'?")
    _p("=" * 80)
    all_committed = [r for r in recs if r["committed"]]
    cat_all = [r for r in all_committed if r["is_catalogue"]]
    hi_band = [r for r in all_committed if r["final_conf"] is not None and r["final_conf"] >= 0.9]
    hi_cat = [r for r in hi_band if r["is_catalogue"]]
    bin_cat = [r for r in pops["pooled (all rows)"] if r["is_catalogue"]]
    _p(f"  catalogue-routed committed rows (all shapes): {len(cat_all)}")
    _p(f"  their answer_confidence values: "
       f"{sorted({round(r['final_conf'],2) for r in cat_all if r['final_conf'] is not None})}")
    _p(f"  conf>=0.9 band (all shapes): n={len(hi_band)}, of which catalogue={len(hi_cat)} "
       f"({len(hi_cat)/len(hi_band):.0%})")
    _p(f"  catalogue rows inside the BINARY population: {len(bin_cat)}")
    _p(f"  => the 0.9-1.0 binary band cannot be a catalogue artefact (0 catalogue pairs are binary).")
    out["catalogue_theory"] = dict(
        catalogue_committed=len(cat_all), hi_band=len(hi_band),
        hi_band_catalogue=len(hi_cat), binary_catalogue=len(bin_cat),
        catalogue_confs=sorted({round(r["final_conf"], 2) for r in cat_all if r["final_conf"] is not None}))

    # ---- Theory 1: are FPs the most confident commits? ---------------------
    _p("\n" + "=" * 80)
    _p("A''. Theory 1: do false positives carry HIGHER confidence than correct answers?")
    _p("=" * 80)
    out["theory1"] = {}
    for label, pop in [("pooled-dev", pops["pooled, dev only"]),
                       ("NL-only", pops["NL only (all arms)"])]:
        t1 = theory1(pop)
        _p(f"\n--- {label} mean/median answer_confidence by outcome ---")
        for k in ("correct", "false_positive", "false_negative"):
            s = t1[k]
            mn = "n/a" if s["mean"] is None else f"{s['mean']:.3f}"
            md = "n/a" if s["median"] is None else f"{s['median']:.2f}"
            _p(f"  {k:16s} n={s['n']:4d}  mean={mn}  median={md}")
        _p("  negative-gold FP rate per confidence band (non-cumulative):")
        for b in t1["neg_fp_per_band"]:
            _p(f"    {b['band']:12s} n={b['n']:3d}  FP%={b['fp_rate']:.0%}  "
               f"[{b['ci'][0]:.0%},{b['ci'][1]:.0%}]")
        out["theory1"][label] = t1

    # reliability-diagram SVG (pooled vs production)
    svg_path = REPO / "evaluation" / "results" / "reliability_diagram.svg"
    svg_path.parent.mkdir(exist_ok=True)
    reliability_svg([
        ("pooled (all arms)", "#c0392b", calibration(pops["pooled (all rows)"])),
        ("production", "#2471a3", calibration(pops["production (dedup)"])),
    ], svg_path)
    _p(f"\nWrote reliability diagram: {svg_path}")

    # ---- B. threshold sweep ------------------------------------------------
    _p("\n" + "=" * 80)
    _p("B. THRESHOLD SWEEP on candidate confidence (commit iff cand_conf >= t)")
    _p("=" * 80)
    out["threshold_sweep"] = {}
    sweep_pops = {
        "pooled-dev binary": population(recs, scope="pooled", countries=DEV, committed_only=False),
        "NL binary": population(recs, scope="pooled", countries={"NL"}, committed_only=False),
        "production-dev binary": population(recs, scope="production", countries=DEV, committed_only=False),
    }
    for label, pop in sweep_pops.items():
        sw = threshold_sweep(pop)
        vo = verifier_optimism(pop)
        _p(f"\n--- {label}  (N={sw['N']} gold pairs, {sw['neg_total']} negative golds) ---")
        _p(f"    downward-sweep caveat: {vo['abstained_with_candidate']} abstained pairs carry a "
           f"candidate; {vo['verifier_rejected']} were verifier-rejected (sweep over-credits these).")
        _p(f"  {'floor':>6s} {'commit':>7s} {'cover':>6s} {'prec':>6s} {'[95%CI]':>13s} "
           f"{'recall':>7s} {'negFP':>6s} {'negFP%':>7s}")
        for r in sw["rows"]:
            pc = "" if r["precision"] is None else f"{r['precision']:.0%}"
            ci = "" if r["precision_ci"][0] is None else f"[{r['precision_ci'][0]:.0%},{r['precision_ci'][1]:.0%}]"
            nf = "" if r["neg_fp_rate"] is None else f"{r['neg_fp_rate']:.0%}"
            _p(f"  {r['t']:6.2f} {r['committed']:7d} {r['coverage']:6.0%} {pc:>6s} {ci:>13s} "
               f"{r['recall']:7.0%} {r['neg_fp']:6d} {nf:>7s}")
        out["threshold_sweep"][label] = dict(
            N=sw["N"], neg_total=sw["neg_total"], optimism=vo,
            rows=[{k: v for k, v in r.items() if k != "precision_ci"} for r in sw["rows"]])

    # per-shape sweep on pooled-dev (all shapes, candidate-based, exact-match correctness)
    _p("\n--- B'. pooled-dev per-shape coverage/precision at t=0.65 vs t=0.80 ---")
    out["per_shape"] = {}
    for shp in ("binary", "percentage_band", "ordinal_magnitude", "count_band", "categorical"):
        pop = [r for r in recs if r["shape"] == shp and r["cc"] in DEV and norm(r["gold"]) not in ("", "none")]
        if len(pop) < 10:
            continue
        sw = threshold_sweep(pop, floors=[0.65, 0.80])
        r65, r80 = sw["rows"][0], sw["rows"][1]
        _p(f"  {shp:18s} N={sw['N']:4d}  "
           f"@.65 cov={r65['coverage']:.0%} prec={(r65['precision'] or 0):.0%}  "
           f"@.80 cov={r80['coverage']:.0%} prec={(r80['precision'] or 0):.0%}")
        out["per_shape"][shp] = dict(N=sw["N"], at_065=r65, at_080=r80)

    # ---- C. predictive power ----------------------------------------------
    _p("\n" + "=" * 80)
    _p("C. Do retrieval_confidence and answer_confidence each predict correctness?")
    _p("=" * 80)
    out["predictive_power"] = {}
    for label, pop in [("pooled binary", pops["pooled (all rows)"]),
                       ("pooled-dev binary", pops["pooled, dev only"]),
                       ("NL binary", pops["NL only (all arms)"])]:
        pp = predictive_power(pop)
        aa, ar = pp["auc_answer"], pp["auc_retrieval"]
        _p(f"\n--- {label} (n={pp['n']}, base acc={pp['base_accuracy']:.0%}) ---")
        _p(f"  AUROC answer_confidence    = {aa['auc']:.3f} [{aa['lo']:.3f},{aa['hi']:.3f}]")
        _p(f"  AUROC retrieval_confidence = {ar['auc']:.3f} [{ar['lo']:.3f},{ar['hi']:.3f}]")
        _p(f"  AUROC mean of the two      = {pp['auc_mean']:.3f}")
        _p(f"  corr(answer, retrieval)    = {pp['corr_answer_retrieval']:.3f}")
        _p(f"  mean conf | pred=yes = {pp['mean_conf_pred_yes']:.3f}   "
           f"| pred=no = {(pp['mean_conf_pred_no'] or float('nan')):.3f}")
        _p(f"  AUROC(answer) within positive golds = {pp['auc_within_positive_gold']}  "
           f"within negative golds = {pp['auc_within_negative_gold']}")
        for v, d in pp["retrieval_within_fixed_answer_conf"].items():
            _p(f"  at answer_conf={v}: n={d['n']} acc={d['acc']:.0%} "
               f"AUROC(retrieval)={d['auc_retrieval']}")
        out["predictive_power"][label] = pp

    if "--json" in sys.argv:
        RESULTS.parent.mkdir(exist_ok=True)
        RESULTS.write_text(json.dumps(out, indent=2, default=str))
        _p(f"\nWrote {RESULTS}")
    _p("\n" + "=" * 80)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="dump JSON to results/")
    ap.add_argument("--db", default=None,
                    help="path to odmi.db (default: repo data/odmi.db; pass the "
                         "canonical live DB when running from a worktree)")
    args = ap.parse_args()
    report(db=args.db)
