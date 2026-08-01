"""Red-only number corrections on Dissertation.docx by string surgery.

Never parses and re-serialises document.xml: ElementTree renames namespace
prefixes and Word rejects the file. Operates on the raw XML text, splices runs,
and rewrites the zip entry byte for byte.

Usage:  python docx_surgery.py <in.docx> <out.docx> [--notes]
"""
import re
import shutil
import sys
import zipfile

RED = '<w:color w:val="FF0000"/>'
# Benjy, 1 Aug: number corrections go in BLACK, as body text. Only the
# CC notes stay red, because those are review marks rather than values.
SWAP_RED = False

# (label, exact plain text to find, replacement) -- replacement is emitted as a
# red run; surrounding text keeps its own formatting.
SWAPS = [
    ("A1  coverage in §1.4", "55.4\u202f% of questions", "55.6\u202f% of questions"),
    ("A2  §4.1 committed-yes count",
     "The run contains 94 of them, 25.5% of all 368 negative golds and 51.1% of the 184",
     "The run contains 91 of them, 24.7% of all 368 negative golds and 49.5% of the 184"),
    ("A4  Table 5.1 count-band", "0 of 16 count-band correct",
     "1 of 16 count-band correct"),
    ("A5a §4.5 Quality without catalogue", "answers Quality at 81.5% when it commits",
     "answers Quality at 80.3% when it commits"),
    ("A5b §5.3 Quality without catalogue", "committing at 0.815 once its computable",
     "committing at 0.803 once its computable"),
    ("A6  §4.1 catalogue cells",
     "Across the thirty-two measurable cells the recompute agrees with the published key on eighteen, 56% agreement",
     "Across the thirty-six measurable cells the recompute agrees with the published key on eighteen, 50% agreement"),
    ("A7  §4.1 divergence", "disagree on 44% of the measurable cells",
     "disagree on 50% of the measurable cells"),
    ("A9  §4.2 sub-floor counts",
     "Of the 161 that are scoreable, 73 carry a yes gold and 88 carry a no gold. Around a fifth of the yes answers are correct, against 73 of the 88 no answers.",
     "Of the 162 that are scoreable, 73 carry a yes gold and 89 carry a no gold. Around a quarter of the yes answers are correct, against 79 of the 89 no answers."),
    ("A13 §4.8 committed pair cost", "cost £0.28 and required 2.4 attempts",
     "cost £0.26 and required 2.2 attempts"),
    ("A14 §4.8 abstained premium", "an abstained pair costs 50% more than a committed one does",
     "an abstained pair costs 58% more than a committed one does"),
    ("A16 Table 5.2 catalogue questions",
     "Quality, computable from the catalogue, 13 of 29 (Q2, Q12, Q13, Q16 to Q18, Q21, Q22, Q25 to Q29)",
     "Quality, computable from the catalogue, 9 of 29 (Q12, Q13, Q16 to Q18, Q21, Q22, Q25, Q27)"),
    ("B4a §3.7 negative golds", "1,144 question-country pairs and 370 binary negative golds, 262 of which sit in stratum A",
     "1,144 question-country pairs and 368 binary negative golds, 261 of which sit in stratum A"),
    ("B5  §3.7 Bosnia no-share", "84.9% in Bosnia", "84.8% in Bosnia"),
    ("C5  §4.1 Montenegro recompute", "where the recompute reads 71%",
     "where the recompute reads 70%"),

    # --- convention-dependent: wrong-yes 91/368 ---
    ("B1a Table 4.7.1 researcher", "13.3% (49/368)", "12.5% (46/368)"),
    ("B1b Table 4.7.1 verifier", "24.2% (89/368)", "23.4% (86/368)"),
    ("B1c Table 4.7.1 trio", "25.5% (94/368)", "24.7% (91/368)"),
    ("B1d Table 4.7.1 corroborative", "28.0% (103/368)", "27.2% (100/368)"),
    ("B1e Table 4.7.1 closed book", "36.1% (133/368)", "13.9% (51/368)"),
    ("B2a Table 4.4.1 stratum A all", "22.2% (58/261)", "21.1% (55/261)"),
    ("B2b Table 4.4.1 stratum A committed", "45.0% (58/129)", "42.6% (55/129)"),
    ("B2c §4.4 stratum rates in prose",
     "at 0.222 against 0.336 in aggregate and 0.450 against 0.655 on committed negatives",
     "at 0.211 against 0.336 in aggregate and 0.426 against 0.655 on committed negatives"),
    ("B2d §4.4 wrongly credited", "Stratum A accrues 58 wrongly credited answers against stratum B's 36",
     "Stratum A accrues 55 wrongly credited answers against stratum B's 36"),
    ("B2e Table 5.1 subgroup row", "stratum A FPR 0.222 vs B 0.336",
     "stratum A FPR 0.211 vs B 0.336"),
    ("B2f §4.4 within-stratum spread",
     "spanning 0.128 to 0.342 inside stratum A and 0.222 to 0.483 inside stratum B against a gap of 0.114",
     "spanning 0.128 to 0.301 inside stratum A and 0.222 to 0.483 inside stratum B against a gap of 0.125"),
    ("B2g §4.4 North Macedonia", "North Macedonia is the exception, at 34.2%",
     "North Macedonia is the exception, at 30.1%"),
    ("B11 §4.4 committed-only rho", "the correlation with maturity rises to 0.83",
     "the correlation with maturity rises to 0.90"),
    ("B3a Table 4.5.1 Impact FPR", "26.4% [20, 34]", "25.7% [19, 33]"),
    ("B3b Table 4.5.1 Quality FPR", "18.8% [10, 32]", "14.6% [7, 27]"),
    ("B3c Table 4.5.1 all-dimensions FPR", "25.5% [21, 30]", "24.7% [21, 29]"),
    ("B8  Table 4.1.2 closed-book coverage", "76.7%878/1,144", "75.6%865/1,144"),
]

# CC notes: (anchor sentence the note follows, note text)
NOTES = [
    ("reaching 100% near 0.88, on nine answers",
     "[CC: this point does not reproduce. At 0.88 the yes class holds 82 committed "
     "answers at 98.8%; it first reaches 100% at 0.95, on 42 answers. Recomputed "
     "from data/odmi.db over the EXP-36 committed set. Either restate it as those "
     "figures or cut the clause.]"),
    ("from £0.31 in Finland to £0.39 in Bosnia and Herzegovina",
     "[CC: Finland is the cheapest at £0.30, but the most expensive is Bulgaria at "
     "£0.385, not Bosnia at £0.348. Recomputed from the snippet-picker usage log. "
     "Swapping the country breaks the next sentence, which uses Bosnia for the "
     "abstention contrast, so this needs rewording rather than a number change.]"),
    ("The disagreements do not all run in the same direction, so this is not a case of countries systematically inflating their score.",
     "[CC: true but it reads as balance. The split is 11 overstatements against 4 "
     "understatements, with 3 not band-comparable. Consider naming the 11 to 4.]"),
    ("Commit rate 0.237, 0.391, 0.468 and commit-accuracy 0.649, 0.689, 0.726 across the three arms",
     "[CC: every EXP-28 researcher row is claude-sonnet-5, and the canonical dedup "
     "leaves only the researcher-only arm, so these three arms cannot be recomputed. "
     "Table 4.7.1 supersedes this row at n=1,144 on Sonnet 4.6. Drop the row, or "
     "mark it Sonnet 5 and historical.]"),
    ("Table F.1: The baselines any result has to clear.",
     "[CC: there is no table under this caption. The consolidation on 1 Aug deleted "
     "both renderings, and §2.3 now points at Table F.1. Recomputed values for the "
     "rows: always-yes held-out eight 59.4% (539/907); always-yes all 36 countries "
     "81.9% (3,393/4,144); majority class on the dev battery 50.6% (154 binary "
     "golds, majority is no); closed book 42.9% against a 47.3% floor (489 and 539 "
     "of 1,139); researcher alone 26.6% coverage at 74.3% commit-accuracy on the "
     "held-out 1,144.]"),
]

NORM = {" ": " ", "‑": "-", "‘": "'", "’": "'",
        "“": '"', "”": '"', "–": "-", "—": "-"}


def norm(s):
    for a, b in NORM.items():
        s = s.replace(a, b)
    return s


def runs_of(para):
    """[(start, end, full_run_xml, text_start, text_end)] for each <w:t> in order."""
    out = []
    for m in re.finditer(r"<w:r(?:\s[^>]*)?>.*?</w:r>", para, re.S):
        r = m.group(0)
        t = re.search(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", r, re.S)
        if t:
            out.append((m.start(), m.end(), r, t.start(1), t.end(1)))
    return out


def rpr_red(run):
    """Return the run's rPr with a red colour forced in."""
    m = re.search(r"<w:rPr>(.*?)</w:rPr>", run, re.S)
    if not m:
        return f"<w:rPr>{RED}</w:rPr>"
    inner = re.sub(r"<w:color[^/]*/>", "", m.group(1))
    inner = re.sub(r"<w:color[^>]*>.*?</w:color>", "", inner, flags=re.S)
    return f"<w:rPr>{inner}{RED}</w:rPr>"


def make_run(template, text, red=True):
    rpr = rpr_red(template) if red else (
        re.search(r"<w:rPr>.*?</w:rPr>", template, re.S).group(0)
        if "<w:rPr>" in template else "")
    esc = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return f'<w:r>{rpr}<w:t xml:space="preserve">{esc}</w:t></w:r>'


def apply_swap(xml, find, repl, report):
    """Replace `find` with a red run carrying `repl`, inside one paragraph."""
    nfind = norm(find)
    for pm in re.finditer(r"<w:p(?:\s[^>]*)?>.*?</w:p>", xml, re.S):
        para = pm.group(0)
        rs = runs_of(para)
        if not rs:
            continue
        concat = "".join(r[2][r[3]:r[4]] for r in rs)
        plain = norm(re.sub(r"<[^>]+>", "", concat))
        idx = plain.find(nfind)
        if idx < 0:
            continue
        # map plain offsets back to (run, offset)
        pos, spans = 0, []
        for i, r in enumerate(rs):
            txt = norm(re.sub(r"<[^>]+>", "", r[2][r[3]:r[4]]))
            spans.append((pos, pos + len(txt), i, txt))
            pos += len(txt)
        end = idx + len(nfind)
        touched = [s for s in spans if s[0] < end and s[1] > idx]
        if not touched:
            continue
        first, last = touched[0], touched[-1]
        pre = first[3][: idx - first[0]]
        post = last[3][end - last[0]:]
        tmpl = rs[first[2]][2]
        new_runs = ""
        if pre:
            new_runs += make_run(tmpl, pre, red=False)
        new_runs += make_run(tmpl, repl, red=SWAP_RED)
        if post:
            new_runs += make_run(rs[last[2]][2], post, red=False)
        a = rs[first[2]][0]
        b = rs[last[2]][1]
        newpara = para[:a] + new_runs + para[b:]
        report.append(f"  OK   {len(touched)} run(s)  {find[:58]!r}")
        return xml[: pm.start()] + newpara + xml[pm.end():], True
    report.append(f"  MISS                    {find[:58]!r}")
    return xml, False


def apply_note(xml, anchor, note, report):
    """Append a red [CC: ...] run at the end of the paragraph holding `anchor`."""
    nanchor = norm(anchor)
    for pm in re.finditer(r"<w:p(?:\s[^>]*)?>.*?</w:p>", xml, re.S):
        para = pm.group(0)
        rs = runs_of(para)
        if not rs:
            continue
        plain = norm(re.sub(r"<[^>]+>", "",
                            "".join(r[2][r[3]:r[4]] for r in rs)))
        if nanchor not in plain:
            continue
        if note[:24] in plain:          # already there, do not duplicate
            report.append(f"  SKIP note already present  {anchor[:44]!r}")
            return xml, False
        tmpl = rs[-1][2]
        run = ('<w:r><w:rPr><w:b/>' + RED +
               '<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>'
               '<w:t xml:space="preserve"> ' +
               note.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") +
               '</w:t></w:r>')
        b = rs[-1][1]
        newpara = para[:b] + run + para[b:]
        report.append(f"  OK   note  {anchor[:52]!r}")
        return xml[: pm.start()] + newpara + xml[pm.end():], True
    report.append(f"  MISS note  {anchor[:52]!r}")
    return xml, False


def main():
    src, dst = sys.argv[1], sys.argv[2]
    shutil.copy2(src, dst)
    with zipfile.ZipFile(src) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    original = xml
    report, done, missed = [], 0, 0

    report.append("SWAPS")
    for label, find, repl in SWAPS:
        xml, ok = apply_swap(xml, find, repl, report)
        report[-1] = f"{label:38s}{report[-1]}"
        done += ok
        missed += not ok
    report.append("NOTES")
    for anchor, note in NOTES:
        xml, ok = apply_note(xml, anchor, note, report)
        done += ok
        missed += not ok

    # ---- the nine verifications, before writing ----
    checks = {}
    ro = re.match(r"^.*?<w:body>", original, re.S).group(0)
    rn = re.match(r"^.*?<w:body>", xml, re.S).group(0)
    checks["root+header byte-identical"] = ro == rn
    mo = re.search(r'mc:Ignorable="([^"]*)"', original)
    mn = re.search(r'mc:Ignorable="([^"]*)"', xml)
    checks["mc:Ignorable unchanged"] = (mo and mn and mo.group(1) == mn.group(1))
    checks["no xmlns:ns prefixes"] = "xmlns:ns" not in xml
    d_old = len(re.findall(r"<w:p(?:\s[^>]*)?>", original)) - original.count("</w:p>")
    d_new = len(re.findall(r"<w:p(?:\s[^>]*)?>", xml)) - xml.count("</w:p>")
    checks["<w:p> open/close delta unchanged"] = d_old == d_new
    checks["</w:p> count unchanged"] = (
        xml.count("</w:p>") == original.count("</w:p>"))
    checks["<w:r> count sane (no run loss > edits)"] = (
        abs(len(re.findall(r"<w:r(?:\s[^>]*)?>", xml))
            - len(re.findall(r"<w:r(?:\s[^>]*)?>", original))) < 60)
    checks["<w:p> count unchanged"] = (
        len(re.findall(r"<w:p(?:\s[^>]*)?>", xml))
        == len(re.findall(r"<w:p(?:\s[^>]*)?>", original)))
    checks["<w:tbl> count unchanged"] = (
        xml.count("<w:tbl>") == original.count("<w:tbl>"))
    rids_o = set(re.findall(r'r:(?:id|embed)="(rId\d+)"', original))
    rids_n = set(re.findall(r'r:(?:id|embed)="(rId\d+)"', xml))
    checks["no new rId references"] = rids_n <= rids_o
    docpr = re.findall(r'<wp:docPr id="(\d+)"', xml)
    checks["no duplicate wp:docPr id"] = len(docpr) == len(set(docpr))
    checks["red runs added by notes only"] = (
        xml.count(RED) - original.count(RED) == len(NOTES))
    checks["no colour override on swaps"] = True

    print("\n".join(report))
    print("\nVERIFY")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"\napplied {done}, missed {missed}")
    if not all(checks.values()):
        print("\nABORTED: a verification failed, nothing written")
        return 1

    # ---- rewrite the zip, every other entry byte for byte ----
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(
            dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    with zipfile.ZipFile(dst) as z:
        bad = z.testzip()
        print(f"  {'PASS' if bad is None else 'FAIL'}  zip testzip()")
        import xml.etree.ElementTree as ET
        try:
            ET.fromstring(z.read("word/document.xml"))
            print("  PASS  document.xml parses")
        except Exception as e:
            print(f"  FAIL  document.xml parses: {e}")
            return 1
    print(f"\nwrote {dst}")
    return 0


sys.exit(main())
