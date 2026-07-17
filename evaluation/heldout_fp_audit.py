#!/usr/bin/env python3
"""Held-out false-positive audit: are the swarm's committed binary false positives
on the EXP-36 held-out countries genuine swarm errors, definitional gaps, or
defensible answers against a self-reported / stale gold?

This generalises evaluation/nl_fp_audit.py from the Netherlands (a dev country)
to the eight D47 held-out countries that carry the frozen EXP-36 headline
(BA MK ME BG FI HR SE BE). The NL audit adjudicated 22 dev false positives and
found none where the swarm was right and ODMI wrong; every one traced to
outdated or tangential evidence. This asks whether that holds on the actual
held-out results, and quantifies how much of the EXP-36 commit-accuracy lower
bound is depressed by stale or self-reported golds rather than true swarm error
(the D22 staleness band, flagged open in the EXP-36 writeup).

Scope note (audit trail): the D47 held-out set is normally off-limits to
experiments so the headline generalisation stays honest. This is not a config
experiment. It runs no swarm, changes no knob, and tunes nothing; it is a
post-hoc classification of already-frozen disagreements, run at Benjy's explicit
direction, purely for reporting. EXP-34 was the last config-changing freeze gate.

Method, identical to the NL audit so the two are directly comparable:
- For each held-out (country, question) with a committed binary false positive
  (swarm `yes`, gold `no`), take the most recent such pair and its FROZEN stored
  evidence (the researcher's quote and search snippets).
- Pass 1 (charitable): Opus is shown the gold and ODMI's explanation and assigns
  genuine_error / definitional_gap / defensible_or_stale_gold. The rubric and
  schema are imported verbatim from nl_fp_audit.
- Pass 2 (adversarial): Opus is told to act as an advocate hired to defend the
  swarm's 'yes', then to say honestly whether that defence holds
  (swarm_over_read / ambiguous / gold_wrong). Rubric imported from
  nl_fp_audit_adversarial.
- The joint deliverable per FP: was the swarm actually right (adversarial
  gold_wrong) or the gold stale/self-reported (charitable
  defensible_or_stale_gold)? Stratified by country, ODMI dimension, and ODMI
  decision.

No web search, no swarm run, so the evaluation-cycle deny-list is not engaged.

Safety: importing nl_fp_audit forces the proxy base URL from the main .env and
refuses to run against the real Anthropic API. The canonical DB is read
read-only; the per-country max phase2_final id audited is pinned in the output.

  uv run python evaluation/heldout_fp_audit.py --limit 1        # reachability, both passes, 1 FP
  uv run python evaluation/heldout_fp_audit.py --pass charitable
  uv run python evaluation/heldout_fp_audit.py                  # full: both passes, all held-out FPs
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

# Importing nl_fp_audit runs its env guard (forces the local proxy, refuses the
# real API) and gives us the exact pass-1 rubric. nl_fp_audit_adversarial gives
# the exact pass-2 rubric. Keeping a single source of truth for both prompts is
# what makes the held-out numbers comparable to the NL ones.
from evaluation.nl_fp_audit import (  # noqa: E402
    ABST, Audit, SYS as SYS_CHARITABLE, build_user as build_user_charitable, norm,
)
from evaluation.nl_fp_audit_adversarial import (  # noqa: E402
    Defence, SYS as SYS_ADVERSARIAL, build_user as build_user_adversarial,
)
from agents.tools.llm import call_for_structured  # noqa: E402

CANONICAL_DB = "/Users/benjyb/Desktop/MscProject/data/odmi.db"
MODEL = "claude-opus-4-6"  # match the NL audit judge so a difference is about the countries, not the model
HELD_OUT = ("BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE")  # D47 held-out set
RESULTS_DIR = Path(__file__).resolve().parent / "results"

CHARITABLE_VERDICTS = ("genuine_error", "definitional_gap", "defensible_or_stale_gold")
ADVERSARIAL_VERDICTS = ("swarm_over_read", "ambiguous", "gold_wrong")


def load_fps(con, countries):
    """Latest committed binary false positive (swarm yes, gold no) per
    (country, question) across `countries`. Returns the FP rows plus a per-country
    max phase2_final id, to pin the snapshot. Mirrors nl_fp_audit.load_fps but
    parametrised by country and carrying dimension + country name for stratification.
    """
    placeholders = ",".join("?" * len(countries))
    shape = {r["question_id"]: (r["answer_shape"] or "binary")
             for r in con.execute("SELECT question_id, answer_shape FROM questions")}
    qtext = {r["question_id"]: r["question_text"]
             for r in con.execute("SELECT question_id, question_text FROM questions")}
    qdim = {r["question_id"]: r["dimension"]
            for r in con.execute("SELECT question_id, dimension FROM questions")}
    # gold keyed by (country, question)
    gt = {(r["country_code"], r["question_id"]): r
          for r in con.execute(
              f"SELECT * FROM ground_truth WHERE country_code IN ({placeholders})", countries)}
    cname = {r["country_code"]: r["country_name"]
             for r in con.execute(
                 f"SELECT DISTINCT country_code, country_name FROM ground_truth "
                 f"WHERE country_code IN ({placeholders})", countries)}
    # latest committed (non-abstained) researcher run per pair: snippets + quote
    res = {}
    for r in con.execute(
        f"SELECT pair_run_id, retry_count, id, answer, evidence_quote, search_snippets, country_code "
        f"FROM phase2_researcher_runs WHERE country_code IN ({placeholders}) "
        f"ORDER BY retry_count, id", countries):
        if norm(r["answer"]) not in ABST:
            res[r["pair_run_id"]] = r

    best, max_id = {}, defaultdict(int)
    for f in con.execute(
        f"SELECT * FROM phase2_final WHERE country_code IN ({placeholders})", countries):
        max_id[f["country_code"]] = max(max_id[f["country_code"]], f["id"])
        if shape.get(f["question_id"]) != "binary":
            continue
        g = gt.get((f["country_code"], f["question_id"]))
        if not g or norm(g["response"]) != "no" or norm(f["final_answer"]) != "yes":
            continue
        k = (f["country_code"], f["question_id"])
        if k not in best or f["id"] > best[k]["id"]:
            best[k] = f

    out = []
    for (cc, q) in sorted(best):
        f = best[(cc, q)]
        rr = res.get(f["pair_run_id"])
        snips = []
        if rr and rr["search_snippets"]:
            try:
                snips = [d.get("snippet", "") if isinstance(d, dict) else str(d)
                         for d in json.loads(rr["search_snippets"])]
                snips = [s for s in snips if s]
            except Exception:
                snips = []
        g = gt[(cc, q)]
        out.append(dict(
            country=cc, country_name=cname.get(cc, cc), qid=q, final_id=f["id"],
            pair_run_id=f["pair_run_id"], q_text=qtext.get(q, q), dimension=qdim.get(q, ""),
            gold=g["response"], decision=g["decision"], explanation=g["explanation"] or "",
            answer_confidence=f["final_answer_confidence"],
            quote=(rr["evidence_quote"] if rr else "") or "", snippets=snips,
            has_evidence=bool(snips)))
    return out, dict(max_id)


def audit_charitable(c, model):
    out, _ = call_for_structured(
        system=SYS_CHARITABLE,
        user_message=build_user_charitable(c["q_text"], c["country_name"], c["quote"],
                                           c["snippets"], c["gold"], c["explanation"]),
        output_schema=Audit, model=model, max_tokens=500, temperature=0.0,
        condition_label="heldout_fp_audit",
        usage_context=f"heldout_fp_audit:{c['qid']}:{c['country']}")
    return dict(verdict=out.verdict,
                swarm_evidence_supports_yes=out.swarm_evidence_supports_yes,
                gold_is_self_report=out.gold_is_self_report, reason=out.reason)


def audit_adversarial(c, model):
    out, _ = call_for_structured(
        system=SYS_ADVERSARIAL,
        user_message=build_user_adversarial(c["q_text"], c["country_name"], c["quote"], c["snippets"]),
        output_schema=Defence, model=model, max_tokens=1500, temperature=0.0,
        condition_label="heldout_fp_audit_adversarial",
        usage_context=f"heldout_fp_adv:{c['qid']}:{c['country']}")
    return dict(holds=out.holds, reason=out.reason, best_case=out.best_case_for_swarm)


def summarise(rows, do_char, do_adv):
    ok = [r for r in rows if "error" not in r]
    lines = [f"Held-out FP audit: {len(ok)}/{len(rows)} adjudicated "
             f"({len(rows) - len(ok)} errored)."]
    if not ok:
        return "\n".join(lines)

    if do_char:
        ctr = Counter(r["charitable"]["verdict"] for r in ok if "charitable" in r)
        n = sum(ctr.values())
        lines.append("\nPass 1 (charitable) verdicts:")
        for v in CHARITABLE_VERDICTS:
            lines.append(f"  {v:26s} {ctr.get(v, 0):3d}  ({ctr.get(v, 0)/n:.0%})" if n else f"  {v:26s} 0")
        stale = ctr.get("defensible_or_stale_gold", 0)
        err = ctr.get("genuine_error", 0)
        lines.append(f"  -> genuine swarm error: {err}/{n} = {err/n:.0%}" if n else "")
        lines.append(f"  -> defensible/stale gold (swarm not clearly wrong): {stale}/{n} = {stale/n:.0%}" if n else "")

    if do_adv:
        ctr = Counter(r["adversarial"]["holds"] for r in ok if "adversarial" in r)
        n = sum(ctr.values())
        lines.append("\nPass 2 (adversarial advocate) verdicts:")
        for v in ADVERSARIAL_VERDICTS:
            lines.append(f"  {v:16s} {ctr.get(v, 0):3d}  ({ctr.get(v, 0)/n:.0%})" if n else f"  {v:16s} 0")
        won = ctr.get("gold_wrong", 0)
        lines.append(f"  -> swarm vindicated (gold_wrong, swarm right / ODMI wrong): {won}/{n} = {won/n:.0%}" if n else "")

    # per-country and per-dimension breakdown on the decisive signals
    def strat(key, label):
        lines.append(f"\nBy {label}:")
        groups = defaultdict(list)
        for r in ok:
            groups[r[key]].append(r)
        for g in sorted(groups):
            rs = groups[g]
            bits = [f"n={len(rs)}"]
            if do_char:
                se = sum(1 for r in rs if r.get("charitable", {}).get("verdict") == "genuine_error")
                sg = sum(1 for r in rs if r.get("charitable", {}).get("verdict") == "defensible_or_stale_gold")
                bits.append(f"genuine_error={se}")
                bits.append(f"stale_gold={sg}")
            if do_adv:
                gw = sum(1 for r in rs if r.get("adversarial", {}).get("holds") == "gold_wrong")
                bits.append(f"gold_wrong={gw}")
            lines.append(f"  {str(g):14s} {'  '.join(bits)}")

    strat("country", "country")
    strat("dimension", "ODMI dimension")

    # decision cross-tab (confirm/complement/change): where FPs cluster per ODMI methodology
    lines.append("\nBy ODMI decision:")
    dgroups = defaultdict(list)
    for r in ok:
        dgroups[r.get("decision") or "(null)"].append(r)
    for d in sorted(dgroups):
        rs = dgroups[d]
        bits = [f"n={len(rs)}"]
        if do_char:
            se = sum(1 for r in rs if r.get("charitable", {}).get("verdict") == "genuine_error")
            bits.append(f"genuine_error={se}")
        if do_adv:
            gw = sum(1 for r in rs if r.get("adversarial", {}).get("holds") == "gold_wrong")
            bits.append(f"gold_wrong={gw}")
        lines.append(f"  {d:12s} {'  '.join(bits)}")

    # the headline sentence, mirroring the NL claim
    if do_adv:
        won = sum(1 for r in ok if r.get("adversarial", {}).get("holds") == "gold_wrong")
        lines.append(f"\nHEADLINE: {won}/{len(ok)} held-out false positives had the swarm right and "
                     f"ODMI wrong (adversarial gold_wrong).")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=CANONICAL_DB)
    ap.add_argument("--countries", nargs="*", default=list(HELD_OUT),
                    help="country codes to audit (default: the 8 D47 held-out)")
    ap.add_argument("--limit", type=int, default=0, help="0 = all FPs")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--pass", dest="which", choices=["charitable", "adversarial", "both"],
                    default="both")
    ap.add_argument("--tag", default="", help="suffix for output files + condition label")
    args = ap.parse_args()
    do_char = args.which in ("charitable", "both")
    do_adv = args.which in ("adversarial", "both")

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    fps, max_id = load_fps(con, args.countries)
    con.close()
    if args.limit:
        fps = fps[:args.limit]

    RESULTS_DIR.mkdir(exist_ok=True)
    jsonl_path = RESULTS_DIR / f"heldout_fp_audit{args.tag}.jsonl"
    md_path = RESULTS_DIR / f"heldout_fp_audit{args.tag}_summary.md"

    print(f"Base URL: {os.environ['ANTHROPIC_BASE_URL']}  Model: {args.model}")
    print(f"Held-out FP audit: {len(fps)} FPs across {sorted(set(c['country'] for c in fps))}")
    print(f"  passes: {'charitable ' if do_char else ''}{'adversarial' if do_adv else ''}")
    print(f"  DB snapshot per-country max phase2_final.id: {max_id}")
    by_country = Counter(c["country"] for c in fps)
    print(f"  FPs per country: {dict(sorted(by_country.items()))}")
    no_ev = [(c["country"], c["qid"]) for c in fps if not c["has_evidence"]]
    if no_ev:
        print(f"  note: {len(no_ev)} FPs have no stored snippets, audited on quote only: {no_ev}")

    rows = []
    with jsonl_path.open("w") as fh:
        for i, c in enumerate(fps):
            rec = dict(country=c["country"], qid=c["qid"], final_id=c["final_id"],
                       dimension=c["dimension"], decision=c["decision"],
                       answer_confidence=c["answer_confidence"], has_evidence=c["has_evidence"])
            try:
                if do_char:
                    rec["charitable"] = audit_charitable(c, args.model)
                if do_adv:
                    rec["adversarial"] = audit_adversarial(c, args.model)
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"{type(e).__name__}: {e}"
            rows.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if "error" in rec:
                tag = rec["error"]
            else:
                cv = rec.get("charitable", {}).get("verdict", "-")
                av = rec.get("adversarial", {}).get("holds", "-")
                tag = f"char={cv:24s} adv={av:16s} (dim={c['dimension']}, dec={c['decision']})"
            print(f"  [{i+1}/{len(fps)}] {c['country']} {c['qid']:6s} -> {tag}")

    summary = summarise(rows, do_char, do_adv)
    print("\n" + summary)
    md_path.write_text(
        f"# Held-out false-positive audit\n\n"
        f"Model: `{args.model}`  Countries: {args.countries}  "
        f"DB snapshot per-country max phase2_final.id: {max_id}\n\n"
        f"```\n{summary}\n```\n")
    print(f"\nWrote {jsonl_path}\nWrote {md_path}")


if __name__ == "__main__":
    main()
