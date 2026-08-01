"""Insert Table 3.2 and Figure 5.5 into the dissertation master.

String surgery only. document.xml is never parsed and re-serialised: doing that
renames namespace prefixes and breaks mc:Ignorable, and Word then refuses the
file. Every edit here is an exact-match replacement on the raw text, and each
one asserts it matched exactly once before anything is written.

Reads the numbers from the DB at build time so the table cannot drift.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import struct
import zipfile
from collections import defaultdict

REPO = "/Users/benjyb/Desktop/MscProject"
WORK = os.path.dirname(os.path.abspath(__file__))
SRC = f"{REPO}/Dissertation/Dissertation.docx"
DST = f"{WORK}/out.docx"
PNG = f"{REPO}/Dissertation/figures_new/fig_5_5_dimension_oversight.png"
DB = f"{REPO}/.claude/worktrees/dissertation-review-agent-f6ad5c/data/odmi.db"

QUESTIONS = ["Q12", "Q13", "Q16", "Q17", "Q18", "Q21", "Q22", "Q25", "Q27"]
HELD_OUT = {"BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE"}
ROUTE = {"dcat_rdf": "DCAT-AP RDF", "ckan_json": "CKAN",
         "al_dcat_api": "DCAT-AP API", "sparql_rdf": "SPARQL"}

RED = '<w:color w:val="FF0000"/>'


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def load_rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    snaps = {}
    for r in con.execute("""select snapshot_id, country_code, harvest_route,
                                   dataset_count, partial
                            from catalogue_snapshots"""):
        if r["country_code"] in HELD_OUT or r["dataset_count"] == 0:
            continue
        if r["partial"]:                    # partial harvests are not evidence
            continue
        snaps[r["snapshot_id"]] = dict(r)

    latest = {}
    for r in con.execute("""select snapshot_id, question_id, raw_value,
                                   band_label, computed_at
                            from catalogue_metrics order by computed_at"""):
        if r["snapshot_id"] in snaps:
            latest[(r["snapshot_id"], r["question_id"])] = dict(r)

    selfrep = {}
    q = ",".join("?" * len(QUESTIONS))
    for r in con.execute(f"""select country_code, question_id, response
                             from ground_truth where question_id in ({q})""",
                         QUESTIONS):
        selfrep[(r["country_code"], r["question_id"])] = r["response"]

    by_country = defaultdict(list)
    for sid, s in snaps.items():
        by_country[s["country_code"]].append(s)
    for c in by_country:
        by_country[c].sort(key=lambda s: s["dataset_count"])

    rows, agree_tot, cmp_tot = [], 0, 0
    for cc in sorted(by_country):
        rows.append(("head", cc, "Self-reported", "",
                     [selfrep.get((cc, q), "--") for q in QUESTIONS]))
        for s in by_country[cc]:
            cells, agree = [], 0
            for qid in QUESTIONS:
                m = latest.get((s["snapshot_id"], qid))
                if not m or m["raw_value"] is None:
                    cells.append(("--", False))
                    continue
                val = (f"{m['raw_value']:.0f}" if qid == "Q13"
                       else f"{m['raw_value']:.1f}")
                hit = (selfrep.get((cc, qid)) or "").strip() == (m["band_label"] or "").strip()
                if m["band_label"] and selfrep.get((cc, qid)):
                    cmp_tot += 1
                    agree += hit
                cells.append((val, hit))
            agree_tot += agree
            rows.append(("data", "", ROUTE.get(s["harvest_route"],
                                               s["harvest_route"]),
                         f"{s['dataset_count']:,}", cells))
    return rows, agree_tot, cmp_tot


# --------------------------------------------------------------------------
# xml builders
# --------------------------------------------------------------------------

def esc(t):
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def cell(text, *, bold=False, italic=False, size="14", align="center"):
    rpr = "<w:rPr>"
    if bold:
        rpr += "<w:b/><w:bCs/>"
    if italic:
        rpr += "<w:i/><w:iCs/>"
    rpr += f'{RED}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>'
    return (
        '<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/><w:vAlign w:val="center"/>'
        "</w:tcPr><w:p><w:pPr>"
        f'<w:spacing w:before="0" w:after="0"/><w:jc w:val="{align}"/>{rpr}</w:pPr>'
        f"<w:r>{rpr}<w:t xml:space=\"preserve\">{esc(text)}</w:t></w:r></w:p></w:tc>"
    )


def build_table(rows):
    ncol = 3 + len(QUESTIONS)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in
                   [620, 1180, 700] + [560] * len(QUESTIONS))
    out = [
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblCellSpacing w:w="15" w:type="dxa"/><w:tblCellMar>'
        '<w:top w:w="15" w:type="dxa"/><w:left w:w="15" w:type="dxa"/>'
        '<w:bottom w:w="15" w:type="dxa"/><w:right w:w="15" w:type="dxa"/>'
        "</w:tblCellMar>"
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1"'
        ' w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>",
        # header
        '<w:tr><w:trPr><w:tblHeader/><w:tblCellSpacing w:w="15" w:type="dxa"/></w:trPr>'
        + cell("", bold=True) + cell("Source", bold=True) + cell("n", bold=True)
        + "".join(cell(q, bold=True) for q in QUESTIONS) + "</w:tr>",
    ]
    for kind, cc, source, n, cells in rows:
        tr = ['<w:tr><w:trPr><w:tblCellSpacing w:w="15" w:type="dxa"/></w:trPr>']
        if kind == "head":
            tr.append(cell(cc, bold=True, align="left"))
            tr.append(cell(source, italic=True, align="left"))
            tr.append(cell(""))
            tr += [cell(v, italic=True) for v in cells]
        else:
            tr.append(cell(""))
            tr.append(cell(source, align="left"))
            tr.append(cell(n, align="right"))
            tr += [cell(v, bold=hit) for v, hit in cells]
        tr.append("</w:tr>")
        out.append("".join(tr))
    out.append("</w:tbl>")
    return "".join(out)


def note_para(text):
    return (
        '<w:p><w:pPr><w:spacing w:before="60" w:after="200"/>'
        f'<w:rPr>{RED}<w:sz w:val="16"/></w:rPr></w:pPr>'
        f'<w:r><w:rPr>{RED}<w:sz w:val="16"/></w:rPr>'
        f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
    )


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit("not a png")
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def build_figure(rid, png_path, caption):
    pw, ph = png_size(png_path)
    cx = 5393797                       # matches the other figures in the file
    cy = int(round(cx * ph / pw))
    drawing = (
        '<w:p><w:pPr><w:spacing w:before="200" w:after="40"/>'
        '<w:jc w:val="center"/></w:pPr>'
        '<w:r><w:rPr><w:noProof/></w:rPr><w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:docPr id="1955000155" name="Picture 1955000155"/>'
        "<wp:cNvGraphicFramePr><a:graphicFrameLocks "
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="0" name="fig_5_5_dimension_oversight.png"/>'
        "<pic:cNvPicPr/></pic:nvPicPr>"
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )
    cap = (
        '<w:p><w:pPr><w:spacing w:before="40" w:after="220"/>'
        f'<w:jc w:val="center"/><w:rPr>{RED}<w:sz w:val="18"/></w:rPr></w:pPr>'
        f'<w:r><w:rPr>{RED}<w:sz w:val="18"/></w:rPr>'
        f'<w:t xml:space="preserve">{esc(caption)}</w:t></w:r></w:p>'
    )
    return drawing + cap


# --------------------------------------------------------------------------
# surgery
# --------------------------------------------------------------------------

def replace_once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"REFUSING: {what!r} matched {n} times, expected 1")
    return text.replace(old, new)


def main():
    rows, agree, total = load_rows()

    with zipfile.ZipFile(SRC) as z:
        names = z.namelist()
        blobs = {n: z.read(n) for n in names}

    doc = blobs["word/document.xml"].decode("utf-8")
    rels = blobs["word/_rels/document.xml.rels"].decode("utf-8")

    # 1. the table replaces the shouted author note
    missing = (
        '<w:p w14:paraId="18644BCC" w14:textId="2F32FD38" w:rsidR="004E729F" '
        'w:rsidRDefault="004E729F" w:rsidP="004E729F"><w:pPr>'
        '<w:spacing w:before="200" w:after="100"/><w:rPr><w:color w:val="FF0000"/>'
        '<w:sz w:val="20"/></w:rPr></w:pPr><w:r><w:rPr><w:color w:val="FF0000"/>'
        '<w:sz w:val="20"/></w:rPr><w:t>[TABLE IS MISSING] AND IVE MESSED WITH '
        'THES SECTION ORDERING – MAKE SURE ALL REFS ARE CORECT</w:t></w:r></w:p>'
    )
    note = (
        f"Recomputed values are percentages, except Q13 which is a count of "
        f"distinct licences. Bold marks a recompute falling in the band the "
        f"country reported: {agree} of {total} across the eight complete "
        f"harvests. Partial harvests are excluded. [CC: Romania's DCAT-AP RDF "
        f"row returns 0.0 on Q12 and Q25 and 0.5 on Q21 where CKAN over the "
        f"same 5,143 datasets returns 96.2, 96.2 and 99.8. That harvest "
        f"predates the RDF serialiser fix, so treat the licence columns on "
        f"that one row as an artefact or drop the row.]"
    )
    doc = replace_once(doc, missing, build_table(rows) + note_para(note),
                       "[TABLE IS MISSING] paragraph")

    # 2. the placeholder becomes a real cross-reference
    doc = replace_once(doc, "<w:t>FIGURE X makes plain</w:t>",
                       "<w:t>Figure 5.5 makes plain</w:t>", "FIGURE X reference")

    # 3. figure and caption after the paragraph that cites it
    anchor = ("<w:t>. So, the useful question is which parts of the assessment "
              "the system can be trusted with and which have to stay manual."
              "</w:t></w:r></w:p>")
    rid = "rId900"
    fig = build_figure(
        rid, PNG,
        "Figure 5.5: Outcome composition by ODMI dimension over the 1,144 "
        "held-out pairs, ordered by false-positive rate on negative golds.")
    doc = replace_once(doc, anchor, anchor + fig, "FIGURE X host paragraph")

    # 4. relationship and media part
    rel = (f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
           f'officeDocument/2006/relationships/image" '
           f'Target="media/fig_5_5_dimension_oversight.png"/>')
    rels = replace_once(rels, "</Relationships>", rel + "</Relationships>",
                        "rels closing tag")

    blobs["word/document.xml"] = doc.encode("utf-8")
    blobs["word/_rels/document.xml.rels"] = rels.encode("utf-8")
    with open(PNG, "rb") as f:
        blobs["word/media/fig_5_5_dimension_oversight.png"] = f.read()
    names.append("word/media/fig_5_5_dimension_oversight.png")

    with zipfile.ZipFile(DST, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, blobs[n])

    print(f"wrote {DST}")
    print(f"  table rows {len(rows)}, agreement {agree}/{total}")
    print(f"  document.xml {len(blobs['word/document.xml']):,} bytes")


if __name__ == "__main__":
    main()
