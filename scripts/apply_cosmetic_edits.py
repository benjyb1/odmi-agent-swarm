"""Apply the agreed cosmetic and pruning edits to the dissertation master.

String surgery on word/document.xml only. The XML is never parsed and
re-serialised, because that renames namespace prefixes and Word then rejects the
file. Every other part of the zip is copied through byte for byte.

Every replacement asserts its expected match count. A count that does not match
aborts the whole run before anything is written, so a target that moved since
the recon cannot silently edit the wrong place.

Writes to a new file. Installing over the master is a separate step.

Usage:
    python3 scripts/apply_cosmetic_edits.py <in.docx> <out.docx> [--expect-sha X]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import zipfile

W_T = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)


class Editor:
    def __init__(self, xml):
        self.xml = xml
        self.log = []

    # -- exact string replacement, count asserted --------------------------
    def sub(self, old, new, expect=1, label=""):
        n = self.xml.count(old)
        if n != expect:
            raise SystemExit(
                f"ABORT [{label or old[:40]}]: expected {expect} match(es), found {n}")
        self.xml = self.xml.replace(old, new)
        self.log.append(f"replaced x{n}: {label or old[:60]}")

    # -- replacement scoped to the paragraph holding an anchor --------------
    def sub_in_paragraph(self, anchor, old, new, expect=1, label=""):
        """For targets whose text is common elsewhere, such as a section
        number used as a cross-reference throughout the document."""
        if self.xml.count(anchor) != 1:
            raise SystemExit(
                f"ABORT anchor [{label}]: {self.xml.count(anchor)} matches, need 1")
        i = self.xml.find(anchor)
        start = max(self.xml.rfind("<w:p ", 0, i), self.xml.rfind("<w:p>", 0, i))
        end = self.xml.find("</w:p>", i) + len("</w:p>")
        seg = self.xml[start:end]
        n = seg.count(old)
        if n != expect:
            raise SystemExit(
                f"ABORT [{label}]: expected {expect} in paragraph, found {n}")
        self.xml = self.xml[:start] + seg.replace(old, new) + self.xml[end:]
        self.log.append(f"replaced x{n} within paragraph: {label}")

    # -- delete the <w:p> containing a needle -------------------------------
    def delete_paragraph(self, needle, label=""):
        n = self.xml.count(needle)
        if n != 1:
            raise SystemExit(
                f"ABORT paragraph [{label or needle[:40]}]: {n} matches, need 1")
        i = self.xml.find(needle)
        start = max(self.xml.rfind("<w:p ", 0, i), self.xml.rfind("<w:p>", 0, i))
        if start < 0:
            raise SystemExit(f"ABORT: no <w:p> before {label or needle[:40]}")
        end = self.xml.find("</w:p>", i)
        if end < 0:
            raise SystemExit(f"ABORT: no </w:p> after {label or needle[:40]}")
        end += len("</w:p>")
        # A <w:p> cannot nest, so anything between start and end is this
        # paragraph only. Guard anyway.
        if "<w:p " in self.xml[start + 5:end - 6] or "<w:p>" in self.xml[start + 5:end - 6]:
            raise SystemExit(f"ABORT: nested <w:p> around {label or needle[:40]}")
        self.xml = self.xml[:start] + self.xml[end:]
        self.log.append(f"deleted paragraph: {label or needle[:60]}")

    # -- delete table rows by absolute <w:tr> span --------------------------
    def delete_row_spans(self, spans, label=""):
        for start, end in sorted(spans, reverse=True):
            self.xml = self.xml[:start] + self.xml[end:]
        self.log.append(f"deleted {len(spans)} table rows: {label}")

    # -- collapse runs of spaces inside <w:t> only --------------------------
    def collapse_double_spaces(self):
        hits = [0]

        def fix(m):
            body = m.group(1)
            new = re.sub(r"  +", " ", body)
            if new != body:
                hits[0] += body.count("  ")
            return m.group(0).replace(body, new) if new != body else m.group(0)

        self.xml = W_T.sub(fix, self.xml)
        self.log.append(f"collapsed double spaces in {hits[0]} places")

    def collapse_boundary_double_spaces(self):
        """A double space split across two runs survives a per-run collapse.

        Word splits runs for formatting reasons, so ". " and " Word" can be two
        elements and still render as two spaces. Only join runs inside the same
        paragraph, since the last run of one paragraph and the first of the next
        are not adjacent to a reader.
        """
        fixed = 0
        while True:
            spans = [(m.start(1), m.end(1), m.group(1))
                     for m in re.finditer(W_T, self.xml)]
            for (s1, e1, t1), (s2, e2, t2) in zip(spans, spans[1:]):
                if not (t1.endswith(" ") and t2.startswith(" ")):
                    continue
                if "</w:p>" in self.xml[e1:s2]:
                    continue
                self.xml = self.xml[:s2] + t2.lstrip(" ") + self.xml[e2:]
                fixed += 1
                break
            else:
                break
        self.log.append(f"collapsed {fixed} double spaces spanning two runs")


def find_h2_duplicate_rows(xml):
    """The first row of each duplicated (Question, Country) pair in Table H.2.

    The duplication is two metric computation passes over one harvest snapshot,
    not two harvests. The later pass is the corrected one, so the earlier row
    goes. Rows sit in computed order, so the earlier row is the first of a pair.
    """
    # Locate the table by its header cells.
    anchor = xml.find(">Question</w:t>")
    while anchor != -1:
        tbl_start = xml.rfind("<w:tbl>", 0, anchor)
        tbl_end = xml.find("</w:tbl>", anchor)
        if tbl_start == -1 or tbl_end == -1:
            break
        seg = xml[tbl_start:tbl_end]
        if ">Country</w:t>" in seg[:4000] and ">Published</w:t>" in seg[:4000]:
            break
        anchor = xml.find(">Question</w:t>", anchor + 1)
    else:
        raise SystemExit("ABORT: Table H.2 not found")
    if anchor == -1:
        raise SystemExit("ABORT: Table H.2 not found")

    rows = []
    for m in re.finditer(r"<w:tr\b.*?</w:tr>", xml[tbl_start:tbl_end], re.S):
        body = m.group(0)
        cells = re.findall(r"<w:tc>.*?</w:tc>", body, re.S)
        texts = ["".join(t for t in W_T.findall(c)).strip() for c in cells]
        rows.append((tbl_start + m.start(), tbl_start + m.end(), texts))

    header = rows[0][2][:2]
    if header != ["Question", "Country"]:
        raise SystemExit(f"ABORT: unexpected H.2 header {header}")

    seen, drop = {}, []
    for start, end, texts in rows[1:]:
        key = tuple(texts[:2])
        if key in seen:
            drop.append(seen[key])          # the earlier row of the pair
        seen[key] = (start, end)
    return drop, len(rows) - 1


ORPHANS = [
    "Bai, Y., Kadavath, S., Kundu, S. et al. (2022)",
    "Cambronero, J., Tufano, M., Shi, S. et al. (2026)",
    "Chern, I., Chern, S., Chen, S. et al. (2023)",
    "Eurostat (2017)",
    "Franklin, S. and Graesser, A. (1997)",
    "Golchin, S. and Surdeanu, M. (2024)",
    "Irving, G., Christiano, P. and Amodei, D. (2018)",
    "Kadavath, S., Conerly, T., Askell, A. et al. (2022)",
    "Khan, A., Hughes, J., Valentine, D., Ruis, L.",
    "Lipton, Z. C. and Steinhardt, J. (2018)",
    "Luo, H., Wen, B. and Wang, L. L. (2026)",
    "Madaan, A., Tandon, N., Gupta, P. et al. (2023)",
    "Magar, I. and Schwartz, R. (2022)",
    "Ogundepo, O., Gwadabe, T. R., Rivera, C. E. et al. (2023)",
    "Pineau, J., Vincent-Lamarre, P., Sinha, K. et al. (2021)",
    "Powell, J., Lagomarsino, G. and Melamed, C. (2025)",
    "Sainz, O., Campos, J. A.",
    "Sculley, D., Holt, G., Golovin, D. et al. (2015)",
    "Wang, L., Ma, C., Feng, X., Zhang, Z., Yang, H.",
    "Wang, X., Wei, J., Schuurmans, D. et al. (2023)",
    "Wen, B., Yao, J., Feng, S., Xu, C., Tsvetkov, Y.",
    "Weng, L. (2023)",
    "Xie, J., Zhang, K., Chen, M., Lou, R. and Su, Y. (2024)",
    "Zhang, H., Diao, S., Lin, Y. et al. (2024)",
    "Zhang, X., Peng, B., Tian, Y. et al. (2024)",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dest")
    ap.add_argument("--expect-sha")
    args = ap.parse_args()

    with open(args.src, "rb") as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    print(f"source sha256 {sha}")
    if args.expect_sha and sha != args.expect_sha:
        raise SystemExit(f"ABORT: master changed. expected {args.expect_sha}")

    with zipfile.ZipFile(args.src) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names}
        infos = {n: z.getinfo(n) for n in names}

    ed = Editor(parts["word/document.xml"].decode("utf-8"))

    # ---- 1. table H.2 de-duplication ---------------------------------
    drop, total_rows = find_h2_duplicate_rows(ed.xml)
    print(f"Table H.2: {total_rows} data rows, {len(drop)} duplicates to drop")
    if len(drop) != 21:
        raise SystemExit(f"ABORT: expected 21 duplicate rows, found {len(drop)}")
    ed.delete_row_spans(drop, "Table H.2 stale metric pass")
    ed.sub("Table H.1, 96 in total,", "Table H.1, 75 in total,",
           label="H.2 caption count 96 -> 75")

    # ---- 2. 'Crucially' ----------------------------------------------
    ed.sub(">Crucially, </w:t>", "></w:t>", label="drop 'Crucially, '")
    ed.sub(">a large share of the questions ask a team to report on its own internal practice",
           ">A large share of the questions ask a team to report on its own internal practice",
           label="capitalise 'A large share'")

    # ---- 3. cosmetic single-run fixes ---------------------------------
    ed.sub("more evidence based", "more evidence-based", label="evidence-based")
    ed.sub("Outcome makeup per country", "Outcome make-up per country",
           label="make-up")
    ed.sub("multiple failure modes; abstention tracking maturity",
           "multiple failure modes: abstention tracking maturity",
           label="semicolon -> colon")
    ed.sub("The baselines the evaluation result is read against.",
           "The baselines the evaluation results are read against.",
           label="baselines results are")
    ed.sub("pp. 131–184", "pp.131–184", label="pp.131")
    ed.sub("pp. 291–308", "pp.291–308", label="pp.291")
    ed.sub("arXiv:2305.14325 (published ICML 2024).", "arXiv:2305.14325.",
           label="drop ICML venue note")
    ed.sub("from £0.31 in Finland", "from £0.310 in Finland", label="£0.310")
    ed.sub("per-token rates and no figure in this report is billed spend",
           "per-token rates, and no figure in this report is billed spend",
           label="comma before 'and no figure'")
    ed.sub("adds and misses</w:t>", "adds and misses.</w:t>",
           label="Figure 2.3 terminal stop")

    # ---- 4. non-breaking hyphen --------------------------------------
    # per-claim, three-retry and lower-resource. All three are ordinary
    # compounds typed with U+2011, which Word's Find will not match.
    nb = ed.xml.count("‑")
    print(f"non-breaking hyphens found: {nb}")
    if nb != 3:
        raise SystemExit(f"ABORT: expected 3 non-breaking hyphens, found {nb}")
    ed.sub("‑", "-", expect=3, label="non-breaking hyphen -> hyphen")

    # ---- 5. scaffold sentences ---------------------------------------
    ed.delete_paragraph("Reproduced in full from the Experiments section for reference.",
                        label="scaffold sentence (Appendix C)")
    anchor_b = ">Reproduced in full from </w:t>"
    ed.sub_in_paragraph(anchor_b, ">§4.2</w:t>", "></w:t>",
                        label="scaffold prefix (Appendix B): drop '§4.2'")
    ed.sub_in_paragraph(anchor_b, "> for reference. Codes E, G, I and D are",
                        ">Codes E, G, I and D are",
                        label="scaffold prefix (Appendix B): drop 'for reference.'")
    ed.sub(anchor_b, "></w:t>",
           label="scaffold prefix (Appendix B): drop 'Reproduced in full from'")

    # ---- 6. uncited references ---------------------------------------
    for entry in ORPHANS:
        ed.delete_paragraph(entry, label=f"uncited reference: {entry[:34]}")

    # ---- 7. double spaces --------------------------------------------
    ed.collapse_double_spaces()
    ed.collapse_boundary_double_spaces()

    # ---- write -------------------------------------------------------
    parts["word/document.xml"] = ed.xml.encode("utf-8")
    with zipfile.ZipFile(args.dest, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            zi = zipfile.ZipInfo(n, date_time=infos[n].date_time)
            zi.compress_type = infos[n].compress_type
            zi.external_attr = infos[n].external_attr
            zi.internal_attr = infos[n].internal_attr
            zi.create_system = infos[n].create_system
            z.writestr(zi, parts[n])

    print()
    for line in ed.log:
        print("  " + line)
    print(f"\nwritten to {args.dest}")


if __name__ == "__main__":
    main()
