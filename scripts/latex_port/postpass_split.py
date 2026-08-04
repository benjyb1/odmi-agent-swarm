r"""Post-process pandoc output and split it into chapter files.

Takes the single .tex body pandoc produced from the sentinel-wrapped
docx and:

  1. merges adjacent same-channel sentinels so each contiguous coloured
     block is one @@CL@@...@@/CL@@ or @@CC@@...@@/CC@@ span;
  2. strips Word bookmark anchors (\phantomsection\label{_Toc...}) that
     mean nothing outside Word;
  3. removes empty \chapter{} headings, which are stray formatting in the
     docx that would otherwise split the Introduction into fragments;
  4. cuts Word's generated contents list (the "Table of Contents" heading
     and its \hyperref entry lines): \tableofcontents regenerates it, and
     leaving it in would ship a stale, hand-numbered contents page;
  5. captures everything before the first \chapter as front matter, which
     pandoc would otherwise leave to be discarded;
  6. splits the rest into chapters/NN-slug.tex.

Usage: python3 postpass_split.py body.tex outdir
"""

import re
import sys
from pathlib import Path

EXPECTED = [
    "Introduction",
    "Background and Related Work",
    "Approach and Methodology",
    "Results",
    "Discussion",
    "Conclusion",
    "References",
    "Appendix",
]


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def main() -> None:
    body = Path(sys.argv[1]).read_text(encoding="utf-8")
    outdir = Path(sys.argv[2])
    (outdir / "chapters").mkdir(parents=True, exist_ok=True)

    # 1. merge adjacent sentinels (whitespace between spans stays coloured)
    for ch in ("CL", "CC"):
        pat = re.compile(r"@@/" + ch + r"@@(\s*)@@" + ch + r"@@")
        prev = None
        while prev != body:
            prev = body
            body = pat.sub(r"\1", body)

    # 2. Word bookmark anchors
    body = re.sub(r"\\protect\\phantomsection\\label\{_[^}]*\}\{\}", "", body)
    body = re.sub(r"\\phantomsection\\label\{_[^}]*\}", "", body)
    body = re.sub(r"\\label\{_(?:Toc|Ref|Hlk)[^}]*\}", "", body)

    # 2b. headings with trailing spaces in Word make pandoc emit
    #     \texorpdfstring{Title }{Title }; collapse when both args match
    def collapse_texorpdf(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        return a.strip() if a.strip() == b.strip() else m.group(0)
    body = re.sub(r"\\texorpdfstring\{([^{}]*)\}\{([^{}]*)\}",
                  collapse_texorpdf, body)
    body = re.sub(r"\\(chapter|section|subsection)\{([^{}]*?)\s+\}",
                  r"\\\1{\2}", body)

    # 3. Word's generated contents list: the literal heading plus every
    #    entry line, which pandoc renders as a bare \hyperref paragraph
    body, n_toc = re.subn(r"^\\hyperref\[[^\]]*\]\{.*\}\s*$", "", body,
                          flags=re.M)
    body = re.sub(r"^Table of Contents\s*$", "", body, flags=re.M)

    # 4. empty chapter headings are stray formatting, not chapters
    body, n_empty = re.subn(r"^\\chapter\{\}(?:\\label\{[^}]*\})?\s*$", "",
                            body, flags=re.M)

    # 5/6. split on real \chapter lines
    parts = re.split(r"^(\\chapter\{[^}]+\}.*)$", body, flags=re.M)
    front = parts[0]
    files = [("00-front-matter.tex", front)]
    seq = 1
    for i in range(1, len(parts), 2):
        heading = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        title = re.search(r"\\chapter\{([^}]+)\}", heading).group(1)
        name = f"{seq:02d}-{slug(title)}.tex"
        files.append((name, heading + content))
        seq += 1

    for name, text in files:
        path = outdir / "chapters" / name
        path.write_text(text.strip() + "\n", encoding="utf-8")
        opens_cl, closes_cl = text.count("@@CL@@"), text.count("@@/CL@@")
        opens_cc, closes_cc = text.count("@@CC@@"), text.count("@@/CC@@")
        bal = "OK" if (opens_cl == closes_cl and opens_cc == closes_cc) else "UNBALANCED"
        print(f"{name}: {len(text.split())} words, "
              f"CL {opens_cl}/{closes_cl} CC {opens_cc}/{closes_cc} {bal}")

    print(f"empty chapter headings folded: {n_empty}")
    print(f"generated TOC entry lines cut: {n_toc}")
    titles = [re.search(r"\\chapter\{([^}]+)\}", t).group(1)
              for _, t in files[1:]]
    missing = [t for t in EXPECTED if t not in titles]
    extra = [t for t in titles if t not in EXPECTED]
    print("chapters:", titles)
    if missing:
        print("MISSING expected chapters:", missing)
    if extra:
        print("UNEXPECTED chapters:", extra)


if __name__ == "__main__":
    main()
