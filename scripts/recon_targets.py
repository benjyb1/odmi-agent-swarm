"""Report how each edit target is represented inside word/document.xml.

Word splits a sentence across runs for reasons that have nothing to do with the
text, so a phrase that reads as one string in the extracted prose may be three
<w:t> elements. String surgery needs to know which before it edits anything.

Usage:
    python3 scripts/recon_targets.py <docx>
"""

from __future__ import annotations

import re
import sys
import zipfile

TARGETS = [
    ("crucially", "Crucially, a large share of the questions ask"),
    ("evidence_based", "more evidence based"),
    ("its_just", "or if it's just the evidence that is absent"),
    ("its_just_curly", "or if it’s just the evidence that is absent"),
    ("wouldve", "would've been a stronger test"),
    ("wouldve_curly", "would’ve been a stronger test"),
    ("by_construction", "by construction and a generative assessor cannot"),
    ("fig23_caption", "What each prior method adds and misses"),
    ("makeup", "Outcome makeup per country"),
    ("keywords_q", "Do you monitor search key words?”."),
    ("keywords_q2", "Do you monitor search key words?\"."),
    ("cost_031", "£0.31 in Finland"),
    ("failure_modes_semi", "multiple failure modes; abstention tracking maturity"),
    ("per_token", "computed from published per-token rates and no figure"),
    ("nb_hyphen", "lower‑resource"),
    ("repro_experiments", "Reproduced in full from the Experiments section for reference."),
    ("repro_42", "Reproduced in full from §4.2 for reference."),
    ("baselines_result", "The baselines the evaluation result is read against."),
    ("pp131", "pp. 131–184"),
    ("pp291", "pp. 291–308"),
    ("icml", "(published ICML 2024)"),
    ("h2_caption_96", "96 in total"),
]


def main():
    path = sys.argv[1]
    with zipfile.ZipFile(path) as z:
        doc = z.read("word/document.xml").decode("utf-8")

    # Every <w:t> body, with its span in the raw xml.
    runs = [(m.start(1), m.end(1), m.group(1))
            for m in re.finditer(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", doc, re.S)]

    print(f"document.xml {len(doc):,} chars, {len(runs):,} <w:t> elements\n")
    for name, needle in TARGETS:
        whole = [(s, e, t) for s, e, t in runs if needle in t]
        if whole:
            print(f"{name:22s} SINGLE-RUN x{len(whole)}")
            for s, e, t in whole[:3]:
                print(f"{'':24s} run text: {t[:110]!r}")
            continue
        # Not inside one run. Show the flattened neighbourhood so the split is visible.
        flat = "".join(t for _, _, t in runs)
        if needle in flat:
            i = flat.find(needle)
            # find which runs cover it
            pos, covering = 0, []
            for s, e, t in runs:
                if pos + len(t) > i and pos < i + len(needle):
                    covering.append(t)
                pos += len(t)
            print(f"{name:22s} SPLIT across {len(covering)} runs")
            for c in covering:
                print(f"{'':24s} {c[:90]!r}")
        else:
            print(f"{name:22s} NOT PRESENT")
    print()

    # Double spaces, by run.
    ds = [(s, t) for s, _, t in runs if "  " in t]
    print(f"runs containing a double space: {len(ds)}")
    total = sum(t.count("  ") for _, t in ds)
    print(f"double-space occurrences: {total}")


if __name__ == "__main__":
    main()
