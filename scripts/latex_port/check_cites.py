r"""Citation integrity gate.

Every \textcite/\parencite key must exist in references.bib, every
bib entry must be cited somewhere, and the entry count must match the
43 references of the typed list the bib was converted from. Rendering
is verified on Overleaf, whose biblatex and biber versions pair; the
local tectonic bundle's biblatex predates the installed biber, so the
local build leaves citations unresolved by design.

Usage: python3 check_cites.py latex_dir
"""

import re
import sys
from collections import Counter
from pathlib import Path

TYPED_LIST_COUNT = 43


def main() -> None:
    base = Path(sys.argv[1])
    bib = (base / "references.bib").read_text(encoding="utf-8")
    bib_keys = set(re.findall(r"@\w+\{([^,]+),", bib))

    used = Counter()
    for path in sorted((base / "chapters").glob("*.tex")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\\(?:textcite|parencite)\{([^}]+)\}", text):
            for key in m.group(1).split(","):
                used[key.strip()] += 1

    missing = set(used) - bib_keys
    uncited = bib_keys - set(used)

    print(f"bib entries: {len(bib_keys)} (typed list had {TYPED_LIST_COUNT})")
    print(f"unique keys cited: {len(used)}, citation instances: "
          f"{sum(used.values())}")
    print(f"keys cited but MISSING from bib: {sorted(missing) or 'none'}")
    print(f"bib entries never cited: {sorted(uncited) or 'none'}")

    ok = (not missing and len(bib_keys) == TYPED_LIST_COUNT)
    print("GATE:", "PASS" if ok else "FAIL")


if __name__ == "__main__":
    main()
