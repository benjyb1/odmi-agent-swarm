"""Wrap every coloured run in the docx in ASCII sentinels.

Pandoc discards character colour with no warning. The colour channels are
how the migration proves no working note silently became body prose, so
before conversion every coloured run is wrapped in plain-text sentinels
that survive pandoc:

    C00000 (Claude)          @@CL@@ ... @@/CL@@
    FF0000, EE0000 (Benjy)   @@CC@@ ... @@/CC@@

String surgery on word/document.xml only. Parsing and re-serialising with
ElementTree renames namespace prefixes and breaks mc:Ignorable, after
which Word refuses the file, so the XML is edited as a string.

Usage: python3 sentinel_prepass.py in.docx out.docx
"""

import re
import sys
import zipfile

CHANNELS = {
    "C00000": ("@@CL@@", "@@/CL@@"),
    "FF0000": ("@@CC@@", "@@/CC@@"),
    "EE0000": ("@@CC@@", "@@/CC@@"),
}

RUN_RE = re.compile(r"<w:r\b[^>]*>.*?</w:r>", re.S)
WT_OPEN_RE = re.compile(r"(<w:t(?:\s[^>]*)?>)")


def wrap_run(run: str) -> str:
    rpr = re.search(r"<w:rPr>.*?</w:rPr>", run, re.S)
    if not rpr:
        return run
    colour = re.search(r'<w:color[^>]*w:val="([0-9A-Fa-f]{6})"', rpr.group(0))
    if not colour or colour.group(1).upper() not in CHANNELS:
        return run
    opens = list(WT_OPEN_RE.finditer(run))
    closes = [m for m in re.finditer(r"</w:t>", run)]
    if not opens or not closes:
        return run  # coloured run with no text, e.g. a drawing
    start, end = CHANNELS[colour.group(1).upper()]
    first_ins = opens[0].end()
    last_ins = closes[-1].start()
    return run[:first_ins] + start + run[first_ins:last_ins] + end + run[last_ins:]


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    zin = zipfile.ZipFile(src)
    xml = zin.read("word/document.xml").decode("utf-8")

    wrapped = 0

    def repl(m: re.Match) -> str:
        nonlocal wrapped
        out = wrap_run(m.group(0))
        if out != m.group(0):
            wrapped += 1
        return out

    xml = RUN_RE.sub(repl, xml)

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = xml.encode("utf-8")
            zout.writestr(item, data)

    print(f"wrapped {wrapped} coloured runs")


if __name__ == "__main__":
    main()
