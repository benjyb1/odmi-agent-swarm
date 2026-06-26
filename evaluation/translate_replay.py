"""Translate-before-entailment replay (L2 test).

Tests whether translating native-language evidence into English for the
Verifier's entailment judgment changes the verdict, and whether any change moves
toward ground truth. This isolates the comprehension channel: if Sonnet under-
reads native evidence, an English rendering should flip relevance-rejections to
accepts on cases the experts answered the same way.

Design (read-only on the stored trail; nothing is dispatched):
  - Population: pairs where the Verifier FAILED on relevance (verdict=fail,
    substring=pass, so the quote was really on the page but judged off-target)
    and the Researcher had committed an answer, with NATIVE-language evidence.
    Dev/diagnostic countries only: NL, NO, AL. No held-out country.
  - The substring grounding gate is NOT re-run. Per the language-normalised
    design, grounding stays on the original native quote; only the entailment
    judgment sees a translation. So the no-hallucination contract is untouched.
  - Two conditions per case, identical prompt, the ONLY difference is the
    language of the evidence quote: (native) the original; (english) the DeepL
    translation. The question and proposed answer are English in both.
  - Endpoint: verdict agreement; flips native->english (fail->pass = recovered,
    pass->fail = newly caught); and, among flips, whether the move agrees with
    the ODMI gold (a recovered pass is "good" only if the gold supports the
    answer).

Modes:
  select    -> write the candidate cases to results/translate_replay_cases.json
  translate -> DeepL-translate each native quote to English (cached in the file)
  judge     -> LLM entailment on both conditions (Sonnet; run after EXP-22)
  analyze   -> agreement, flips, GT alignment

DeepL key from .env (DEEPL_API_KEY). LLM via the swarm's call_for_structured.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_DB = Path("/Users/benjyb/Desktop/MscProject/data/odmi.db")
OUT = ROOT / "evaluation" / "results" / "translate_replay_cases.json"
COUNTRIES = {"NL": "nl", "NO": "no", "AL": "sq"}
DEEPL_LANG = {"nl": "NL", "no": "NB", "sq": "SQ"}

sys.path.insert(0, str(ROOT))


def _detect_native(text, native_code):
    # Reuse the transparent heuristic detector from the language pass.
    import importlib.util
    spec = importlib.util.spec_from_file_location("ld", "/tmp/langdetect_heur.py")
    # The detector file runs DB code at import; instead inline the function body.
    raise RuntimeError("unused")


# --- minimal inline heuristic detector (no DB side effects) -----------------
import re
from collections import defaultdict
_STOP = {
 'en': set("the and of to in is for on that with as are this by an be or was which it its at from has have not also their public open data portal national government".split()),
 'sq': set("të dhe për është nuk janë me një që nga ose hapja dhënave ripërdorim sipas kombëtar qeveria publike portali shqipëri".split()),
 'nl': set("de het en van een voor gegevens open met op dat zijn niet ook naar wordt overheid door als".split()),
 'no': set("og av for er ikke åpne data som til med det en på offentlig kan har".split()),
}
_DIA = {'sq': 'ëç', 'no': 'åøæ'}
_WORD = re.compile(r"[a-zà-ÿčćžšđ]+", re.I)


def detect(text):
    if not text or len(text.strip()) < 8:
        return 'none'
    t = text.lower()
    toks = _WORD.findall(t)
    if len(toks) < 3:
        return 'none'
    score = defaultdict(float)
    for lg, sw in _STOP.items():
        score[lg] = sum(1 for w in toks if w in sw) / len(toks)
    for lg, ds in _DIA.items():
        d = sum(t.count(c) for c in ds)
        score[lg] += 0.6 * min(d, 8) / max(len(toks), 1) * 3
    best = max(score, key=score.get)
    return best if score[best] >= 0.02 else 'unknown'


def select():
    import sqlite3
    con = sqlite3.connect(MAIN_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
      SELECT v.country_code cc, v.question_id qid, v.pair_run_id pr,
             r.answer ans, r.evidence_quote quote, r.source_url url,
             q.question_text qtext,
             (SELECT response FROM ground_truth gt WHERE gt.question_id=v.question_id AND gt.country_code=v.country_code) gt
      FROM phase2_verifier_runs v
      JOIN phase2_researcher_runs r ON r.id=v.researcher_run_id
      JOIN questions q ON q.question_id=v.question_id
      WHERE v.country_code IN ('NL','NO','AL') AND v.verdict='fail'
        AND v.substring_check_result='pass'
        AND r.answer NOT IN ('inconclusive','other') AND r.answer IS NOT NULL
        AND r.evidence_quote IS NOT NULL AND r.evidence_quote!=''
    """).fetchall()
    cases = []
    seen = set()
    for r in rows:
        if detect(r["quote"]) != COUNTRIES[r["cc"]]:
            continue
        key = (r["qid"], r["cc"], r["quote"][:60])
        if key in seen:
            continue
        seen.add(key)
        cases.append({
            "cc": r["cc"], "qid": r["qid"], "pair_run_id": r["pr"],
            "answer": r["ans"], "quote_native": r["quote"], "source_url": r["url"],
            "question_text": r["qtext"], "gt": r["gt"],
            "quote_english": None, "verdict_native": None, "verdict_english": None,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print("selected", len(cases), "cases:", dict(Counter(c["cc"] for c in cases)))


def _deepl(text, src):
    key = os.environ.get("DEEPL_API_KEY")
    if not key:
        # load from the canonical main-checkout .env (gitignored, holds the key)
        for line in Path("/Users/benjyb/Desktop/MscProject/.env").read_text().splitlines():
            if line.startswith("DEEPL_API_KEY="):
                key = line.split("=", 1)[1].strip()
    data = urllib.parse.urlencode({"text": text, "target_lang": "EN", "source_lang": src}).encode()
    req = urllib.request.Request(
        "https://api-free.deepl.com/v2/translate", data=data,
        headers={"Authorization": f"DeepL-Auth-Key {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["translations"][0]["text"]


def translate():
    cases = json.loads(OUT.read_text())
    n = 0
    for c in cases:
        if c.get("quote_english"):
            continue
        src = DEEPL_LANG[COUNTRIES[c["cc"]]]
        try:
            c["quote_english"] = _deepl(c["quote_native"], src)
            n += 1
            if n % 20 == 0:
                OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
                print("translated", n)
        except Exception as e:  # noqa: BLE001
            print("deepl fail", c["qid"], c["cc"], str(e)[:80])
            time.sleep(2)
    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    print("translated total", sum(1 for c in cases if c.get("quote_english")), "of", len(cases))


_ENTAIL_SYSTEM = (
    "You verify whether a quoted passage of evidence actually supports a specific "
    "proposed answer to a question about a country's open data. Reply 'pass' only "
    "if the passage substantively supports the proposed answer. Reply 'fail' if it "
    "is too general, off-topic, describes something else, or relates only "
    "tangentially. Judge the passage exactly as given."
)


def _entail_message(question_text, answer, quote):
    return (
        f"Question: {question_text}\nProposed answer: {answer}\n"
        f"Evidence passage:\n{quote}\n\nDoes the evidence passage support the "
        f"proposed answer? Reply pass or fail with a one-line reason."
    )


def judge(limit=None):
    """Run the entailment judgment on both conditions (Sonnet). Claude-heavy;
    run only when nothing else is contending for the proxy."""
    from typing import Literal
    from pydantic import BaseModel, Field
    from agents.tools.llm import call_for_structured

    class Entail(BaseModel):
        verdict: Literal["pass", "fail"]
        reason: str = Field(max_length=300)

    cases = json.loads(OUT.read_text())
    todo = [c for c in cases if c.get("quote_english") and c.get("verdict_english") is None]
    if limit:
        todo = todo[:limit]
    print(f"judging {len(todo)} cases x 2 conditions")
    for i, c in enumerate(todo):
        for cond, quote in (("native", c["quote_native"]), ("english", c["quote_english"])):
            try:
                out, _ = call_for_structured(
                    system=_ENTAIL_SYSTEM,
                    user_message=_entail_message(c["question_text"], c["answer"], quote),
                    output_schema=Entail,
                    condition_label=f"translate_replay_{cond}",
                    usage_context=f"translate_replay_{cond}:{c['qid']}:{c['cc']}",
                )
                c[f"verdict_{cond}"] = out.verdict
                c[f"reason_{cond}"] = out.reason
            except Exception as e:  # noqa: BLE001
                print("judge fail", c["qid"], c["cc"], cond, str(e)[:80])
        if (i + 1) % 10 == 0:
            OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
            print("judged", i + 1)
    OUT.write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    print("judge done")


def analyze():
    """Verdict agreement, flips, and GT alignment of any flips."""
    cases = [c for c in json.loads(OUT.read_text())
             if c.get("verdict_native") and c.get("verdict_english")]
    print(f"analysed {len(cases)} judged cases")

    def gt_supports(c):
        # The verifier originally rejected the committed answer. A flip to pass is
        # "good" only if the ODMI gold actually supports that answer.
        gt = (c.get("gt") or "").strip().lower()
        ans = (c.get("answer") or "").strip().lower()
        if not gt:
            return None
        if ans == "yes" and gt.startswith("yes"):
            return True
        if ans == "no" and gt == "no":
            return True
        return ans == gt

    from collections import Counter
    agree = sum(1 for c in cases if c["verdict_native"] == c["verdict_english"])
    recovered = [c for c in cases if c["verdict_native"] == "fail" and c["verdict_english"] == "pass"]
    newly_caught = [c for c in cases if c["verdict_native"] == "pass" and c["verdict_english"] == "fail"]
    print(f"verdict agreement: {agree}/{len(cases)} ({agree/len(cases)*100:.0f}%)")
    print(f"native re-judged: {Counter(c['verdict_native'] for c in cases)}")
    print(f"flips fail->pass (English recovers): {len(recovered)}")
    print(f"flips pass->fail (English newly rejects): {len(newly_caught)}")
    good = [c for c in recovered if gt_supports(c) is True]
    bad = [c for c in recovered if gt_supports(c) is False]
    print(f"  of recovered: GT-supported (good recovery) {len(good)}, GT-contradicted (false recovery) {len(bad)}")
    print(f"by country recovered: {Counter(c['cc'] for c in recovered)}")
    print("\nNET toward ground truth = good recoveries - false recoveries =",
          len(good) - len(bad))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "select"
    arg = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if mode == "judge":
        judge(limit=arg)
    else:
        {"select": select, "translate": translate, "analyze": analyze}[mode]()
