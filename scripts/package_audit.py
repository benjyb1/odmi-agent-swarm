"""Package-level audit of the dissertation .docx, treated as a zip archive.

Everything here is invisible to a text pass. Tracked insertions, Word comments,
field codes, document properties, image names, hidden text and embedded objects
all ship inside the file and none of them appear in the extracted prose.

Deterministic and read-only. No LLM, no network, no writes to the master.

Usage:
    python3 scripts/package_audit.py Dissertation/Dissertation.docx --out build/pub
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Local-path shapes that must never be embedded in a published file.
LOCAL_PATH = re.compile(
    r"(file:///[^\"'<>\s]+|[A-Za-z]:\\\\[^\"'<>\s]+|/Users/[^\"'<>\s]+"
    r"|/home/[^\"'<>\s]+|localhost(?::\d+)?|127\.0\.0\.1)"
)

# Identifiers that mean nothing to a reader.
INTERNAL_ID = re.compile(
    r"(exp\d+_[a-z0-9_]+|data/odmi\.db|odmi\.db|\.claude/worktrees/[\w.-]+"
    r"|scripts/[a-z_]+\.py|evaluation/[\w/]+\.(?:py|json)|dashboard/[\w/]+\.py"
    r"|agents/[\w/]+\.py|[a-z_]+\.jsonl)"
)


def strip_tags(xml: str) -> str:
    return re.sub(r"<[^>]+>", "", xml)


def audit(path: str) -> dict:
    out = {"file": os.path.abspath(path)}
    with open(path, "rb") as f:
        raw = f.read()
    out["sha256"] = hashlib.sha256(raw).hexdigest()
    out["bytes"] = len(raw)

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        out["parts"] = len(names)

        def read(part):
            try:
                return z.read(part).decode("utf-8", "replace")
            except KeyError:
                return ""

        doc = read("word/document.xml")

        # ---------------- tracked changes ----------------
        ins = re.findall(r"<w:ins\b[^>]*>(.*?)</w:ins>", doc, re.S)
        dele = re.findall(r"<w:del\b[^>]*>(.*?)</w:del>", doc, re.S)
        out["tracked_insertions"] = [
            {"text": strip_tags(m).strip()[:300],
             "author": (re.search(r'w:author="([^"]*)"', a) or [None, ""])[1]
             if False else None}
            for m, a in zip(ins, ins)
        ]
        # authors sit on the w:ins tag itself, so pull tag and body together
        out["tracked_insertions"] = []
        for m in re.finditer(r"<w:ins\b([^>]*)>(.*?)</w:ins>", doc, re.S):
            attrs, body = m.group(1), m.group(2)
            out["tracked_insertions"].append({
                "author": (re.search(r'w:author="([^"]*)"', attrs) or ["", ""])[1]
                if re.search(r'w:author="([^"]*)"', attrs) else "",
                "date": (re.search(r'w:date="([^"]*)"', attrs).group(1)
                         if re.search(r'w:date="([^"]*)"', attrs) else ""),
                "text": strip_tags(body).strip()[:400],
            })
        out["tracked_deletions"] = []
        for m in re.finditer(r"<w:del\b([^>]*)>(.*?)</w:del>", doc, re.S):
            attrs, body = m.group(1), m.group(2)
            out["tracked_deletions"].append({
                "author": (re.search(r'w:author="([^"]*)"', attrs).group(1)
                           if re.search(r'w:author="([^"]*)"', attrs) else ""),
                "date": (re.search(r'w:date="([^"]*)"', attrs).group(1)
                         if re.search(r'w:date="([^"]*)"', attrs) else ""),
                "text": strip_tags(body).strip()[:400],
            })
        out["tracked_formatting_rPrChange"] = len(re.findall(r"<w:rPrChange\b", doc))
        out["tracked_formatting_pPrChange"] = len(re.findall(r"<w:pPrChange\b", doc))
        out["tracked_table_changes"] = len(
            re.findall(r"<w:(?:tblPrChange|trPrChange|tcPrChange|cellIns|cellDel)\b", doc))
        out["moveFrom_moveTo"] = len(re.findall(r"<w:move(?:From|To)\b", doc))

        # ---------------- comments ----------------
        out["comment_anchors"] = {
            "commentRangeStart": len(re.findall(r"<w:commentRangeStart\b", doc)),
            "commentRangeEnd": len(re.findall(r"<w:commentRangeEnd\b", doc)),
            "commentReference": len(re.findall(r"<w:commentReference\b", doc)),
        }
        comments = []
        for part in ("word/comments.xml", "word/commentsExtended.xml",
                     "word/commentsIds.xml", "word/commentsExtensible.xml"):
            if part in names:
                out.setdefault("comment_parts", []).append(part)
        cx = read("word/comments.xml")
        for m in re.finditer(r"<w:comment\b([^>]*)>(.*?)</w:comment>", cx, re.S):
            attrs, body = m.group(1), m.group(2)
            def attr(k):
                mm = re.search(rf'w:{k}="([^"]*)"', attrs)
                return mm.group(1) if mm else ""
            comments.append({"id": attr("id"), "author": attr("author"),
                             "initials": attr("initials"), "date": attr("date"),
                             "text": strip_tags(body).strip()[:400]})
        out["comments"] = comments
        # resolved state lives in commentsExtended
        cext = read("word/commentsExtended.xml")
        out["comments_resolved"] = len(re.findall(r'w15:done="1"', cext))
        out["comments_unresolved"] = len(re.findall(r'w15:done="0"', cext))

        # ---------------- field codes ----------------
        fields = [f.strip() for f in re.findall(r"<w:instrText[^>]*>(.*?)</w:instrText>",
                                                doc, re.S)]
        fields = [strip_tags(f).strip() for f in fields]
        simple = re.findall(r'<w:fldSimple[^>]*w:instr="([^"]*)"', doc)
        out["field_codes"] = {
            "instrText_runs": len(fields),
            "fldSimple": len(simple),
            "dirty_flagged": len(re.findall(r'w:dirty="(?:1|true)"', doc)),
            "fldChar_begin": len(re.findall(r'w:fldCharType="begin"', doc)),
            "kinds": {},
            "samples": (fields + simple)[:80],
        }
        for f in fields + simple:
            kind = (f.strip().split() or ["?"])[0].upper()
            out["field_codes"]["kinds"][kind] = \
                out["field_codes"]["kinds"].get(kind, 0) + 1

        # Cross-reference targets that resolve to nothing, and stale REF text.
        out["field_ref_targets"] = sorted(set(
            re.findall(r"\bREF\s+(\S+)", " ".join(fields + simple))))
        out["bookmarks"] = sorted(set(re.findall(r'<w:bookmarkStart[^>]*w:name="([^"]*)"',
                                                 doc)))[:200]
        out["error_not_found_text"] = len(re.findall(
            r"Error! (?:Reference source not found|Bookmark not defined)", doc))

        # ---------------- document properties ----------------
        for part in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
            if part in names:
                out[part] = {}
                content = read(part)
                for m in re.finditer(r"<((?:cp|dc|dcterms|ap|vt|)[:\w]*)"
                                     r"[^>/]*>([^<]*)</\1>", content):
                    tag, val = m.group(1), m.group(2).strip()
                    if val:
                        out[part][tag] = val[:200]
                out[part + "_raw_len"] = len(content)
                if part == "docProps/custom.xml":
                    out["custom_props_raw"] = content[:2000]

        # ---------------- media ----------------
        media = [n for n in names if n.startswith("word/media/")]
        out["media_count"] = len(media)
        out["media"] = []
        for n in sorted(media):
            info = z.getinfo(n)
            head = z.read(n)[:4096]
            # Anything textual inside the first blocks: PNG tEXt, EXIF, SVG.
            strings = re.findall(rb"[ -~]{6,}", head)
            interesting = [s.decode("ascii", "replace") for s in strings
                           if LOCAL_PATH.search(s.decode("ascii", "replace"))
                           or re.search(r"(?i)(screenshot|untitled|desktop|"
                                        r"benjyb|matplotlib|Adobe|Photoshop|"
                                        r"Illustrator|Canva|Figma|\.py|\.db)",
                                        s.decode("ascii", "replace"))]
            out["media"].append({"name": n, "bytes": info.file_size,
                                 "strings": interesting[:6]})

        # Alt text and drawing names carry original filenames.
        out["drawing_names"] = re.findall(r'<wp:docPr[^>]*\bname="([^"]*)"', doc)
        out["drawing_descr"] = [d for d in
                                re.findall(r'<wp:docPr[^>]*\bdescr="([^"]*)"', doc) if d]
        out["pic_names"] = sorted(set(re.findall(r'<pic:cNvPr[^>]*\bname="([^"]*)"', doc)))

        # ---------------- hidden / marked-up text ----------------
        out["vanish_runs"] = len(re.findall(r"<w:vanish\b(?![^>]*w:val=\"(?:0|false)\")", doc))
        out["vanish_all"] = len(re.findall(r"<w:vanish\b", doc))
        out["specVanish"] = len(re.findall(r"<w:specVanish\b", doc))
        out["highlight"] = {}
        for h in re.findall(r'<w:highlight[^>]*w:val="([^"]*)"', doc):
            out["highlight"][h] = out["highlight"].get(h, 0) + 1
        out["shading_runs"] = len(re.findall(r"<w:rPr>(?:(?!</w:rPr>).)*<w:shd\b", doc, re.S))
        out["strike_runs"] = len(re.findall(r"<w:strike\b", doc))

        # ---------------- embedded objects ----------------
        out["embeddings"] = [n for n in names if "embeddings/" in n
                             or n.endswith((".bin", ".xlsx", ".docx", ".pptx"))
                             and n != os.path.basename(path)]
        out["ole_objects"] = len(re.findall(r"<o:OLEObject\b|<w:object\b", doc))
        out["activex"] = [n for n in names if "activeX" in n]
        out["vba"] = [n for n in names if n.endswith(".bin") and "vba" in n.lower()]

        # ---------------- settings ----------------
        settings = read("word/settings.xml")
        out["settings"] = {
            "trackChanges_on": "<w:trackChanges" in settings,
            "documentProtection": "<w:documentProtection" in settings,
            "removePersonalInformation": "<w:removePersonalInformation" in settings,
            "rsid_count": len(re.findall(r"<w:rsid\b", settings)),
            "attachedTemplate": (re.search(r'<w:attachedTemplate[^>]*r:id="([^"]*)"',
                                           settings).group(1)
                                 if re.search(r"<w:attachedTemplate", settings) else None),
        }
        srels = read("word/_rels/settings.xml.rels")
        out["settings_template_target"] = re.findall(r'Target="([^"]*)"', srels)

        # ---------------- relationships: external targets ----------------
        rels = read("word/_rels/document.xml.rels")
        targets = re.findall(r'Target="([^"]*)"[^>]*(?:TargetMode="External")?', rels)
        ext = re.findall(r'<Relationship[^>]*Target="([^"]*)"[^>]*TargetMode="External"',
                         rels)
        out["external_links_count"] = len(ext)
        out["external_links_suspicious"] = sorted(
            {t for t in ext if LOCAL_PATH.search(t) or t.startswith("file:")})
        out["external_links_sample"] = sorted(set(ext))[:40]

        # ---------------- whole-package string sweep ----------------
        hits_path, hits_id = {}, {}
        for n in names:
            if n.startswith("word/media/"):
                continue
            try:
                blob = z.read(n).decode("utf-8", "replace")
            except Exception:
                continue
            for m in set(LOCAL_PATH.findall(blob)):
                hits_path.setdefault(m[:160], []).append(n)
            for m in set(INTERNAL_ID.findall(blob)):
                hits_id.setdefault(m[:120], []).append(n)
        out["local_paths_in_package"] = {k: sorted(set(v))[:5]
                                         for k, v in sorted(hits_path.items())}
        out["internal_ids_in_package"] = {k: sorted(set(v))[:5]
                                          for k, v in sorted(hits_id.items())}

        # ---------------- headers and footers ----------------
        out["headers_footers"] = {}
        for n in sorted(names):
            if re.match(r"word/(header|footer)\d*\.xml", n):
                txt = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", read(n)))
                out["headers_footers"][n] = txt.strip()[:300]

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--out", default="build/pub")
    args = ap.parse_args()

    data = audit(args.docx)
    os.makedirs(args.out, exist_ok=True)
    dest = os.path.join(args.out, "package_audit.json")
    with open(dest, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)

    print(f"sha256 {data['sha256'][:16]}  parts {data['parts']}")
    print(f"  tracked insertions      {len(data['tracked_insertions'])}")
    print(f"  tracked deletions       {len(data['tracked_deletions'])}")
    print(f"  rPrChange/pPrChange     {data['tracked_formatting_rPrChange']}"
          f"/{data['tracked_formatting_pPrChange']}")
    print(f"  comments                {len(data['comments'])}"
          f"  anchors {data['comment_anchors']}")
    print(f"  field codes             {data['field_codes']['instrText_runs']} instrText,"
          f" {data['field_codes']['fldSimple']} fldSimple,"
          f" dirty {data['field_codes']['dirty_flagged']}")
    print(f"  field kinds             {data['field_codes']['kinds']}")
    print(f"  Error!-not-found runs   {data['error_not_found_text']}")
    print(f"  media                   {data['media_count']}")
    print(f"  vanish/specVanish       {data['vanish_all']}/{data['specVanish']}")
    print(f"  highlight               {data['highlight']}")
    print(f"  embeddings/ole/activex  {len(data['embeddings'])}/"
          f"{data['ole_objects']}/{len(data['activex'])}")
    print(f"  external links          {data['external_links_count']}"
          f"  suspicious {data['external_links_suspicious']}")
    print(f"  local paths in package  {len(data['local_paths_in_package'])}")
    print(f"  internal ids in package {len(data['internal_ids_in_package'])}")
    print(f"written to {dest}")


if __name__ == "__main__":
    main()
