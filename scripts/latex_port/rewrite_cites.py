r"""Rewrite the typed Harvard citations as biblatex commands.

Narrative citations ("Fumega and Gao (2026) report...") become
\textcite{fumega2026}; parenthetical ones ("(Maynez et al., 2020;
Ji et al., 2023)") become \parencite{maynez2020,ji2023}. The key map
is keyed on the first surname and the year, which is unambiguous in
this reference list (the two Wei entries differ by year).

07-references.tex is excluded: the typed list it holds is replaced by
\printbibliography. Anything citation-shaped that does not match the
map is reported, not rewritten, which leaves quoted material from
other papers alone.

Usage: python3 rewrite_cites.py latex_dir
"""

import re
import sys
from pathlib import Path

KEYS = {
    ("Anthropic", "2024"): "anthropic2024",
    ("Anthropic", "2026"): "anthropic2026",
    ("Chowdhury", "2026"): "chowdhury2026",
    ("Cohen", "2023"): "cohen2023",
    ("Davis", "2012"): "davis2012",
    ("Dhuliawala", "2024"): "dhuliawala2024",
    ("Du", "2023"): "du2023",
    ("European", "2024"): "edp2024",
    ("European", "2025"): "edp2025",
    ("Feng", "2024"): "feng2024",
    ("Fumega", "2026"): "fumega2026",
    ("Gao", "2023"): "gao2023",
    ("Heseltine", "2024"): "heseltine2024",
    ("Huang", "2024"): "huang2024",
    ("Jacobs", "2021"): "jacobs2021",
    ("Ji", "2023"): "ji2023",
    ("Joshi", "2020"): "joshi2020",
    ("Kalai", "2025"): "kalai2025",
    ("Kandpal", "2023"): "kandpal2023",
    ("Lewis", "2020"): "lewis2020",
    ("Liang", "2023"): "liang2023",
    ("Longpre", "2021"): "longpre2021",
    ("Mallen", "2023"): "mallen2023",
    ("Manakul", "2023"): "manakul2023",
    ("Maynez", "2020"): "maynez2020",
    ("Menick", "2022"): "menick2022",
    ("Nakano", "2021"): "nakano2021",
    ("Powers", "2002"): "powers2002",
    ("Rashkin", "2023"): "rashkin2023",
    ("Reiter", "1978"): "reiter1978",
    ("Schenk", "2024"): "schenk2024",
    ("Simhi", "2025"): "simhi2025",
    ("Smit", "2024"): "smit2024",
    ("Thellmann", "2024"): "thellmann2024",
    ("Törnberg", "2025"): "tornberg2025",
    ("Tyen", "2024"): "tyen2024",
    ("UNECE", "2025"): "unece2025",
    ("Wei", "2022"): "wei2022",
    ("Wei", "2024"): "wei2024",
    ("Williamson", "2012"): "williamson2012",
    ("Yao", "2023"): "yao2023",
    ("Yung", "2022"): "yung2022",
    ("Zhu", "2026"): "zhu2026",
}

SURNAMES = sorted({s for s, _ in KEYS}, key=len, reverse=True)
NAME_ALT = "|".join(re.escape(s) for s in SURNAMES)

# one item inside a parenthetical group: "Maynez et al., 2020",
# "Davis, Kingsbury and Merry, 2012", "Heseltine and Clemm von
# Hohenberg, 2024", "European Data Portal and Capgemini Invent, 2025",
# with pandoc's \, thin spaces tolerated
ITEM_RE = re.compile(
    r"^(" + NAME_ALT + r")"
    r"(?:(?:\\,|\s)+et(?:\\,|\s)+al\.?"
    r"|[\w\s,.'À-ſ-]*?)?"
    r",(?:\\,|\s)*((?:19|20)\d\d)$")

PAREN_RE = re.compile(r"\(([^()]{0,200}?(?:19|20)\d\d)\)")

NARRATIVE_RE = re.compile(
    r"\b(" + NAME_ALT + r")"
    r"((?:\\,|\s)+et(?:\\,|\s)+al\.?"
    r"|(?:,\s+[A-Z][\wÀ-ſ'-]+)*(?:,?\s+and\s+[A-Z][\w\sÀ-ſ'-]+?)?"
    r"|\s+Data\s+Portal\s+and\s+Capgemini\s+Invent)?"
    r"\s+\(((?:19|20)\d\d)\)")

unmatched = []
counts = {"parencite": 0, "textcite": 0}


def rewrite(text: str, fname: str) -> str:
    def paren_repl(m):
        inner = m.group(1)
        items = [i.strip() for i in inner.split(";")]
        keys = []
        for item in items:
            im = ITEM_RE.match(item.replace(" ", " ").strip())
            if not im or (im.group(1), im.group(2)) not in KEYS:
                unmatched.append((fname, "(" + inner + ")"))
                return m.group(0)
            keys.append(KEYS[(im.group(1), im.group(2))])
        counts["parencite"] += 1
        return "\\parencite{" + ",".join(keys) + "}"

    text = PAREN_RE.sub(paren_repl, text)

    def narrative_repl(m):
        surname, year = m.group(1), m.group(3)
        if (surname, year) not in KEYS:
            unmatched.append((fname, m.group(0)))
            return m.group(0)
        counts["textcite"] += 1
        return "\\textcite{" + KEYS[(surname, year)] + "}"

    text = NARRATIVE_RE.sub(narrative_repl, text)
    return text


def main() -> None:
    base = Path(sys.argv[1])
    for path in sorted((base / "chapters").glob("*.tex")):
        if path.name == "07-references.tex":
            continue
        text = path.read_text(encoding="utf-8")
        text = rewrite(text, path.name)
        path.write_text(text, encoding="utf-8")
    print(f"parenthetical groups rewritten: {counts['parencite']}")
    print(f"narrative citations rewritten: {counts['textcite']}")
    if unmatched:
        print("\nNOT REWRITTEN (report, do not guess):")
        for f, s in sorted(set(unmatched)):
            print(f"  {f}: {s[:110]}")


if __name__ == "__main__":
    main()
