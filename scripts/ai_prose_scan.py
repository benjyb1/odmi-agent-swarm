"""Scan for the prose patterns Benjy's supervisor reads as machine-written.

Scoped to the red runs by default. The red in this document is incorporated
body prose rather than review marking, and it is where drafted text ended up,
so it is where the tells cluster. Scanning all 30,000 words would bury the
signal.

This flags patterns, not verdicts. A rule-of-three list can be the right way to
write a sentence. The output is a shortlist to reread, ordered by how strongly
each pattern reads as generated.

Usage:
    python3 scripts/ai_prose_scan.py --qa build/qa/report.json
    python3 scripts/ai_prose_scan.py --qa build/qa/report.json --all
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

# Weight is how strongly the pattern reads as generated, 3 being the most
# telling. Ordering by it puts the sentences worth rereading at the top.
PATTERNS = [
    (3, "negative_parallelism",
     r"\b(?:is|was|are|were|does|do|did)\s+not\s+(?:just|merely|simply|only)\b[^.]{0,60}?,?\s*(?:but|it is|they are)\b",
     "States the thing by what it is not. Say what it is."),
    (3, "negative_parallelism",
     r"\bnot\s+(?:a|an|the)?\s*\w+[^.]{0,30},\s*but\s+(?:a|an|the|rather)\b",
     "'Not X, but Y' construction."),
    (3, "inflated_significance",
     r"\b(?:stands? as|serves? as|represents? a|marks? a|is a testament|plays? a (?:vital|key|central|significant) role|underscore[sd]?|highlight(?:s|ing)? the (?:importance|need|significance))\b",
     "Inflated significance. State the fact instead."),
    (2, "hollow_signposting",
     r"\b(?:it is (?:important|worth) (?:to note|noting|mentioning)|notably|importantly|significantly,|it should be noted)\b",
     "Hollow signpost. If it matters, just say it."),
    (2, "superficial_ing",
     r",\s+(?:highlighting|emphasising|emphasizing|showcasing|reflecting|underscoring|demonstrating|illustrating|showing that|revealing|suggesting that)\b",
     "Trailing -ing clause that restates rather than analyses."),
    (2, "conjunctive_scaffolding",
     r"(?:^|\.\s+)(?:Moreover|Furthermore|Additionally|In addition|Consequently|Nevertheless|Nonetheless)\b",
     "Connective used as scaffolding between points."),
    (2, "vague_attribution",
     r"\b(?:some (?:argue|suggest|contend|researchers)|it (?:has been|is) (?:shown|argued|suggested)|research (?:shows|suggests|indicates)|studies (?:show|suggest)|experts (?:agree|suggest))\b",
     "Vague attribution with no named source."),
    (2, "ai_vocabulary",
     r"\b(?:delve|crucial|landscape|tapestry|testament|realm|nuanced|multifaceted|pivotal|paradigm|holistic|robust(?:ly)?|seamless(?:ly)?|leverage[sd]?|showcase[sd]?|intricate|myriad)\b",
     "Vocabulary his supervisor reads as generated."),
    (1, "colon_chain",
     r":\s+[A-Z][^.]{0,80}\.\s+[A-Z][^.]{0,80}\.\s+[A-Z]",
     "Colon then stacked short clauses."),
    (1, "em_dash", r"—", "Em dash. House style forbids them."),
]

RULE_OF_THREE = re.compile(
    r"\b(\w+(?:\s+\w+){0,2}),\s+(\w+(?:\s+\w+){0,2}),\s+and\s+(\w+(?:\s+\w+){0,2})\b")


def scan_text(text):
    hits = []
    for weight, name, pat, why in PATTERNS:
        for m in re.finditer(pat, text, re.I):
            hits.append((weight, name, m.group(0)[:70], why))
    for m in RULE_OF_THREE.finditer(text):
        # Only interesting when the three items are of similar length, which is
        # the rhythmic triad rather than an ordinary list.
        parts = [len(m.group(i)) for i in (1, 2, 3)]
        if max(parts) - min(parts) <= 6:
            hits.append((1, "rule_of_three", m.group(0)[:70],
                         "Triad used for rhythm rather than content."))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", default="build/qa/report.json")
    ap.add_argument("--all", action="store_true",
                    help="scan the whole document rather than the red runs")
    ap.add_argument("--min-words", type=int, default=8)
    args = ap.parse_args()

    with open(args.qa) as f:
        qa = json.load(f)

    if args.all:
        with open(args.qa.replace("report.json", "full.txt")) as f:
            units = [{"text": line, "chapter": "?"} for line in f if line.strip()]
        label = "whole document"
    else:
        units = [r for r in qa["red_runs"] if r["words"] >= args.min_words]
        label = f"{len(units)} red runs of {args.min_words}+ words"

    by_pattern = defaultdict(list)
    flagged = []
    for u in units:
        hits = scan_text(u["text"])
        if not hits:
            continue
        score = sum(h[0] for h in hits)
        flagged.append((score, u, hits))
        for h in hits:
            by_pattern[h[1]].append((u, h))

    flagged.sort(key=lambda x: -x[0])
    print(f"scanned {label}")
    print(f"flagged {len(flagged)} of {len(units)}\n")

    print("=== pattern counts ===")
    for name, items in sorted(by_pattern.items(), key=lambda kv: -len(kv[1])):
        print(f"  {name:26} {len(items)}")

    print("\n=== worst offenders ===")
    for score, u, hits in flagged[:12]:
        ch = u.get("chapter", "?")
        print(f"\n[{score}] {ch}")
        print(f"  {u['text'][:190]}")
        for _w, name, frag, why in hits[:4]:
            print(f"     - {name}: {frag!r}")
            print(f"       {why}")


if __name__ == "__main__":
    main()
