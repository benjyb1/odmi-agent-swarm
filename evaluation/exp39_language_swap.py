"""EXP-39 Part A, step 2: the language-swap replay.

Reads the frozen translations (`exp39_translations.jsonl`, written by
`exp39_translate.py` in a side venv) and re-scores the frozen
verifier-disprove prompt on `claude-sonnet-4-6` over the same candidates,
with the evidence surface rendered in fr / bg / sq. The untranslated English
anchor arm is not re-run here: EXP-38's `disprove_replay` verdicts on the
same cand_ids are the anchor (same builder, same strategy, same model,
byte-identical English evidence), read directly from
`exp38_corroborate_ladder.jsonl`.

Endpoints (docs/EXPERIMENTS_LANGUAGE_PROBE.md): per-language Youden's J,
verdict flip rate vs the English anchor, exact McNemar per language vs
anchor; the en->fr arm is the MT-artefact control, and comprehension is
implicated for X only if X's degradation exceeds fr's by the pre-registered
margins (>= 0.10 J beyond fr, or flip rate above fr's with p < 0.05).

Resume-safe; rate-limit pauses rather than dying (shares the Claude window
with the EXP-36 headline run).

  uv run python evaluation/exp39_language_swap.py --workers 2
  uv run python evaluation/exp39_language_swap.py --analyse-only
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import ValidationError

from agents.errors import RateLimitedShutdown
from agents.models import VerifierOutput
from agents.prompts import verifier as vp
from agents.tools import db as db_helpers
from agents.tools.llm import StructuredOutputError, call_for_structured

from evaluation import stats
from evaluation.exp38_corroborate_ladder import (
    DB,
    _country_names,
    _load_freezes,
    _question_meta,
    _recover_researcher_row,
    _researcher_output,
)

RESULTS = Path(__file__).resolve().parent / "results"
TRANSLATIONS = RESULTS / "exp39_translations.jsonl"
ANCHOR = RESULTS / "exp38_corroborate_ladder.jsonl"
OUT = RESULTS / "exp39_language_swap.jsonl"
SUMMARY = RESULTS / "exp39_language_swap_summary.json"
STRATEGY = "verifier-disprove"
TARGETS = ["fr", "bg", "sq"]

RATE_LIMIT_PAUSE_S = 300
RATE_LIMIT_MAX_WAVES = 24

_pause_lock = threading.Lock()
_pause_until = 0.0


def _load_translations() -> tuple[dict, dict[tuple[str, str], dict]]:
    meta = None
    recs: dict[tuple[str, str], dict] = {}
    for line in TRANSLATIONS.open():
        r = json.loads(line)
        if r.get("kind") == "meta":
            meta = r
        else:
            recs[(r["cand_id"], r["target_lang"])] = r
    if meta is None:
        raise SystemExit("translations file has no meta record; re-run step 1")
    return meta, recs


def _anchor_verdicts() -> dict[str, str]:
    out = {}
    for line in ANCHOR.open():
        r = json.loads(line)
        if r.get("arm") == "disprove_replay" and "verdict" in r:
            out[r["cand_id"]] = r["verdict"]
    return out


def _wait_out_rate_limit() -> None:
    global _pause_until
    with _pause_lock:
        _pause_until = max(_pause_until, time.time() + RATE_LIMIT_PAUSE_S)
    while time.time() < _pause_until:
        time.sleep(10)


def _run_one(rec, ro, qtext, cname, target, trans, prompt_id):
    fz = rec["freeze"]
    snippet_texts = [
        f"{s.get('title', '')} — {t[:200]}"
        for s, t in zip(fz["adversarial_snippets"], trans["snippets_translated"])
    ]
    ro_swapped = ro.model_copy(
        update={"evidence_quote": trans["evidence_quote_translated"]
                or ro.evidence_quote}
    )
    msg = vp.build_user_message(
        question_text=qtext,
        country_name=cname,
        country_code=rec["country"],
        researcher_output=ro_swapped,
        substring_result=fz["substring_v2"],
        substring_notes=None,
        independent_queries=fz["adversarial_queries"],
        independent_snippets=snippet_texts,
        strategy=STRATEGY,
        answer_shape=rec["answer_shape"],
        allowed_answers=rec["allowed_answers"],
    )
    spec = vp.STRATEGIES[STRATEGY]
    for _ in range(RATE_LIMIT_MAX_WAVES):
        while time.time() < _pause_until:
            time.sleep(10)
        try:
            out, usage = call_for_structured(
                system=spec.system,
                user_message=msg,
                output_schema=VerifierOutput,
                max_tokens=1500,
                condition_label=f"exp39_{target}",
                prompt_version_id=prompt_id,
                usage_context=f"exp39_{target}:{rec['cand_id']}",
            )
        except RateLimitedShutdown:
            _wait_out_rate_limit()
            continue
        except (StructuredOutputError, ValidationError) as exc:
            return dict(cand_id=rec["cand_id"], arm=target, failed=str(exc)[:160])
        return dict(
            cand_id=rec["cand_id"],
            arm=target,
            verdict=out.verdict,
            verifier_confidence=out.verifier_confidence,
            output=out.model_dump(mode="json"),
        )
    return dict(cand_id=rec["cand_id"], arm=target, failed="rate_limited_out")


def run(workers: int) -> None:
    meta, translations = _load_translations()
    freezes = _load_freezes()
    english = [c for c in meta["english_subset"] if c in freezes]

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    qmeta = _question_meta(conn)
    cnames = _country_names(conn)

    spec = vp.STRATEGIES[STRATEGY]
    prompt_id = db_helpers.ensure_prompt_version(
        spec.name, spec.version, spec.system, spec.description
    )

    done = set()
    if OUT.exists():
        for line in OUT.open():
            r = json.loads(line)
            if "verdict" in r:
                done.add((r["cand_id"], r["arm"]))

    work = []
    for cid in english:
        rec = freezes[cid]
        explanation, rconf, aconf, _ = _recover_researcher_row(conn, rec)
        ro = _researcher_output(rec, explanation, rconf, aconf)
        if ro is None:
            continue
        qtext = qmeta.get(rec["question_id"], {}).get("question_text", rec["question_id"])
        cname = cnames.get(rec["country"], rec["country"])
        for target in TARGETS:
            trans = translations.get((cid, target))
            if trans is None or (cid, target) in done:
                continue
            work.append((rec, ro, qtext, cname, target, trans))
    conn.close()

    print(
        f"English subset n={len(english)}, targets={TARGETS}, "
        f"{len(work)} calls pending ({len(done)} done), workers={workers}"
    )
    fh = OUT.open("a")
    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(_run_one, rec, ro, qt, cn, tg, tr, prompt_id):
                (rec["cand_id"], tg)
            for (rec, ro, qt, cn, tg, tr) in work
        }
        for fut in as_completed(futs):
            n += 1
            cid, tg = futs[fut]
            try:
                out_rec = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"  [{n}/{len(work)}] {cid} {tg} ERROR {str(exc)[:80]}")
                continue
            fh.write(json.dumps(out_rec) + "\n")
            fh.flush()
            if n % 25 == 0 or "failed" in out_rec:
                print(
                    f"  [{n}/{len(work)}] {cid} {tg} -> "
                    f"{out_rec.get('verdict', out_rec.get('failed', '?'))}"
                )
    fh.close()
    print(f"Wrote {OUT}")


def analyse() -> None:
    meta, _ = _load_translations()
    freezes = _load_freezes()
    anchor = _anchor_verdicts()
    english = [c for c in meta["english_subset"] if c in anchor]

    verdicts: dict[str, dict[str, str]] = {}
    for line in OUT.open():
        r = json.loads(line)
        if "verdict" in r:
            verdicts.setdefault(r["cand_id"], {})[r["arm"]] = r["verdict"]

    def j_and_flips(arm: str) -> dict:
        tp = fp = tn = fn = flips = shared = 0
        for cid in english:
            v = anchor.get(cid) if arm == "en" else verdicts.get(cid, {}).get(arm)
            if v is None:
                continue
            shared += 1
            gold = freezes[cid]["gold_label"]
            if gold == "should_fail" and v == "fail":
                tp += 1
            elif gold == "should_pass" and v == "fail":
                fp += 1
            elif gold == "should_fail" and v == "pass":
                fn += 1
            else:
                tn += 1
            if arm != "en" and anchor.get(cid) is not None and v != anchor[cid]:
                flips += 1
        pos, neg = tp + fn, fp + tn
        sens = tp / pos if pos else float("nan")
        spc = tn / neg if neg else float("nan")
        j = sens + spc - 1 if pos and neg else float("nan")
        flip_rate = flips / shared if shared and arm != "en" else 0.0
        return dict(n=shared, youden_j=j, sensitivity=sens, specificity=spc,
                    flips=flips, flip_rate=flip_rate)

    def mcnemar_vs_anchor(arm: str) -> tuple[int, int, float]:
        b = c = 0
        for cid in english:
            va, vx = anchor.get(cid), verdicts.get(cid, {}).get(arm)
            if va is None or vx is None:
                continue
            want = "fail" if freezes[cid]["gold_label"] == "should_fail" else "pass"
            ca, cx = va == want, vx == want
            if ca and not cx:
                b += 1
            elif cx and not ca:
                c += 1
        return b, c, stats.mcnemar_exact(b, c)

    summary = {"english_subset_n": len(english), "arms": {}}
    print(f"\nEXP-39 language swap (English-evidence subset n={len(english)})")
    print(f"{'arm':8} {'n':>4} {'J':>6} {'sens':>5} {'spec':>5} {'flips':>6} {'fliprate':>9}")
    for arm in ["en"] + TARGETS:
        m = j_and_flips(arm)
        summary["arms"][arm] = m
        print(f"{arm:8} {m['n']:>4} {m['youden_j']:>6.2f} {m['sensitivity']:>5.2f} "
              f"{m['specificity']:>5.2f} {m['flips']:>6} {m['flip_rate']:>9.2f}")

    print("\nMcNemar vs English anchor:")
    for arm in TARGETS:
        b, c, p = mcnemar_vs_anchor(arm)
        summary["arms"][arm]["mcnemar_vs_en"] = dict(b=b, c=c, p=p)
        print(f"  en vs {arm}: b={b} c={c} p={p:.4f}")

    j_en = summary["arms"]["en"]["youden_j"]
    j_fr = summary["arms"]["fr"]["youden_j"]
    control_drop = j_en - j_fr
    print(f"\nMT-artefact control (en->fr) J drop: {control_drop:.2f}")
    for arm in ("bg", "sq"):
        drop = j_en - summary["arms"][arm]["youden_j"]
        beyond = drop - control_drop
        verdict = "COMPREHENSION IMPLICATED" if beyond >= 0.10 else "within control margin"
        summary["arms"][arm]["drop_beyond_fr_control"] = beyond
        print(f"  {arm}: J drop {drop:.2f}, beyond-control {beyond:+.2f} -> {verdict}")

    SUMMARY.write_text(json.dumps(summary, indent=2))
    print(f"\nSummary JSON: {SUMMARY}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--analyse-only", action="store_true")
    args = ap.parse_args()
    if args.analyse_only:
        analyse()
        return
    run(args.workers)
    analyse()


if __name__ == "__main__":
    main()
