"""EXP-11 stage 1: the verifier-redesign classifier ladder.

Frozen-evidence, paired comparison of verifier strategies as binary
classifiers over a Researcher candidate answer. Borrows the EXP-6
design (evaluation/verifier_strategies.py) but is a separate file so
that pre-registered artefact is not edited.

Arms (live LLM calls, one main call per candidate per arm):
  A  verifier-disprove          (incumbent, binary VerifierOutput)
  B  verifier-tristate          (tristate, adversarial evidence)
  D  verifier-tristate-probes   (tristate, adversarial + probe evidence)
  E  verifier-blind             (optional, --with-blind; binary)

Gated analysis columns are derived offline from the stored outputs, no
extra calls:
  A-gated, B-gated, D-gated  (refute/confirm kept only if the quote
                              verifies per snippet via the v2 matcher;
                              confirm also needs a URL != the
                              Researcher's source).

Per the freeze: substring is computed under BOTH matchers; arm A sees
the v1 result (its production behaviour), arms B/D see v2; both stored.

No phase2_* writes. Streams to evaluation/results/verifier_redesign_*.jsonl
with a "freeze" record per candidate and a "verdict" record per
(candidate, arm), so a killed run resumes and the gates can be re-run
offline.

  uv run python evaluation/verifier_redesign.py --limit 2     # smoke
  uv run python evaluation/verifier_redesign.py               # dev ladder (MT+NO)
  uv run python evaluation/verifier_redesign.py --with-blind  # add arm E
  uv run python evaluation/verifier_redesign.py --analyse-only PATH.jsonl
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from agents import verifier as V
from agents.errors import BlockerShutdown
from agents.models import (
    ResearcherOutput,
    VerifierInput,
    VerifierOutput,
    VerifierOutputTristate,
)
from agents.prompts import verifier as vp
from agents.tools import db as db_helpers
from agents.tools import search_cache
from agents.tools.llm import StructuredOutputError, call_for_structured
from agents.tools.search import search_many
from agents.tools.substring import contains, contains_v2

from evaluation import stats
from evaluation._replay_common import (
    is_abstention,
    is_correct,
    parse_search_snippets,
)

RESULTS = Path(__file__).resolve().parent / "results"
EXPERIMENT_ID = "verifier_tristate_v1"
SEED = 20260610
PROVIDER = "diy"
MAX_RESULTS_PER_QUERY = 5
DEV_COUNTRIES = ["MT", "NO"]

# Arms: (arm_key, strategy_label, schema, sees_probes)
ARMS_CORE = [
    ("A", "verifier-disprove", VerifierOutput, False),
    ("B", "verifier-tristate", VerifierOutputTristate, False),
    ("D", "verifier-tristate-probes", VerifierOutputTristate, True),
]
ARM_BLIND = ("E", "verifier-blind", VerifierOutput, False)


@dataclass
class Candidate:
    cand_id: str
    country_code: str
    country_name: str
    question_id: str
    question_text: str
    dimension: str
    answer_shape: str
    allowed_answers: list
    researcher_answer: str
    gold_response: str
    gold_label: str          # should_pass | should_fail
    absence: bool
    row: dict = field(default=None, repr=False)


# Candidate construction (dev ladder: MT + NO natural)

def build_candidates(limit: Optional[int] = None) -> list[Candidate]:
    from evaluation._replay_common import is_absence_class
    cands = []
    with sqlite3.connect("file:data/odmi.db?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        qmeta = {}
        for r in conn.execute(
            "SELECT question_id, question_text, dimension, answer_shape, "
            "allowed_answers FROM questions"
        ):
            qmeta[r["question_id"]] = dict(
                text=r["question_text"], dim=r["dimension"],
                shape=r["answer_shape"] or "binary",
                allowed=json.loads(r["allowed_answers"]) if r["allowed_answers"] else ["yes", "no"],
            )
        for cc in DEV_COUNTRIES:
            # latest researcher run per question with a definite answer + snippets
            rows = conn.execute(
                "SELECT * FROM phase2_researcher_runs WHERE country_code = ? "
                "AND answer IS NOT NULL AND search_snippets IS NOT NULL "
                "AND search_snippets <> '[]' ORDER BY question_id, id",
                (cc,),
            ).fetchall()
            latest = {}
            for r in rows:
                latest[r["question_id"]] = dict(r)  # later id wins
            for qid, row in latest.items():
                ans = (row["answer"] or "").strip()
                if is_abstention(ans) or not ans:
                    continue
                gold = conn.execute(
                    "SELECT response, country_name FROM ground_truth "
                    "WHERE question_id = ? AND country_code = ?", (qid, cc)
                ).fetchone()
                if not gold or not (gold["response"] or "").strip():
                    continue
                meta = qmeta.get(qid)
                if not meta:
                    continue
                correct = is_correct(qid, ans, gold["response"])
                cands.append(Candidate(
                    cand_id=f"{cc}:{qid}",
                    country_code=cc, country_name=gold["country_name"],
                    question_id=qid, question_text=meta["text"],
                    dimension=meta["dim"], answer_shape=meta["shape"],
                    allowed_answers=meta["allowed"], researcher_answer=ans,
                    gold_response=gold["response"],
                    gold_label="should_pass" if correct else "should_fail",
                    absence=is_absence_class(qid, ans),
                    row=row,
                ))
    cands.sort(key=lambda c: c.cand_id)
    if limit:
        cands = cands[:limit]
    return cands


def _researcher_output(cand: Candidate) -> Optional[ResearcherOutput]:
    row = cand.row
    quote = (row["evidence_quote"] or "").strip()
    if len(quote) < 10:
        quote = (quote + " " + (row["answer_explanation"] or ""))[:200].strip()
        if len(quote) < 10:
            return None
    try:
        return ResearcherOutput(
            answer=cand.researcher_answer,
            answer_explanation=(row["answer_explanation"] or cand.researcher_answer)[:2000],
            evidence_quote=quote,
            source_url=row["source_url"] or "https://example.invalid/none",
            retrieval_confidence=row["retrieval_confidence"] or 0.5,
            answer_confidence=row["answer_confidence"] or 0.5,
        )
    except ValidationError:
        return None


def _snips_with_urls(search_results) -> list[dict]:
    return [{"url": r.url, "snippet": r.snippet, "title": r.title}
            for r in search_results]


# Freeze evidence once per candidate

def freeze_evidence(cand: Candidate, ro: ResearcherOutput) -> dict:
    """One query-gen + search for the adversarial set, one for the probe
    set, plus both substring matchers. Returns a JSON-able freeze dict."""
    snippets = parse_search_snippets(cand.row["search_snippets"])

    v_inp = VerifierInput(
        question_id=cand.question_id, question_text=cand.question_text,
        country_code=cand.country_code, country_name=cand.country_name,
        researcher_output=ro, strategy="verifier-disprove",
        answer_shape=cand.answer_shape, allowed_answers=cand.allowed_answers,
        researcher_snippets=snippets,
    )

    # substring under both matchers, against the researcher's own snippets
    v1 = contains("\n\n".join(s for s in snippets if s), ro.evidence_quote)
    v2 = contains_v2(snippets, ro.evidence_quote)

    # Each generator gets one retry inside call_for_structured already; if
    # it still fails we degrade that channel to empty rather than dropping
    # the candidate, which would break the paired set.
    def _gen_search(gen_fn):
        try:
            queries, _ = gen_fn(v_inp)
        except Exception:
            return [], []
        try:
            results = search_many(queries, max_results_per_query=MAX_RESULTS_PER_QUERY,
                                  provider=PROVIDER)
        except (Exception, BlockerShutdown):
            # BlockerShutdown (BaseException) fires when the DIY fetch stage
            # exceeds 30s on a slow/WAF query. In production it halts the run
            # for a human; in this offline harness one slow query must not kill
            # the whole sweep, so we degrade that channel to empty and carry on.
            return queries, []
        return queries, results

    adversarial_queries, adv_results = _gen_search(V.generate_adversarial_queries)
    probe_queries, probe_results = _gen_search(V.generate_confirmation_probes)

    return dict(
        researcher_snippets=snippets,
        substring_v1="pass" if v1 else "fail",
        substring_v2="pass" if v2.matched else "fail",
        substring_v2_reason=v2.reason,
        adversarial_queries=adversarial_queries,
        adversarial_snippets=_snips_with_urls(adv_results),
        probe_queries=probe_queries,
        probe_snippets=_snips_with_urls(probe_results),
        researcher_source_url=str(ro.source_url),
        evidence_quote=ro.evidence_quote,
    )


# Run one arm

def _adv_snip_texts(freeze) -> list[str]:
    return [f"{s.get('title','')} — {s['snippet'][:200]}" for s in freeze["adversarial_snippets"]]


def run_arm(cand: Candidate, ro: ResearcherOutput, freeze: dict, arm,
            prompt_ids: dict) -> dict:
    arm_key, strategy, schema, sees_probes = arm
    spec = vp.STRATEGIES[strategy]
    adv_texts = _adv_snip_texts(freeze)

    if schema is VerifierOutput:
        substring_result = freeze["substring_v1"]  # arm A/E see v1
        user_message = vp.build_user_message(
            question_text=cand.question_text, country_name=cand.country_name,
            country_code=cand.country_code, researcher_output=ro,
            substring_result=substring_result, substring_notes=None,
            independent_queries=freeze["adversarial_queries"],
            independent_snippets=adv_texts, strategy=strategy,
            answer_shape=cand.answer_shape, allowed_answers=cand.allowed_answers,
        )
    else:
        substring_result = freeze["substring_v2"]  # arms B/D see v2
        probe_texts = (
            [f"{s.get('title','')} — {s['snippet'][:200]}" for s in freeze["probe_snippets"]]
            if sees_probes else []
        )
        user_message = vp.build_tristate_user_message(
            question_text=cand.question_text, country_name=cand.country_name,
            country_code=cand.country_code, researcher_output=ro,
            substring_result=substring_result, substring_notes=None,
            independent_queries=freeze["adversarial_queries"],
            independent_snippets=adv_texts,
            answer_shape=cand.answer_shape, allowed_answers=cand.allowed_answers,
            probe_queries=freeze["probe_queries"] if sees_probes else None,
            probe_snippets=probe_texts if sees_probes else None,
            include_probes=sees_probes,
        )

    try:
        out, usage = call_for_structured(
            system=spec.system, user_message=user_message,
            output_schema=schema, max_tokens=1500,
            condition_label=f"exp11_{arm_key}",
            prompt_version_id=prompt_ids.get(strategy),
            usage_context=f"exp11_{arm_key}:{cand.cand_id}",
        )
    except (StructuredOutputError, ValidationError) as exc:
        return dict(kind="verdict", cand_id=cand.cand_id, arm=arm_key,
                    strategy=strategy, failed=str(exc)[:200])

    parsed = out.model_dump(mode="json")

    # Blind post-processing, mirrors production agents/verifier.py.
    if strategy == "verifier-blind" and parsed["verifier_answer"] != cand.researcher_answer:
        if parsed["verdict"] == "pass":
            parsed["verdict"] = "fail"
            parsed["rejection_reason"] = (
                f"Blind verifier answered {parsed['verifier_answer']!r} vs "
                f"researcher {cand.researcher_answer!r}."
            )
            parsed.setdefault("counter_evidence_quote",
                              adv_texts[0][:200] if adv_texts else "n/a")

    return dict(
        kind="verdict", cand_id=cand.cand_id, arm=arm_key, strategy=strategy,
        substring_shown=substring_result, output=parsed,
        out_tokens=usage.output_tokens, cost_usd=usage.estimated_cost_usd,
    )


# Run loop (resumable)

def _disable_render():
    """Monkeypatch the DIY pipeline's Playwright fallback to a fast-fail.

    The browser launch in fetch_rendered_html has no timeout and wedges
    under 6-worker concurrency on Cloudflare-walled pages (data.gov.mt),
    which hung the dev run. WAF pages now return empty fast instead of
    hanging. Effect on evidence: a handful of WAF portal pages (almost all
    Malta, and Malta is mostly already frozen) contribute no snippet to
    the Verifier's INDEPENDENT search; the Researcher's own frozen
    snippets and the substring gate are untouched. Documented in the
    EXP-11 dev-run notes. See search_diy.py:33 on the launch-timeout gap.
    """
    import agents.tools.search_diy as sd
    from agents.tools.fetch import FetchResult

    def _noop_render(url, timeout_s=0.0, **kw):
        return FetchResult(url=url, backend="playwright", status_code=0,
                           content="", truncated=False,
                           failure_mode="render_disabled")
    sd.fetch_rendered_html = _noop_render


def _register_prompts(arms) -> dict:
    """Register each arm strategy's prompt and return {strategy: prompt_id}.
    A receipt write (prompt_versions), done once before the pool."""
    ids = {}
    for _key, strategy, _schema, _probes in arms:
        spec = vp.STRATEGIES[strategy]
        ids[strategy] = db_helpers.ensure_prompt_version(
            spec.name, spec.version, spec.system, spec.description,
        )
    return ids


def _process_candidate(cand, arms, frozen, done_freeze, done_verdict, prompt_ids):
    """Freeze (if needed) and run pending arms for one candidate. Returns
    (freeze_record_or_None, [verdict_records]). Runs in a worker thread;
    does no file IO so the main thread can serialise writes."""
    ro = _researcher_output(cand)
    if ro is None:
        return None, [], "no usable researcher output"
    freeze_rec = None
    if cand.cand_id in done_freeze:
        fr = frozen[cand.cand_id]
    else:
        try:
            fr = freeze_evidence(cand, ro)
        except Exception as exc:
            return None, [], f"freeze-fail {str(exc)[:80]}"
        freeze_rec = dict(
            kind="freeze", cand_id=cand.cand_id, freeze=fr,
            country=cand.country_code, question_id=cand.question_id,
            dimension=cand.dimension, answer_shape=cand.answer_shape,
            allowed_answers=cand.allowed_answers,
            researcher_answer=cand.researcher_answer,
            gold_response=cand.gold_response, gold_label=cand.gold_label,
            absence=cand.absence,
        )
    verdicts = []
    for arm in arms:
        if (cand.cand_id, arm[0]) in done_verdict:
            continue
        verdicts.append(run_arm(cand, ro, fr, arm, prompt_ids))
    return freeze_rec, verdicts, None


def run(limit: Optional[int], with_blind: bool, out_name: Optional[str],
        workers: int = 6):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / (out_name or f"verifier_redesign_{EXPERIMENT_ID}.jsonl")

    arms = list(ARMS_CORE) + ([ARM_BLIND] if with_blind else [])
    cands = build_candidates(limit=limit)
    prompt_ids = _register_prompts(arms)

    done_freeze, done_verdict, frozen = set(), set(), {}
    if out_path.exists():
        for line in out_path.open():
            rec = json.loads(line)
            if rec.get("kind") == "freeze":
                done_freeze.add(rec["cand_id"]); frozen[rec["cand_id"]] = rec["freeze"]
            elif rec.get("kind") == "verdict":
                done_verdict.add((rec["cand_id"], rec["arm"]))

    pending = [c for c in cands
               if any((c.cand_id, a[0]) not in done_verdict for a in arms)]
    n_pass = sum(1 for c in cands if c.gold_label == "should_pass")
    print(f"Dev ladder: {len(cands)} candidates "
          f"({n_pass} should_pass / {len(cands)-n_pass} should_fail), arms={[a[0] for a in arms]}")
    print(f"Resuming: {len(done_freeze)} freezes done; {len(pending)} candidates pending; "
          f"workers={workers}")

    f = out_path.open("a")
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_process_candidate, c, arms, frozen, done_freeze,
                          done_verdict, prompt_ids): c for c in pending}
        for fut in as_completed(futs):
            c = futs[fut]
            done += 1
            try:
                freeze_rec, verdicts, err = fut.result()
            except (Exception, BlockerShutdown) as exc:
                print(f"  [{done}/{len(pending)}] {c.cand_id} WORKER-ERROR {str(exc)[:80]}")
                continue
            if err:
                print(f"  [{done}/{len(pending)}] {c.cand_id} SKIP ({err})")
                continue
            if freeze_rec is not None:
                f.write(json.dumps(freeze_rec) + "\n")
            vs = []
            for rec in verdicts:
                f.write(json.dumps(rec) + "\n")
                vs.append(f"{rec['arm']}={rec.get('output',{}).get('verdict', 'FAIL')}")
            f.flush()
            print(f"  [{done}/{len(pending)}] {c.cand_id} gold={c.gold_label} "
                  f"r={c.researcher_answer!r} {' '.join(vs)}")
    f.close()
    print(f"\nWrote {out_path}")
    return out_path


# Analysis (offline; recomputes gated columns)

def _verifies(quote: Optional[str], snippet_objs: list[dict]) -> Optional[int]:
    """Return the index of the snippet that carries the quote per the v2
    matcher, or None. snippet_objs are {url, snippet, title}."""
    if not quote:
        return None
    texts = [s["snippet"] for s in snippet_objs]
    res = contains_v2(texts, quote)
    return res.snippet_index if res.matched else None


def _binarise(verdict: str) -> str:
    """Map any arm verdict to pass/fail for the J classifier."""
    if verdict in ("fail", "refute"):
        return "fail"
    return "pass"  # pass, confirm, inconclusive


def _gated_verdict(arm_key, output, freeze):
    """Apply the deterministic gate; return the (possibly downgraded)
    verdict in tristate vocabulary for B/D, binary for A/E."""
    verdict = output["verdict"]
    adv = freeze["adversarial_snippets"]
    researcher_snips = [{"url": freeze["researcher_source_url"], "snippet": s, "title": ""}
                        for s in freeze["researcher_snippets"]]
    probe = freeze.get("probe_snippets", [])
    counter = output.get("counter_evidence_quote")
    corro = output.get("corroborating_quote")

    if arm_key in ("A", "E"):
        # binary: a 'fail' survives iff substring v2 failed OR the counter
        # quote verifies against adversarial+researcher snippets.
        if verdict == "fail":
            if freeze["substring_v2"] == "fail":
                return "fail"
            if _verifies(counter, adv + researcher_snips) is not None:
                return "fail"
            return "pass"  # unverifiable fail downgraded
        return "pass"

    # tristate B/D
    if verdict == "refute":
        if freeze["substring_v2"] == "fail":
            return "refute"
        if _verifies(counter, adv + probe + researcher_snips) is not None:
            return "refute"
        return "inconclusive"
    if verdict == "confirm":
        idx = _verifies(corro, adv + probe)
        if idx is not None:
            url = (adv + probe)[idx]["url"]
            if url and url != freeze["researcher_source_url"]:
                return "confirm"
        return "inconclusive"
    return "inconclusive"


def _confusion(records_by_cand, column_fn, predicate):
    tp = fp = tn = fn = 0
    passes = fails = inconcl = confirms = 0
    for cand_id, (freeze_meta, arm_outputs) in records_by_cand.items():
        if not predicate(freeze_meta):
            continue
        v = column_fn(freeze_meta, arm_outputs)
        if v is None:
            continue
        if v == "refute":
            fails += 1
        elif v == "confirm":
            confirms += 1; passes += 1
        elif v == "inconclusive":
            inconcl += 1; passes += 1
        elif v == "fail":
            fails += 1
        else:
            passes += 1
        b = _binarise(v)
        gold = freeze_meta["gold_label"]
        if gold == "should_fail" and b == "fail":
            tp += 1
        elif gold == "should_pass" and b == "fail":
            fp += 1
        elif gold == "should_fail" and b == "pass":
            fn += 1
        else:
            tn += 1
    return dict(tp=tp, fp=fp, tn=tn, fn=fn, n=tp+fp+tn+fn,
                passes=passes, fails=fails, inconcl=inconcl, confirms=confirms)


def _metrics(c):
    tp, fp, tn, fn = c["tp"], c["fp"], c["tn"], c["fn"]
    pos, neg = tp + fn, fp + tn
    sens = tp / pos if pos else float("nan")
    spec = tn / neg if neg else float("nan")
    fpr = fp / neg if neg else float("nan")
    j = (sens + spec - 1) if (pos and neg) else float("nan")
    denom = ((tp+fp)*(tp+fn)*(tn+fp)*(tn+fn)) ** 0.5
    mcc = ((tp*tn - fp*fn) / denom) if denom else float("nan")
    bal = ((sens + spec) / 2) if (pos and neg) else float("nan")
    return dict(sens=sens, spec=spec, fpr=fpr, youden_j=j, mcc=mcc,
                bal_acc=bal, pos=pos, neg=neg)


def analyse(path: Path):
    freezes, verdicts = {}, {}
    for line in Path(path).open():
        rec = json.loads(line)
        if rec["kind"] == "freeze":
            freezes[rec["cand_id"]] = rec
        elif rec["kind"] == "verdict" and "output" in rec:
            verdicts.setdefault(rec["cand_id"], {})[rec["arm"]] = rec

    # assemble: cand_id -> (freeze_meta, {arm: output})
    by_cand = {}
    for cid, fr in freezes.items():
        arms = {a: v["output"] for a, v in verdicts.get(cid, {}).items()}
        by_cand[cid] = (fr, arms)

    arms_present = sorted({a for _, arms in by_cand.values() for a in arms})
    print(f"\nAnalysed {len(by_cand)} candidates; arms present: {arms_present}")

    # Columns: raw arms + gated arms.
    def raw_col(arm):
        return lambda fm, ao: (ao[arm]["verdict"] if arm in ao else None)

    def gated_col(arm):
        def fn(fm, ao):
            if arm not in ao:
                return None
            return _gated_verdict(arm, ao[arm], fm["freeze"])
        return fn

    columns = []
    for arm in arms_present:
        columns.append((f"{arm}-raw", raw_col(arm)))
        columns.append((f"{arm}-gated", gated_col(arm)))

    strata = [
        ("DEV all", lambda fm: True),
        ("DEV MT", lambda fm: fm["country"] == "MT"),
        ("DEV NO", lambda fm: fm["country"] == "NO"),
        ("no-claims", lambda fm: fm["absence"]),
        ("yes-claims", lambda fm: not fm["absence"]),
    ]

    for sname, pred in strata:
        print(f"\n===== {sname} =====")
        print(f"  {'column':16} {'n':>4} {'J':>6} {'MCC':>6} {'sens':>5} {'spec':>5} "
              f"{'fpr':>5} {'pass%':>6} {'verdict dist (f/inc/conf/pass)':>22}")
        for cname, cfn in columns:
            c = _confusion(by_cand, cfn, pred)
            if c["n"] == 0:
                continue
            m = _metrics(c)
            passrate = (c["passes"] / c["n"]) if c["n"] else float("nan")
            dist = f"{c['fails']}/{c['inconcl']}/{c['confirms']}/{c['passes']}"
            print(f"  {cname:16} {c['n']:>4} {m['youden_j']:>6.2f} {m['mcc']:>6.2f} "
                  f"{m['sens']:>5.2f} {m['spec']:>5.2f} {m['fpr']:>5.2f} "
                  f"{passrate:>6.2f} {dist:>22}")

    # Paired McNemar on verdict-correctness over the dev ladder, the four
    # planned comparisons, Holm-corrected.
    print("\n===== Paired comparisons (DEV all, McNemar exact on verdict-correctness, Holm) =====")
    def correct_indicator(col_fn):
        ind = {}
        for cid, (fm, ao) in by_cand.items():
            v = col_fn(fm, ao)
            if v is None:
                continue
            b = _binarise(v)
            want = "fail" if fm["gold_label"] == "should_fail" else "pass"
            ind[cid] = (b == want)
        return ind

    col_map = {cn: cf for cn, cf in columns}
    planned = [
        ("A-raw vs A-gated", "A-raw", "A-gated"),
        ("A-raw vs B-raw", "A-raw", "B-raw"),
        ("B-raw vs B-gated", "B-raw", "B-gated"),
        ("B-gated vs D-gated", "B-gated", "D-gated"),
    ]
    pvals = []
    for label, x, y in planned:
        if x not in col_map or y not in col_map:
            continue
        ix, iy = correct_indicator(col_map[x]), correct_indicator(col_map[y])
        shared = set(ix) & set(iy)
        b = sum(1 for k in shared if ix[k] and not iy[k])
        c = sum(1 for k in shared if iy[k] and not ix[k])
        p = stats.mcnemar_exact(b, c)
        pvals.append((label, b, c, p))
    # Holm
    order = sorted(range(len(pvals)), key=lambda i: pvals[i][3])
    holm = [None] * len(pvals)
    m = len(pvals)
    for rank, i in enumerate(order):
        holm[i] = min(1.0, pvals[i][3] * (m - rank))
    for (label, b, c, p), h in zip(pvals, holm):
        better = "2nd better" if c > b else ("1st better" if b > c else "tie")
        print(f"  {label:24} discordant b={b} c={c}  p={p:.4f}  Holm={h:.4f}  ({better})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--with-blind", action="store_true")
    ap.add_argument("--analyse-only", type=str, default=None)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-render", action="store_true", default=False,
                    help="disable the Playwright WAF fallback (avoids the "
                         "browser-launch hang under concurrency)")
    ap.add_argument("--no-cache", action="store_true", default=True)
    args = ap.parse_args()

    if args.analyse_only:
        analyse(Path(args.analyse_only))
        return

    search_cache.set_read_disabled(True)  # pinned cold cache (R9)
    if args.no_render:
        _disable_render()
        print("Playwright render fallback DISABLED (WAF pages fail fast).")
    out_path = run(args.limit, args.with_blind, args.out, workers=args.workers)
    analyse(out_path)


if __name__ == "__main__":
    main()
