r"""Polish pandoc's output into hand-written-looking LaTeX.

- \textquotesingle becomes a plain apostrophe.
- The tick and cross glyphs of the Table 2.2 scorecard, and the stray
  maths symbols in the appendix, become commands: Latin Modern has no
  U+2713/U+2717 and they rendered as missing-character boxes.
- Longtable column specs lose pandoc's \real{} arithmetic in favour of
  a single L/C column type defined in main.tex.
- Header cells lose their \begin{minipage}[b]{\linewidth} wrappers.

Usage: python3 polish_source.py latex_dir
"""

import re
import sys
from pathlib import Path

CHARS = {
    "✓": "$\\checkmark$",
    "✗": "$\\times$",
    "≥": "$\\geq$",
    "≠": "$\\neq$",
    "→": "$\\rightarrow$",
}


def polish(text: str) -> str:
    text = text.replace("\\textquotesingle{}", "'")
    text = re.sub(r"\\textquotesingle\s*", "'", text)

    for ch, cmd in CHARS.items():
        text = text.replace(ch, cmd)

    # >{\raggedright\arraybackslash}p{(\linewidth - 8\tabcolsep) * \real{0.16}}
    text = re.sub(
        r">\{\\raggedright\\arraybackslash\}p\{\(\\linewidth - "
        r"\d+\\tabcolsep\) \* \\real\{([0-9.]+)\}\}",
        r"L{\1}", text)
    text = re.sub(
        r">\{\\centering\\arraybackslash\}p\{\(\\linewidth - "
        r"\d+\\tabcolsep\) \* \\real\{([0-9.]+)\}\}",
        r"C{\1}", text)

    # \begin{minipage}[b]{\linewidth}\raggedright\nX\n\end{minipage}
    # Cells whose docx source held two stacked paragraphs (a rate over
    # its k/n) carry an internal \\ inside the minipage; that must
    # become \newline, or the \\ turns into a row break and scrambles
    # the table once the minipage is gone.
    def unwrap(m):
        cell = m.group(1).strip()
        cell = cell.replace("\\strut", "")
        cell = re.sub(r"\s*\\\\\s*", "\\\\newline ", cell)
        return cell.strip()

    text = re.sub(
        r"\\begin\{minipage\}\[[bt]\]\{\\linewidth\}(?:\\raggedright|"
        r"\\centering)?\s*\n(.*?)\n?\\end\{minipage\}",
        unwrap, text, flags=re.S)
    return text


def main() -> None:
    base = Path(sys.argv[1])
    for path in sorted((base / "chapters").glob("*.tex")):
        text = path.read_text(encoding="utf-8")
        new = polish(text)
        if new != text:
            path.write_text(new, encoding="utf-8")
            print(f"polished {path.name}")
    leftovers = []
    for path in sorted((base / "chapters").glob("*.tex")):
        t = path.read_text(encoding="utf-8")
        for probe in ("\\real{", "textquotesingle", "minipage", "✓", "✗"):
            n = t.count(probe)
            if n:
                leftovers.append((path.name, probe, n))
    print("leftovers:", leftovers or "none")


if __name__ == "__main__":
    main()
