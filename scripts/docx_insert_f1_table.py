"""Re-insert the Appendix F baselines table, which the 1 August consolidation
deleted, leaving the `Table F.1` caption pointing at nothing.

The table body is recovered verbatim from the pre-consolidation archive so the
styling matches the rest of the document. Two cells are corrected to the
907/4,144 convention before insertion. String surgery only.
"""
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

SRC_ARCHIVE = ("/Users/benjyb/Desktop/MscProject/Dissertation/archive/"
               "Dissertation_20260801_1226_pre_F_consolidate.docx")

# (old, new) cell corrections, applied to the recovered table XML.
CELL_FIXES = [
    ("81.8%", "81.9%"),          # always-yes over all 36 countries
    ("4,146", "4,144"),          # its denominator, answer_shape convention
    ("59.3%", "59.4%"),          # always-yes over the held-out eight
    ("909", "907"),              # its denominator
]


def read(path):
    with zipfile.ZipFile(path) as z:
        return z.read("word/document.xml").decode("utf-8")


def find_table(xml, marker="Always-yes, all 36 countries"):
    for m in re.finditer(r"<w:tbl>.*?</w:tbl>", xml, re.S):
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", m.group(0), re.S))
        if marker in text:
            return m.group(0)
    return None


def main():
    src, dst = sys.argv[1], sys.argv[2]
    master = read(src)
    archive = read(SRC_ARCHIVE)

    tbl = find_table(archive)
    if not tbl:
        print("ABORT: baselines table not found in the archive")
        return 1
    print(f"recovered table: {len(tbl)} bytes, "
          f"{tbl.count('<w:tr')} rows, {tbl.count('<w:p ') + tbl.count('<w:p>')} paragraphs")

    before = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", tbl, re.S))
    for old, new in CELL_FIXES:
        if old not in tbl:
            print(f"ABORT: cell value {old!r} not present in the recovered table")
            return 1
        tbl = tbl.replace(old, new, 1)
    after = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", tbl, re.S))
    print("corrected cells:")
    for old, new in CELL_FIXES:
        print(f"  {old} -> {new}")

    # guard: this table must not already be in the master
    if find_table(master):
        print("ABORT: a baselines table is already present in the master")
        return 1

    # locate the `Table F.1:` caption paragraph (not the TOC entry)
    paras = list(re.finditer(r"<w:p(?:\s[^>]*)?>.*?</w:p>", master, re.S))
    anchor = None
    for m in paras:
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", m.group(0), re.S)).strip()
        if t.startswith("Table F.1:") and "PAGEREF" not in m.group(0):
            anchor = m
            break
    if anchor is None:
        print("ABORT: `Table F.1:` caption not found")
        return 1

    # an empty paragraph must follow a table, or Word complains when a table
    # is the last block before a heading; the caption's own paragraph mark is
    # reused by keeping the existing empty paragraph after the insertion point.
    out = master[:anchor.end()] + tbl + master[anchor.end():]

    checks = {}
    ro = re.match(r"^.*?<w:body>", master, re.S).group(0)
    rn = re.match(r"^.*?<w:body>", out, re.S).group(0)
    checks["root+header byte-identical"] = ro == rn
    mo = re.search(r'mc:Ignorable="([^"]*)"', master).group(1)
    mn = re.search(r'mc:Ignorable="([^"]*)"', out).group(1)
    checks["mc:Ignorable unchanged"] = mo == mn
    checks["no xmlns:ns prefixes"] = "xmlns:ns" not in out
    checks["exactly one table added"] = (
        out.count("<w:tbl>") == master.count("<w:tbl>") + 1)
    checks["table open/close balanced"] = (
        out.count("<w:tbl>") == out.count("</w:tbl>"))
    checks["<w:p> delta matches the table"] = (
        len(re.findall(r"<w:p(?:\s[^>]*)?>", out))
        - len(re.findall(r"<w:p(?:\s[^>]*)?>", master))
        == len(re.findall(r"<w:p(?:\s[^>]*)?>", tbl)))
    rids_o = set(re.findall(r'r:(?:id|embed)="(rId\d+)"', master))
    rids_n = set(re.findall(r'r:(?:id|embed)="(rId\d+)"', out))
    checks["no new rId references"] = rids_n <= rids_o
    docpr = re.findall(r'<wp:docPr id="(\d+)"', out)
    checks["no duplicate wp:docPr id"] = len(docpr) == len(set(docpr))
    # the recovered table was itself inserted in red by an earlier session;
    # restoring it faithfully means its red runs come back with it.
    tbl_red = tbl.count('<w:color w:val="FF0000"/>')
    checks["red runs added == the table's own"] = (
        out.count('<w:color w:val="FF0000"/>')
        - master.count('<w:color w:val="FF0000"/>') == tbl_red)
    print(f"\n  (the recovered table carries {tbl_red} red runs of its own)")

    print("\nVERIFY")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    if not all(checks.values()):
        print("\nABORTED: nothing written")
        return 1

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(
            dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = out.encode("utf-8")
            zout.writestr(item, data)
    with zipfile.ZipFile(dst) as z:
        bad = z.testzip()
        print(f"  {'PASS' if bad is None else 'FAIL'}  zip testzip()")
        ET.fromstring(z.read("word/document.xml"))
        print("  PASS  document.xml parses")
    print(f"\nwrote {dst}")
    return 0


sys.exit(main())
