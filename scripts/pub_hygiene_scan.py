"""Publication-hygiene scan: the deterministic checks the QA sweep does not do.

dissertation_qa.py covers scaffolding keywords, house style, US spellings and
SPaG. This adds the checks a pre-publication pass needs and that one cannot
delegate to judgement, because a miss ships:

- every bracketed fragment in visible text, reported without filtering
- a census of coloured runs by context (body prose, heading, caption, table)
- internal identifiers: file paths, experiment ids, script names, db paths,
  localhost, branch and worktree names
- placeholder and stub captions
- informal or shouted register that reads as a note rather than prose
- doubled words, stray single-character paragraphs, unbalanced delimiters

Read-only. No LLM, no network.

Usage:
    python3 scripts/pub_hygiene_scan.py --qa build/pub/report.json --out build/pub
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# patterns
# ---------------------------------------------------------------------------

BRACKET = re.compile(r"\[[^\]\[]{0,200}\]")

# Bracketed forms that are legitimate academic prose rather than a leftover
# note. Everything else is reported for the author to judge.
BRACKET_OK = re.compile(
    r"^\[(?:sic|"
    r"\d{1,3}(?:[,–-]\s*\d{1,3})*|"          # numeric citation
    r"[A-Z][a-z]+(?:\s+(?:et\s+al\.?|and|&)\s+[A-Z][a-z]+)?,?\s*\d{4}[a-z]?"  # Author, 2024
    r")\]$"
)

INTERNAL = [
    (r"\bdata/odmi\.db\b", "database path"),
    (r"\bodmi\.db\b", "database filename"),
    (r"\bexp\d+[a-z]*_[a-z0-9_]+\b", "experiment id"),
    (r"\b(?:EXP|D)-\d+\b", "internal decision or experiment id"),
    (r"\bscripts/[a-z_0-9]+\.py\b", "script path"),
    (r"\b(?:evaluation|agents|dashboard|tests|docs)/[\w/]+\.(?:py|json|md|jsonl)\b",
     "repo path"),
    (r"\b[a-z_0-9]+\.(?:py|jsonl|sqlite|db)\b", "source filename"),
    (r"localhost(?::\d+)?|127\.0\.0\.1", "localhost address"),
    (r"\.claude/worktrees/[\w.-]+", "worktree path"),
    (r"\b(?:origin/)?(?:main|claude/[\w.-]+)\b(?=\s+branch|\bbranch\b)", "branch name"),
    (r"/Users/[\w./-]+", "absolute local path"),
    (r"\buv run\b|\bpytest\b|\bgit (?:commit|push|merge)\b", "shell command"),
    (r"\bCLIProxyAPI\b|\bcliproxyapi\b", "internal tool name"),
    (r"\bSPEC\.md\b|\bFAILURE_MODES\.md\b|\bPROJECT_LOG\.md\b|\bRESULTS\.md\b",
     "internal doc name"),
    (r"\bmerged_responses\b|\bground_truth\b(?!\s+(?:answer|key|data|label))",
     "database table name"),
    (r"\btrio_s5\b|\bsubtrio[s]?\b|\bdispatch_subtrios\b", "internal jargon"),
]

PLACEHOLDER = [
    (r"\bTODO\b", "TODO"),
    (r"\bTBC\b", "TBC"),
    (r"\bTBD\b", "TBD"),
    (r"\bFIXME\b", "FIXME"),
    (r"XXX", "XXX"),
    (r"\blorem\b", "lorem"),
    (r"\[REF\]|\[ref\]|\[CITATION\]|\[citation needed\]", "citation placeholder"),
    (r"(?i)\b(?:figure|table|section|appendix|chapter)\s+[XYN]\b(?![\w])",
     "FIGURE X style placeholder"),
    (r"(?i)\bTable\s+\d*\s*Caption\s*:", "stub caption"),
    (r"(?i)\bcaption\s*:\s*$", "empty caption"),
    (r"(?i)\bstill needs? doing\b|\bneeds? writing\b|\byet to be written\b",
     "unfinished marker"),
    (r"\?\?\?+", "??? marker"),
    (r"(?i)\bplaceholder\b", "the word placeholder"),
    (r"(?i)\binsert\s+(?:figure|table|ref|citation|here)\b", "insert instruction"),
    (r"(?i)\bcheck this\b|\bfix this\b|\bcome back to\b|\brewrite this\b",
     "note to self"),
]

# Shouted or informal register that reads as a note, not prose.
SHOUTY = re.compile(r"\b[A-Z]{2,}(?:['’]?[A-Z]*)?(?:\s+[A-Z]{2,}['’]?[A-Z]*){2,}")
INFORMAL = re.compile(
    r"(?i)\b(?:i've|ive|i'm|im just|messed|mucked|sort of|kind of|a bit of a|"
    r"tbh|obviously|basically just|for now|at some point|not sure if|"
    r"need to|should probably|might want to|gonna|wanna)\b"
)

DOUBLED_WORD = re.compile(r"\b(\w+)\s+\1\b(?!\s*\1)", re.I)
# Words that legitimately repeat in English prose.
DOUBLED_OK = {"had", "that", "very", "no", "so", "long", "far", "well", "many"}


def context(text, start, end, pad=70):
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    return ("..." if a else "") + text[a:b].replace("\n", " ") + ("..." if b < len(text) else "")


def classify(par):
    """Where a paragraph sits, for the colour census."""
    if par.get("is_heading"):
        return "heading"
    if par.get("in_table"):
        return "table"
    t = par["text"].strip()
    if re.match(r"(?i)^(?:figure|table|fig\.?)\s*[\dA-Z][\d.]*\s*[:.–-]", t):
        return "caption"
    if len(t.split()) <= 3:
        return "short/fragment"
    return "body prose"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", required=True)
    ap.add_argument("--out", default="build/pub")
    args = ap.parse_args()

    with open(args.qa) as f:
        qa = json.load(f)
    paras = qa["paragraphs"] if "paragraphs" in qa else None

    # dissertation_qa.py does not persist paragraphs; rebuild from red_runs and
    # chapters is lossy, so re-extract from the same snapshot instead.
    if paras is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dqa", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "dissertation_qa.py"))
        dqa = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dqa)
        doc = dqa.extract(qa["source"])
        paras = doc["paragraphs"]
        chapters = dqa.split_chapters(paras)
    else:
        chapters = qa["chapters"]

    def chapter_of(i):
        for c in chapters:
            if c["start"] <= i < c["end"]:
                return c["name"]
        return "(front matter)"

    findings = defaultdict(list)

    # ---------------- brackets ----------------
    for p in paras:
        t = p["text"]
        if not t.strip():
            continue
        for m in BRACKET.finditer(t):
            frag = m.group(0)
            if BRACKET_OK.match(frag):
                continue
            findings["brackets"].append({
                "chapter": chapter_of(p["i"]), "paragraph": p["i"],
                "fragment": frag,
                "where": classify(p),
                "context": context(t, m.start(), m.end()),
            })

    # ---------------- internal identifiers ----------------
    for p in paras:
        t = p["text"]
        if not t.strip():
            continue
        for pat, label in INTERNAL:
            for m in re.finditer(pat, t):
                findings["internal_ids"].append({
                    "chapter": chapter_of(p["i"]), "paragraph": p["i"],
                    "match": m.group(0), "kind": label,
                    "where": classify(p),
                    "context": context(t, m.start(), m.end()),
                })

    # ---------------- placeholders ----------------
    for p in paras:
        t = p["text"]
        if not t.strip():
            continue
        for pat, label in PLACEHOLDER:
            for m in re.finditer(pat, t):
                findings["placeholders"].append({
                    "chapter": chapter_of(p["i"]), "paragraph": p["i"],
                    "match": m.group(0), "kind": label,
                    "where": classify(p),
                    "context": context(t, m.start(), m.end()),
                })

    # ---------------- register ----------------
    for p in paras:
        t = p["text"]
        if not t.strip():
            continue
        for m in SHOUTY.finditer(t):
            if len(m.group(0)) < 9:
                continue
            findings["shouty"].append({
                "chapter": chapter_of(p["i"]), "paragraph": p["i"],
                "match": m.group(0), "where": classify(p),
                "context": context(t, m.start(), m.end()),
            })
        for m in INFORMAL.finditer(t):
            findings["informal"].append({
                "chapter": chapter_of(p["i"]), "paragraph": p["i"],
                "match": m.group(0), "where": classify(p),
                "context": context(t, m.start(), m.end()),
            })

    # ---------------- doubled words, strays, delimiters ----------------
    for p in paras:
        t = p["text"]
        s = t.strip()
        if not s:
            continue
        for m in DOUBLED_WORD.finditer(t):
            if m.group(1).lower() in DOUBLED_OK or len(m.group(1)) < 3:
                continue
            findings["doubled_words"].append({
                "chapter": chapter_of(p["i"]), "paragraph": p["i"],
                "match": m.group(0), "context": context(t, m.start(), m.end()),
            })
        if len(s) <= 2 and not p.get("is_heading") and not p.get("in_table") \
                and not re.match(r"^[\dIVXivx]+\.?$", s):
            findings["stray_chars"].append({
                "chapter": chapter_of(p["i"]), "paragraph": p["i"], "text": s})
        for open_c, close_c, name in (("(", ")", "parens"), ("[", "]", "square"),
                                      ("“", "”", "smart quotes")):
            if t.count(open_c) != t.count(close_c):
                findings["unbalanced"].append({
                    "chapter": chapter_of(p["i"]), "paragraph": p["i"],
                    "kind": name, "opens": t.count(open_c), "closes": t.count(close_c),
                    "quote": s[:180]})

    # ---------------- colour census ----------------
    census = defaultdict(lambda: defaultdict(lambda: {"runs": 0, "words": 0}))
    coloured_body = []
    for p in paras:
        where = classify(p)
        ch = chapter_of(p["i"])
        for r in p["runs"]:
            col = r.get("colour")
            if not col or col in ("000000", "auto"):
                continue
            cell = census[ch][f"{col}/{where}"]
            cell["runs"] += 1
            cell["words"] += len(r["text"].split())
            if where in ("body prose", "caption", "heading") and \
                    len(r["text"].split()) >= 5:
                coloured_body.append({
                    "chapter": ch, "paragraph": p["i"], "colour": col,
                    "where": where, "words": len(r["text"].split()),
                    "text": r["text"][:200]})
    findings["colour_census"] = {k: dict(v) for k, v in census.items()}
    findings["coloured_prose_runs"] = coloured_body

    out = os.path.join(args.out, "hygiene_scan.json")
    with open(out, "w") as f:
        json.dump({k: (v if not isinstance(v, list) else v)
                   for k, v in findings.items()}, f, indent=1, ensure_ascii=False)

    print(f"brackets                {len(findings['brackets'])}")
    print(f"internal identifiers    {len(findings['internal_ids'])}")
    print(f"placeholders            {len(findings['placeholders'])}")
    print(f"shouty fragments        {len(findings['shouty'])}")
    print(f"informal register       {len(findings['informal'])}")
    print(f"doubled words           {len(findings['doubled_words'])}")
    print(f"stray characters        {len(findings['stray_chars'])}")
    print(f"unbalanced delimiters   {len(findings['unbalanced'])}")
    print(f"coloured prose runs     {len(findings['coloured_prose_runs'])}")
    print()
    print("colour census by chapter:")
    for ch, cells in findings["colour_census"].items():
        tot = sum(c["words"] for c in cells.values())
        print(f"  {ch}: {tot} coloured words")
        for k, c in sorted(cells.items(), key=lambda kv: -kv[1]["words"]):
            print(f"      {k:34s} runs {c['runs']:5d}  words {c['words']:6d}")
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
