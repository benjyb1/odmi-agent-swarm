r"""Rewrite every literal cross-reference as a \ref.

The docx hand-types all of its ~240 cross-references, five kinds:
§2.2, Chapter 4, Appendix E, Figure 4.5.1, Table 4.4.1. Every one
becomes Word~\ref{label} with a non-breaking space, using the label
maps below. § renders as "Section" per the house style set for the
migration; a bare § chapter number renders as "Chapter".

Quoted table numbers from other papers in the Appendix E scorecard
("Table 3 reports Check-COVID performance...") are not references to
this document and are left alone: only numbers present in the maps
are rewritten, and plain "Table 2"/"Table 3"/"Table 7" are not keys.

Emits build/refs_manifest.json recording every replacement with the
literal it replaced, which check_refs.py verifies against the compiled
.aux, number by number, per the migration brief.

Usage: python3 rewrite_refs.py latex_dir
"""

import json
import re
import sys
from pathlib import Path

SECTIONS = {
    "1.1": "sec:domain", "1.2": "sec:motivation", "1.3": "sec:open-world",
    "1.4": "sec:approach", "1.5": "sec:research-questions",
    "1.6": "sec:contributions", "1.7": "sec:report-structure",
    "2.1": "sec:odmi-assessment", "2.2": "sec:criteria",
    "2.3": "sec:llm-limitations", "2.4": "sec:verification-methods",
    "2.5": "sec:debate", "2.6": "sec:abstention", "2.7": "sec:multilingual",
    "2.8": "sec:research-gap",
    "3.1": "sec:architecture", "3.2": "sec:agent-loop", "3.3": "sec:retrieval",
    "3.4": "sec:ground-truth", "3.5": "sec:catalogue-tool",
    "3.6": "sec:leakage-controls", "3.7": "sec:evaluation-set",
    "3.8": "sec:experiments", "3.9": "sec:metrics",
    "4.1": "sec:convergent-validity", "4.2": "sec:selectivity",
    "4.3": "sec:attributability", "4.4": "sec:subgroup-equity",
    "4.5": "sec:generalisability", "4.6": "sec:reproducibility",
    "4.7": "sec:ablation", "4.8": "sec:cost-runtime",
    "4.9": "sec:reconstruction",
    "5.1": "sec:scorecard", "5.2": "sec:debate-odmi",
    "5.3": "sec:reformulation", "5.4": "sec:threats", "5.5": "sec:lsep",
}

CHAPTERS = {
    "1": "ch:introduction", "2": "ch:background", "3": "ch:methodology",
    "4": "ch:results", "5": "ch:discussion", "6": "ch:conclusion",
}

# §8.3 is the docx-era address of Appendix C, from when the appendix
# was chapter 8 and C its third section.
SECTION_ALIASES = {"8.3": "app:experiments"}

APPENDICES = {
    "A": "app:failure-register", "B": "app:pipeline-detail",
    "C": "app:experiments", "D": "app:out-of-reach",
    "E": "app:prior-work-scored", "F": "app:baselines",
    "G": "app:question-bank", "H": "app:catalogue-recompute",
    "I": "app:dev-results", "J": "app:unused-figures",
}

FIGURES = {
    "1.1": "fig:assumption",
    # the docx numbers two figures 2.1; the only prose mention of a
    # chapter 2 figure by number is "the loop traced in Figure 2.2",
    # which is the prior-steered retrieval loop
    "2.2": "fig:prior-steered", "2.3": "fig:lineage",
    "3.1": "fig:subtrio", "3.2": "fig:leakage-points",
    "3.3": "fig:evaluation-set-fig",
    "4.1.1": "fig:outcome-makeup", "4.1.2": "fig:accuracy-by-class",
    "4.1.3": "fig:recompute-band", "4.2.1": "fig:per-class-confidence",
    "4.2.2": "fig:reliability", "4.4.2": "fig:against-maturity",
    "4.5.1": "fig:by-dimension", "4.5.2": "fig:by-answer-shape",
    "4.6.2": "fig:replicates-fig", "4.9.1": "fig:reconstruction-fig",
    "5.1": "fig:error-vs-maturity", "5.2": "fig:two-failure-modes",
    "5.3": "fig:dimension-oversight",
    "B.1": "fig:abstained-by-country",
    "J.1": "fig:j-funnel", "J.2": "fig:j-shares", "J.3": "fig:j-four-ways",
    "J.4": "fig:j-forced", "J.5": "fig:j-confidence-at-commit",
    "J.6": "fig:j-subthreshold", "J.7": "fig:j-abstention-codes",
    "J.8": "fig:j-code-gold-mix", "J.9": "fig:j-abstention-accuracy",
    "J.10": "fig:j-yes-share-dropped", "J.11": "fig:j-yes-share-no",
    "J.12": "fig:j-yes-share-oracle", "J.13": "fig:j-score-bands",
    "J.14": "fig:j-coverage-published", "J.16": "fig:j-two-populations",
    "J.17": "fig:j-asymmetry",
}

TABLES = {
    "2.1": "tab:criteria", "2.2": "tab:prior-work",
    "3.1": "tab:answer-shapes", "3.2": "tab:harvests", "3.3": "tab:metrics",
    "4.1.1": "tab:four-ways", "4.2.1": "tab:abstention-reasons",
    "4.3.1": "tab:attributability", "4.4.1": "tab:strata",
    "4.6.1": "tab:replicates", "4.7.1": "tab:ablation", "4.8.1": "tab:cost",
    "5.1": "tab:scorecard", "5.2": "tab:reformulation",
    "A.1": "tab:failure-register", "B.1": "tab:abstention-codes",
    "B.2": "tab:fp-audit", "C.1": "tab:experiments",
    "D.1": "tab:out-of-reach", "E.1": "tab:prior-work-full",
    "F.1": "tab:baselines", "G.1": "tab:question-bank",
    "H.1": "tab:harvest-register", "H.2": "tab:catalogue-metrics",
    "I.1": "tab:dev-by-country", "I.2": "tab:dev-by-dimension",
}

manifest = []
unknown = []


def sub_all(text, fname):
    def record(kind, literal, label, word):
        manifest.append({"file": fname, "kind": kind, "literal": literal,
                         "label": label})
        return f"{word}~\\ref{{{label}}}"

    def section_ref(m):
        num = m.group(1)
        if num in SECTIONS:
            return record("section", "§" + num, SECTIONS[num], "Section")
        if num in SECTION_ALIASES:
            return record("appendix", "§" + num, SECTION_ALIASES[num],
                          "Appendix")
        if num in CHAPTERS:
            return record("chapter", "§" + num, CHAPTERS[num], "Chapter")
        unknown.append((fname, "§" + num))
        return m.group(0)

    text = re.sub(r"§\s?(\d+(?:\.\d+)?)", section_ref, text)

    def chapter_ref(m):
        num = m.group(1)
        if num in CHAPTERS:
            return record("chapter", "Chapter " + num, CHAPTERS[num],
                          "Chapter")
        unknown.append((fname, "Chapter " + num))
        return m.group(0)

    text = re.sub(r"Chapter (\d+)\b", chapter_ref, text)

    def appendix_ref(m):
        letter = m.group(1)
        return record("appendix", "Appendix " + letter, APPENDICES[letter],
                      "Appendix")

    text = re.sub(r"Appendix ([A-J])\b(?![.\w])", appendix_ref, text)

    def float_ref(kind, table, word):
        def repl(m):
            num = m.group(1).rstrip(".")
            trail = m.group(1)[len(num):]
            if num in table:
                return record(kind, f"{word} {num}", table[num], word) + trail
            unknown.append((fname, f"{word} {num}"))
            return m.group(0)
        return repl

    text = re.sub(r"Figure(?:\\,|~| )([A-J0-9][0-9.]*)",
                  float_ref("figure", FIGURES, "Figure"), text)
    text = re.sub(r"Table(?:\\,|~| )([A-J0-9][0-9.]*)",
                  float_ref("table", TABLES, "Table"), text)
    return text


def main():
    base = Path(sys.argv[1])
    for path in sorted((base / "chapters").glob("*.tex")):
        text = path.read_text(encoding="utf-8")
        text = sub_all(text, path.name)
        path.write_text(text, encoding="utf-8")

    out = Path("build")
    out.mkdir(exist_ok=True)
    (out / "refs_manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"{len(manifest)} references rewritten")
    from collections import Counter
    print(Counter(m["kind"] for m in manifest))
    if unknown:
        print("\nNOT REWRITTEN (no map entry):")
        for f, lit in sorted(set(unknown)):
            print(f"  {f}: {lit}")


if __name__ == "__main__":
    main()
