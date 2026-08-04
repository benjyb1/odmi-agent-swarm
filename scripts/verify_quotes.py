"""Check that every QUOTE in the sweep findings really appears in the master.

A finding the author cannot find with Ctrl-F is worse than no finding, and a
quote an agent paraphrased or reconstructed is a false report. This checks each
one against the snapshot text and marks it EXACT, NORMALISED or NOT FOUND.

Normalised means it matches once smart quotes, dashes, non-breaking spaces and
runs of whitespace are flattened. That still finds in Word, so it passes, but
the flattened form is reported so the author searches for something that exists.

Usage:
    python3 scripts/verify_quotes.py --findings build/pubsweep/findings \
        --docx build/pub/snapshot.docx --out build/pub/quotes_verified.json
"""

from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))

# Characters Word renders that an agent commonly retypes as the ASCII form.
FOLD = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "‑": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
    "…": "...",
}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for k, v in FOLD.items():
        s = s.replace(k, v)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def load_doc_text(docx):
    spec = importlib.util.spec_from_file_location(
        "dqa", os.path.join(HERE, "dissertation_qa.py"))
    dqa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dqa)
    paras = dqa.extract(docx)["paragraphs"]
    chapters = dqa.split_chapters(paras)

    def chapter_of(i):
        for c in chapters:
            if c["start"] <= i < c["end"]:
                return c["name"]
        return "(front matter)"

    joined = "\n".join(p["text"] for p in paras)
    return paras, chapter_of, joined


def parse_findings(path):
    """Blocks of QUOTE/PROBLEM/FIX/SEVERITY. Tolerant of stray prose between."""
    text = open(path).read()
    out = []
    blocks = re.split(r"(?m)^(?=QUOTE:)", text)
    for b in blocks:
        if not b.startswith("QUOTE:"):
            continue
        def grab(field, nxt):
            m = re.search(rf"(?:{field}):\s*(.*?)(?=\n\s*(?:{nxt}):|\Z)", b, re.S)
            return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        out.append({
            "quote": grab("QUOTE", "PROBLEM|WRONG|FIX|SEVERITY"),
            "problem": grab("PROBLEM|WRONG", "FIX|SEVERITY"),
            "fix": grab("FIX", "SEVERITY"),
            "severity": grab("SEVERITY", "QUOTE"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--docx", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    paras, chapter_of, joined = load_doc_text(args.docx)
    folded_paras = [(p["i"], fold(p["text"])) for p in paras]
    folded_joined = fold(joined)

    results = []
    for f in sorted(glob.glob(os.path.join(args.findings, "*.md"))):
        unit = os.path.basename(f)[:-3]
        for item in parse_findings(f):
            q = item["quote"].strip()
            # Agents sometimes wrap a quote in backticks or add a markup tag.
            q = q.strip("`").strip()
            q = re.sub(r"^<br\s*/?>", "", q).strip()
            q = q.strip('"').strip("'") if q[:1] in "\"'" and q[-1:] in "\"'" else q
            verdict, where, found = "NOT FOUND", None, None
            if q and q in joined:
                verdict = "EXACT"
                for p in paras:
                    if q in p["text"]:
                        where, found = chapter_of(p["i"]), p["i"]
                        break
            elif q:
                fq = fold(q)
                if fq and fq in folded_joined:
                    verdict = "NORMALISED"
                    for i, ft in folded_paras:
                        if fq in ft:
                            where, found = chapter_of(i), i
                            break
            results.append({
                "unit": unit, "quote": q, "verdict": verdict,
                "chapter": where, "paragraph": found,
                "problem": item["problem"], "fix": item["fix"],
                "severity": item["severity"],
            })

    with open(args.out, "w") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False)

    from collections import Counter
    print("verdicts:", dict(Counter(r["verdict"] for r in results)))
    print("severity:", dict(Counter(r["severity"] for r in results)))
    print()
    bad = [r for r in results if r["verdict"] == "NOT FOUND"]
    if bad:
        print("NOT FOUND, these must not be reported as quotes:")
        for r in bad:
            print(f"  [{r['unit']}] {r['quote'][:90]!r}")
    print(f"\nwritten to {args.out}  ({len(results)} findings)")


if __name__ == "__main__":
    main()
