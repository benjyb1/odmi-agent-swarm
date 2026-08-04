r"""Size the dense tables so nothing runs into the margin.

Word squeezed these tables to fit; LaTeX at 11pt does not. Body
tables that overflow get \small, the ten-column harvest table and the
big appendix registers get \footnotesize, matching how wide tables
are normally set in a thesis. Long underscore identifiers in the
appendix experiment register gain \allowbreak so they can wrap
instead of running 100pt into the margin.

Usage: python3 size_tables.py latex_dir
"""

import re
import sys
from pathlib import Path

SIZES = {
    "tab:criteria": "small",
    "tab:prior-work": "footnotesize",
    "tab:answer-shapes": "small",
    "tab:harvests": "footnotesize",
    "tab:metrics": "small",
    "tab:four-ways": "small",
    "tab:abstention-reasons": "small",
    "tab:attributability": "small",
    "tab:strata": "small",
    "tab:replicates": "small",
    "tab:ablation": "small",
    "tab:cost": "small",
    "tab:scorecard": "footnotesize",
    "tab:reformulation": "small",
    "tab:failure-register": "footnotesize",
    "tab:abstention-codes": "footnotesize",
    "tab:fp-audit": "footnotesize",
    "tab:experiments": "footnotesize",
    "tab:out-of-reach": "footnotesize",
    "tab:prior-work-full": "footnotesize",
    "tab:baselines": "small",
    "tab:question-bank": "footnotesize",
    "tab:harvest-register": "footnotesize",
    "tab:catalogue-metrics": "footnotesize",
    "tab:dev-by-country": "small",
    "tab:dev-by-dimension": "small",
}


def main() -> None:
    base = Path(sys.argv[1])
    wrapped = 0
    for path in sorted((base / "chapters").glob("*.tex")):
        text = path.read_text(encoding="utf-8")

        pieces = re.split(r"(\\begin\{longtable\}.*?\\end\{longtable\})",
                          text, flags=re.S)
        out = []
        for piece in pieces:
            if piece.startswith("\\begin{longtable}"):
                lm = re.search(r"\\label\{(tab:[^}]+)\}", piece)
                size = SIZES.get(lm.group(1)) if lm else None
                # identifiers wrap after underscores inside tables
                piece = piece.replace("\\_", "\\_\\allowbreak ")
                if size:
                    piece = "{\\" + size + "\n" + piece + "\n}"
                    wrapped += 1
            out.append(piece)
        path.write_text("".join(out), encoding="utf-8")
    print(f"tables wrapped with a size: {wrapped}")


if __name__ == "__main__":
    main()
