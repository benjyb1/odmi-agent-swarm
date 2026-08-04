r"""Verify every \ref resolves to the target the docx pointed at.

A \ref that resolves to the wrong section reads as a perfectly
plausible number in the PDF, so this compares each resolved number
against the literal string it replaced in the frozen docx, from the
manifest rewrite_refs.py emitted. Differences are listed and must each
be an intended renumber (chapter-level figure numbering, the appendix
letter change, the healed duplicate 2.1 / missing 4.6.1 / missing J.15
gaps) rather than a wrong target.

Also checks: zero undefined references and zero multiply-defined
labels in the log, and zero surviving literal references in the prose.

Usage: python3 check_refs.py latex_dir manifest.json [--log build.log]
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path


def aux_labels(base: Path) -> dict:
    # \include splits the labels across main.aux and chapters/*.aux
    labels = {}
    dupes = []
    for aux_path in [base / "main.aux", *sorted((base / "chapters").glob("*.aux"))]:
        if not aux_path.exists():
            continue
        for m in re.finditer(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}",
                             aux_path.read_text(encoding="utf-8")):
            if m.group(1) in labels:
                dupes.append(m.group(1))
            labels[m.group(1)] = m.group(2)
    return labels, dupes


def main() -> None:
    base = Path(sys.argv[1])
    manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    labels, dupes = aux_labels(base)

    if dupes:
        print("MULTIPLY-DEFINED LABELS:", dupes)

    undefined, same, renumbered = [], [], []
    for entry in manifest:
        label = entry["label"]
        if label not in labels:
            undefined.append(entry)
            continue
        resolved = labels[label]
        lit_num = re.sub(r"^(§\s?|Chapter |Appendix |Figure |Table )", "",
                         entry["literal"])
        if resolved == lit_num:
            same.append(entry)
        else:
            renumbered.append((entry, resolved))

    print(f"references checked: {len(manifest)}")
    print(f"  resolve to the docx number unchanged: {len(same)}")
    print(f"  renumbered: {len(renumbered)}")
    print(f"  UNDEFINED: {len(undefined)}")
    for e in undefined:
        print("   ", e)
    print("\nrenumbered, docx -> latex (each must be an intended renumber):")
    seen = Counter()
    for e, resolved in renumbered:
        key = (e["literal"], resolved, e["label"])
        seen[key] += 1
    for (lit, resolved, label), n in sorted(seen.items()):
        print(f"  {lit} -> {resolved}  ({label}) x{n}")

    # surviving literals in the prose (quoted paper tables are allowed)
    allowed = {"Table 2", "Table 3", "Table 7"}
    survivors = []
    for path in sorted((base / "chapters").glob("*.tex")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(
                r"(§\s?\d|Chapter \d|Appendix [A-J]\b(?![.\w])"
                r"|Figure(?:\\,|~| )[A-J0-9][0-9.]*"
                r"|Table(?:\\,|~| )[A-J0-9][0-9.]*)", text):
            lit = m.group(0).replace("\\,", " ").replace("~", " ")
            if lit.rstrip(".") in allowed:
                continue
            survivors.append((path.name, lit,
                              text[max(0, m.start() - 40):m.start()]))
    print(f"\nsurviving literal references: {len(survivors)}")
    for name, lit, ctx in survivors:
        print(f"  {name}: {lit!r}  after ...{ctx[-40:]!r}")


if __name__ == "__main__":
    main()
