"""EXP-24 Phase A calibration dump (read-only).

Walks the same path as snippet_cap_analysis.py A2 but, instead of counting hits,
dumps a stratified sample of up to N abstained pairs whose snippets contain a
past-600 keyword cluster. For each case it prints the question, the country,
the ground-truth answer and assessor explanation, and the snippet substring
centred on the cluster. Used to manually calibrate the keyword-cluster
heuristic against actual content relevance.

Run:  uv run python evaluation/snippet_cap_calibration_dump.py --n 20
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "odmi.db"

PROD_CAP = 600
MIN_SNIPPET = 800
KW_WINDOW = 200
MIN_KW = 2

STOPWORDS = {
    "the","a","an","is","are","was","were","do","does","did","of","to","in","on",
    "for","by","with","at","as","from","this","that","these","those","and","or",
    "if","then","than","be","been","being","have","has","had","not","no","yes",
    "you","your","our","we","us","they","them","their","its","it","there",
    "what","which","when","where","how","why","whether","please","describe",
    "explain","explanation","example","examples","any","all","some","most","many",
    "each","every","other","also","such","country","portal","data","national",
    "open","approach","process","provide","would","could","should","may","might",
}

NAMES = {"FR":"France","NL":"Netherlands","NO":"Norway","FI":"Finland","SE":"Sweden",
         "MT":"Malta","AL":"Albania","HR":"Croatia","EE":"Estonia"}


def normalise(s): return re.sub(r"\s+"," ",(s or "").strip()).lower()


def keywords(qt, cn):
    raw = re.findall(r"[A-Za-zÀ-ſ][A-Za-zÀ-ſ\-]{3,}", (qt+" "+cn).lower())
    return [w for w in raw if w not in STOPWORDS]


def first_cluster_pos(snippet, kws):
    txt = normalise(snippet)
    hits = []
    for kw in set(kws):
        if len(kw)<4: continue
        for m in re.finditer(re.escape(kw), txt):
            hits.append((m.start(), kw))
    if len(hits) < MIN_KW: return None
    hits.sort()
    for i,(si,_) in enumerate(hits):
        d=set()
        for j in range(i,len(hits)):
            sj,kj = hits[j]
            if sj-si > KW_WINDOW: break
            d.add(kj)
            if len(d) >= MIN_KW: return si
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    # Quotas per country, prioritising NL (the FP-heavy clean country) and MT
    # (the most hidden absolute hits), then a tail of the others.
    quota = {"NL":7, "MT":7, "FI":2, "SE":1, "NO":1, "HR":1, "AL":1}

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    qtext = {r["question_id"]: r["question_text"] for r in
             cur.execute("SELECT question_id, COALESCE(question_text,'') AS question_text FROM questions")}

    gt = {(r["question_id"], r["country_code"]): (r["response"], r["explanation"]) for r in
          cur.execute("SELECT question_id, country_code, response, COALESCE(explanation,'') explanation FROM ground_truth")}

    abst = cur.execute(
        "SELECT DISTINCT f.question_id, f.country_code "
        "FROM phase2_final f "
        "WHERE f.final_answer='inconclusive' OR f.terminal_status='agent_failure' "
        "ORDER BY f.country_code, f.question_id"
    ).fetchall()

    out = []
    for ab in abst:
        cc = ab["country_code"]
        if quota.get(cc, 0) <= 0:
            continue
        rrows = cur.execute(
            "SELECT search_snippets FROM phase2_researcher_runs "
            "WHERE question_id=? AND country_code=? "
            "  AND search_snippets IS NOT NULL AND search_snippets <> '[]'",
            (ab["question_id"], cc),
        ).fetchall()
        long_snips = []
        for rr in rrows:
            try: snips = json.loads(rr["search_snippets"])
            except: continue
            if not isinstance(snips, list): continue
            for s in snips:
                if isinstance(s, dict) and len(s.get("snippet",""))>MIN_SNIPPET:
                    long_snips.append((s.get("url",""), s["snippet"]))
        if not long_snips: continue

        kws = keywords(qtext.get(ab["question_id"],""), NAMES.get(cc,""))
        if not kws: continue
        for url, body in long_snips:
            pos = first_cluster_pos(body, kws)
            if pos is None or pos <= PROD_CAP: continue
            # Found a past-600 cluster for this pair.
            resp, expl = gt.get((ab["question_id"], cc), ("",""))
            out.append({
                "qid": ab["question_id"], "cc": cc, "url": url, "pos": pos,
                "question": qtext.get(ab["question_id"],""),
                "gt_response": resp, "gt_expl": expl[:280],
                "context_before": body[max(0,pos-80):pos],
                "context_at": body[pos:pos+300],
            })
            quota[cc] -= 1
            break

    print(f"# Calibration sample: {len(out)} of {args.n} cases\n")
    for i, c in enumerate(out, 1):
        print(f"\n=================== CASE {i}: {c['qid']}/{c['cc']} ===================")
        print(f"QUESTION ({c['cc']}): {c['question'][:280]}")
        print(f"GROUND TRUTH: {c['gt_response']}")
        print(f"GT EXPLANATION: {c['gt_expl']}")
        print(f"URL: {c['url']}")
        print(f"CLUSTER POSITION IN SNIPPET: {c['pos']} (past 600 cap)")
        print(f"... [pre-context, chars {max(0,c['pos']-80)}-{c['pos']}]:")
        print(f"   {c['context_before']}")
        print(f"[CLUSTER STARTS HERE] chars {c['pos']}-{c['pos']+300}:")
        print(f"   {c['context_at']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
