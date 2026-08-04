r"""Deterministic QA sweep over the LaTeX dissertation.

The LaTeX successor to dissertation_qa.py: reads Dissertation/latex/
and emits the same manifest shape (report.json plus per-chapter text),
so verify_numbers.py, ai_prose_scan.py and the reading passes work
unchanged. The check functions themselves are imported from
dissertation_qa; this file only synthesises its paragraph structure
from the .tex sources.

References are resolved before checking: \ref{sec:selectivity} becomes
"Section 4.2" via the compiled .aux files, and \textcite/\parencite
become author-year text via references.bib, so the number and
cross-reference checks see what a reader of the PDF sees. Compile
before running, or the resolver has no .aux to read.

LaTeX-specific additions: every % comment in the sources is reported
as a note (comments ship in the source and are read by anyone given
the project), and the citation integrity fields come from the biblatex
key check rather than a typed reference list.

Usage:
    python3 scripts/latex_qa.py Dissertation/latex --out build/pub
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dissertation_qa as dqa  # noqa: E402

CHAPTER_FILES = [
    "00-front-matter.tex",
    "01-introduction.tex",
    "02-background-and-related-work.tex",
    "03-approach-and-methodology.tex",
    "04-results.tex",
    "05-discussion.tex",
    "06-conclusion.tex",
    "08-appendix.tex",
]


def aux_labels(base: str) -> dict:
    labels = {}
    paths = [os.path.join(base, "main.aux")]
    chdir = os.path.join(base, "chapters")
    if os.path.isdir(chdir):
        paths += sorted(os.path.join(chdir, f) for f in os.listdir(chdir)
                        if f.endswith(".aux"))
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for m in re.finditer(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}",
                                 f.read()):
                labels.setdefault(m.group(1), m.group(2))
    return labels


def bib_authors(base: str) -> dict:
    """key -> 'Surname (year)' for citation rendering."""
    out = {}
    path = os.path.join(base, "references.bib")
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for entry in re.finditer(
                r"@\w+\{([^,]+),(.*?)(?=\n@|\Z)", f.read(), re.S):
            key, body = entry.group(1), entry.group(2)
            author = re.search(r"author\s*=\s*\{(.*?)\},", body, re.S)
            year = re.search(r"year\s*=\s*\{(\d{4})\}", body)
            surname = "Anon"
            if author:
                first = author.group(1).split(" and ")[0]
                surname = re.sub(r"[{}\\\"']", "", first.split(",")[0]).strip()
            out[key] = (surname, year.group(1) if year else "n.d.")
    return out


def delatex(text: str, labels: dict, bib: dict) -> str:
    """Visible text of a LaTeX fragment, references resolved."""
    def ref(m):
        return labels.get(m.group(1), "??")

    text = re.sub(r"\\ref\{([^}]+)\}", ref, text)

    def textcite(m):
        keys = [k.strip() for k in m.group(1).split(",")]
        s, y = bib.get(keys[0], ("??", "??"))
        return f"{s} et al. ({y})" if len(keys) == 1 else s

    def parencite(m):
        parts = []
        for k in m.group(1).split(","):
            s, y = bib.get(k.strip(), ("??", "??"))
            parts.append(f"{s} et al., {y}")
        return "(" + "; ".join(parts) + ")"

    text = re.sub(r"\\textcite\{([^}]+)\}", textcite, text)
    text = re.sub(r"\\parencite\{([^}]+)\}", parencite, text)

    text = re.sub(r"(?<!\\)%.*", "", text)
    # commands with up to three brace groups whose content is invisible
    text = re.sub(r"\\(?:label|nocite|hypersetup|addcontentsline"
                  r"|graphicspath|includegraphics|input|include"
                  r"|setlength|newcolumntype)"
                  r"(\[[^\]]*\])?(\{[^{}]*\}){1,3}", "", text)
    # tabular/longtable environment shells and their column specs
    text = re.sub(r"\\begin\{(?:tabular|longtable)\}(\[[^\]]*\])?"
                  r"\{(?:[^{}]|\{[^{}]*\})*\}", "", text)
    text = re.sub(r"\\end\{(?:tabular|longtable)\}", "", text)
    for _ in range(3):
        text = re.sub(
            r"\\(?:emph|textbf|textit|texttt|textsc|mbox|caption)"
            r"\{([^{}]*)\}", r"\1", text)
    text = text.replace("\\newline", " ")
    text = re.sub(r"\\(?:toprule|midrule|bottomrule|noalign\{\}|endfirsthead"
                  r"|endhead|endlastfoot|centering|raggedright"
                  r"|arraybackslash|strut)", "", text)
    text = text.replace("\\checkmark", "tick").replace("\\times", "cross")
    text = text.replace("\\rho", "rho").replace("\\geq", ">=")
    text = text.replace("\\neq", "/=").replace("\\rightarrow", "->")
    text = text.replace("``", '"').replace("''", '"')
    text = re.sub(r"\\,", " ", text)
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)
    text = re.sub(r"\\([%&#$_{}])", r"\1", text)
    text = text.replace("~", " ").replace("{", "").replace("}", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def tex_comments(base: str) -> list:
    """Every % comment in the sources: they ship in the project."""
    found = []
    files = ["main.tex", "kclthesis.cls"] + [
        os.path.join("chapters", f) for f in CHAPTER_FILES]
    for rel in files:
        path = os.path.join(base, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                m = re.search(r"(?<!\\)%(.*)", line)
                if m and m.group(1).strip():
                    found.append({"kind": "tex-comment", "file": rel,
                                  "line": n, "paragraph": None,
                                  "chapter": None,
                                  "text": m.group(1).strip()})
    return found


def build_paragraphs(base: str) -> list:
    labels = aux_labels(base)
    bib = bib_authors(base)
    paragraphs = []
    i = 0

    def add(text, style="Normal", in_table=False, heading=False):
        nonlocal i
        text = text.strip()
        if not text:
            return
        paragraphs.append({"i": i, "text": text, "style": style,
                           "is_heading": heading, "in_table": in_table,
                           "runs": []})
        i += 1

    for fname in CHAPTER_FILES:
        raw = open(os.path.join(base, "chapters", fname),
                   encoding="utf-8").read()

        # floats and longtables handled structurally
        pieces = re.split(r"(\\begin\{longtable\}.*?\\end\{longtable\}"
                          r"|\\begin\{figure\}.*?\\end\{figure\})",
                          raw, flags=re.S)
        for piece in pieces:
            if piece.startswith("\\begin{longtable}"):
                cap = re.search(r"\\caption\{((?:[^{}]|\{[^{}]*\})*)\}"
                                r"\\label\{([^}]+)\}", piece)
                if cap:
                    num = labels.get(cap.group(2), "?")
                    add(f"Table {num}: "
                        + delatex(cap.group(1), labels, bib))
                body = piece.split("\\endlastfoot", 1)
                rows = body[1] if len(body) == 2 else piece
                rows = rows.replace("\\end{longtable}", "")
                for row in rows.split("\\\\"):
                    for cell in row.split("&"):
                        add(delatex(cell, labels, bib), in_table=True)
            elif piece.startswith("\\begin{figure}"):
                cap = re.search(r"\\caption\{((?:[^{}]|\{[^{}]*\})*)\}", piece)
                lab = re.search(r"\\label\{(fig:[^}]+)\}", piece)
                num = labels.get(lab.group(1), "?") if lab else "?"
                if cap:
                    add(f"Figure {num}: "
                        + delatex(cap.group(1), labels, bib))
            else:
                for block in re.split(r"\n\s*\n", piece):
                    hm = re.match(
                        r"\s*\\(chapter|section|subsection)\*?"
                        r"\{((?:[^{}]|\{[^{}]*\})*)\}", block)
                    if hm:
                        style = {"chapter": "Heading1",
                                 "section": "Heading2",
                                 "subsection": "Heading3"}[hm.group(1)]
                        add(delatex(hm.group(2), labels, bib),
                            style=style, heading=True)
                        rest = block[hm.end():]
                        add(delatex(rest, labels, bib))
                    else:
                        add(delatex(block, labels, bib))
    return paragraphs


def check_citation_keys(base: str) -> tuple:
    bib = open(os.path.join(base, "references.bib"), encoding="utf-8").read()
    bib_keys = set(re.findall(r"@\w+\{([^,]+),", bib))
    used = set()
    chdir = os.path.join(base, "chapters")
    for fname in os.listdir(chdir):
        if not fname.endswith(".tex"):
            continue
        text = open(os.path.join(chdir, fname), encoding="utf-8").read()
        for m in re.finditer(r"\\(?:textcite|parencite|nocite)\{([^}]+)\}",
                             text):
            used.update(k.strip() for k in m.group(1).split(","))
    main = open(os.path.join(base, "main.tex"), encoding="utf-8").read()
    for m in re.finditer(r"\\nocite\{([^}]+)\}", main):
        used.update(k.strip() for k in m.group(1).split(","))
    missing = [{"key": k} for k in sorted(used - bib_keys)]
    orphan = [{"key": k} for k in sorted(bib_keys - used)]
    return missing, orphan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("latex_dir")
    ap.add_argument("--out", default="build/pub")
    args = ap.parse_args()

    base = args.latex_dir
    paragraphs = build_paragraphs(base)
    chapters = dqa.split_chapters(paragraphs)

    notes = dqa.check_notes(paragraphs, [], chapters)
    notes.extend(tex_comments(base))
    claims, conflicts = dqa.check_numbers(paragraphs, chapters)
    cite_missing, cite_orphan = check_citation_keys(base)

    report = {
        "source": os.path.abspath(base),
        "totals": {
            "paragraphs": len(paragraphs),
            "words": sum(len(p["text"].split()) for p in paragraphs),
            "chapters": len(chapters),
            "headings": sum(1 for p in paragraphs if p["is_heading"]),
        },
        "chapters": chapters,
        "notes": notes,
        "scaffolding": dqa.check_scaffolding(paragraphs, chapters, notes),
        "structure": dqa.check_structure(paragraphs, chapters),
        "crossrefs": dqa.check_crossrefs(paragraphs, chapters),
        "number_claims": claims,
        "number_conflicts": conflicts,
        "style": dqa.check_style(paragraphs, chapters),
        "spag": dqa.check_spag(paragraphs, chapters),
        "duplicates": dqa.check_duplicates(paragraphs, chapters),
        "citations_missing": cite_missing,
        "citations_orphan": cite_orphan,
        "red_runs": [],
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "report.json"), "w") as f:
        json.dump(report, f, indent=1)

    chdir = os.path.join(args.out, "chapters")
    os.makedirs(chdir, exist_ok=True)
    for n, c in enumerate(chapters):
        slug = re.sub(r"[^a-z0-9]+", "_", c["name"].lower()).strip("_")[:40]
        lines = []
        for p in paragraphs[c["start"]:c["end"]]:
            if not p["text"].strip():
                continue
            prefix = "### " if p["is_heading"] else ""
            lines.append(prefix + p["text"])
        with open(os.path.join(chdir, f"{n:02d}_{slug}.txt"), "w") as f:
            f.write("\n\n".join(lines))

    with open(os.path.join(args.out, "full.txt"), "w") as f:
        f.write("\n\n".join(p["text"] for p in paragraphs
                            if p["text"].strip()))

    dqa.summarise(report)
    print(f"\nwritten to {args.out}/report.json and {args.out}/chapters/")


if __name__ == "__main__":
    main()
