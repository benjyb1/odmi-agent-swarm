"""Deterministic QA sweep over the dissertation master.

Reads Dissertation.docx and emits a JSON manifest plus per-chapter text, so the
judgement passes (chapter agents, number verification) work from exact quotes
rather than re-parsing the docx each time.

Everything here is deterministic. No LLM, no network. If a check cannot decide,
it reports "unverified" rather than guessing. Read-only on the master: this
script never writes to the .docx.

Usage:
    python3 scripts/dissertation_qa.py Dissertation/Dissertation.docx --out build/qa
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

RED_COLOURS = {"FF0000", "C00000", "EE0000"}

# House rules from CLAUDE.md. These are hard style constraints, so a hit is a
# finding rather than a suggestion.
BANNED_WORDS = [
    "genuinely", "delve", "crucial", "landscape", "testament", "underscore",
    "tapestry", "navigate the", "in today's", "it is important to note",
    "it is worth noting", "seamless", "robustly", "leverage", "showcase",
]

US_SPELLINGS = [
    (r"\bcolor(s|ed|ing)?\b", "colour"),
    # Only the -z- forms are American. 'analyses' and 'analysed' are correct UK.
    (r"\banalyz(e|ed|es|ing)\b", "analyse"),
    (r"\bbehavior(s|al)?\b", "behaviour"),
    (r"\borganiz(e|ed|es|ing|ation|ational)\b", "organis-"),
    (r"\brecogniz(e|ed|es|ing)\b", "recognis-"),
    (r"\bspecializ(e|ed|es|ing|ation)\b", "specialis-"),
    (r"\boptimiz(e|ed|es|ing|ation)\b", "optimis-"),
    (r"\bnormaliz(e|ed|es|ing|ation)\b", "normalis-"),
    (r"\bcharacteriz(e|ed|es|ing|ation)\b", "characteris-"),
    (r"\bmodeling\b", "modelling"),
    (r"\blabeled\b", "labelled"),
    (r"\bfulfill\b", "fulfil"),
    (r"\bdefense\b", "defence"),
]

# Scaffolding that must never survive into a submitted document.
SCAFFOLDING = [
    r"\[§\d+\s*plan\]",
    r"THESE HAVE NOT BEEN REVIEWED",
    r"delete as actioned",
    r"\bTODO\b", r"\bTBC\b", r"\bTBD\b", r"\bFIXME\b", r"XXX",
    r"\bLorem ipsum\b",
    r"\[insert\b", r"\[add\b", r"\[cite\b",
    r"\?\?\?",
]

NOTE_PATTERNS = [
    (r"\[CC\b[^\]]*\]?", "cc"),
    (r"\[NB\b[^\]]*\]?", "nb"),
    (r"\[\s*(?:note|check|verify|todo)\b[^\]]*\]", "bracket"),
]


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def _text_of(node) -> str:
    """Visible text of a node. w:delText is excluded, so struck-through
    tracked-change content does not leak into quotes."""
    return "".join(t.text or "" for t in node.iter(W + "t"))


def _run_props(run):
    rPr = run.find(W + "rPr")
    if rPr is None:
        return {"colour": None, "bold": False, "size": None, "italic": False}
    colour = rPr.find(W + "color")
    size = rPr.find(W + "sz")
    return {
        "colour": (colour.get(W + "val").upper() if colour is not None
                   and colour.get(W + "val") else None),
        "bold": rPr.find(W + "b") is not None,
        "italic": rPr.find(W + "i") is not None,
        "size": size.get(W + "val") if size is not None else None,
    }


def extract(docx_path: str) -> dict:
    """Unpack the docx and pull out paragraphs, runs, comments and tables."""
    tmp = tempfile.mkdtemp(prefix="dqa_")
    try:
        with zipfile.ZipFile(docx_path) as z:
            z.extractall(tmp)

        doc_xml = os.path.join(tmp, "word", "document.xml")
        body = ET.parse(doc_xml).getroot().find(W + "body")

        # Paragraph ids that live inside a table, so table text can be told
        # apart from body prose.
        in_table = set()
        for tbl in body.iter(W + "tbl"):
            for p in tbl.iter(W + "p"):
                in_table.add(id(p))

        paragraphs = []
        for idx, p in enumerate(body.iter(W + "p")):
            pPr = p.find(W + "pPr")
            style = ""
            if pPr is not None:
                s = pPr.find(W + "pStyle")
                if s is not None:
                    style = s.get(W + "val") or ""
            runs = []
            for r in p.iter(W + "r"):
                txt = _text_of(r)
                if not txt:
                    continue
                props = _run_props(r)
                props["text"] = txt
                runs.append(props)
            paragraphs.append({
                "i": idx,
                "style": style,
                "text": _text_of(p),
                "runs": runs,
                "in_table": id(p) in in_table,
                "is_heading": style.lower().startswith("heading") or style == "Title",
            })

        comments = []
        cpath = os.path.join(tmp, "word", "comments.xml")
        if os.path.exists(cpath):
            croot = ET.parse(cpath).getroot()
            for c in croot.iter(W + "comment"):
                comments.append({
                    "id": c.get(W + "id"),
                    "author": c.get(W + "author"),
                    "date": c.get(W + "date"),
                    "text": _text_of(c).strip(),
                })

        # Anchor each comment to the paragraph it sits in.
        anchor = {}
        for idx, p in enumerate(body.iter(W + "p")):
            for ref in list(p.iter(W + "commentReference")) + list(p.iter(W + "commentRangeStart")):
                cid = ref.get(W + "id")
                if cid is not None and cid not in anchor:
                    anchor[cid] = idx
        for c in comments:
            c["paragraph"] = anchor.get(c["id"])

        return {"paragraphs": paragraphs, "comments": comments}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def split_chapters(paragraphs) -> list:
    """Chapters are Heading1 runs with real text. Blank headings are skipped so
    they do not create phantom chapters."""
    chapters, current = [], None
    for p in paragraphs:
        if p["style"].lower() == "heading1" and p["text"].strip():
            if current:
                current["end"] = p["i"]
                chapters.append(current)
            current = {"name": p["text"].strip(), "start": p["i"], "end": None}
    if current:
        current["end"] = paragraphs[-1]["i"] + 1
        chapters.append(current)
    return chapters


def chapter_of(chapters, i):
    for c in chapters:
        if c["start"] <= i < c["end"]:
            return c["name"]
    return "(front matter)"


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Þ‘“])", text)
    return [s.strip() for s in parts if s.strip()]


def _quote(text, span=None, width=150):
    """A short verbatim slice Benjy can search for in Word."""
    if span is None:
        return text[:width].strip()
    a, b = span
    lo = max(0, a - width // 2)
    hi = min(len(text), b + width // 2)
    return text[lo:hi].strip()


def check_notes(paragraphs, comments, chapters):
    """Every outstanding note: red [CC] markers, bracketed notes, Word comments.

    Answered/unanswered is a judgement call, so this only inventories them and
    leaves the verdict to the reconciliation pass.
    """
    out = []
    for p in paragraphs:
        stripped = p["text"].strip()
        # A paragraph that is one bracketed block is a note, whatever it opens
        # with. This catches free-text marginalia that no keyword would match.
        if (len(stripped) > 12 and stripped.startswith("[") and stripped.endswith("]")
                and stripped.count("[") == stripped.count("]")):
            colours = sorted({r["colour"] for r in p["runs"] if r["colour"]})
            out.append({
                "kind": "whole_paragraph_note",
                "paragraph": p["i"],
                "chapter": chapter_of(chapters, p["i"]),
                "colour": colours or None,
                "note": stripped,
                "context_before": (paragraphs[p["i"] - 1]["text"][-200:]
                                   if p["i"] > 0 else ""),
                "context_after": (paragraphs[p["i"] + 1]["text"][:200]
                                  if p["i"] + 1 < len(paragraphs) else ""),
            })
            continue
        for pat, kind in NOTE_PATTERNS:
            for m in re.finditer(pat, p["text"]):
                # Reconstruct the full bracketed note, which often runs past the
                # naive regex because of nested brackets.
                start = m.start()
                depth, end = 0, None
                for j in range(start, len(p["text"])):
                    if p["text"][j] == "[":
                        depth += 1
                    elif p["text"][j] == "]":
                        depth -= 1
                        if depth == 0:
                            end = j + 1
                            break
                note = p["text"][start:end] if end else p["text"][start:start + 600]
                colours = {r["colour"] for r in p["runs"]
                           if r["colour"] and note[:30] in r["text"][:200]}
                out.append({
                    "kind": kind,
                    "paragraph": p["i"],
                    "chapter": chapter_of(chapters, p["i"]),
                    "colour": sorted(c for c in colours if c) or None,
                    "note": note.strip(),
                    "context_before": p["text"][max(0, start - 200):start].strip(),
                    "context_after": p["text"][end:end + 200].strip() if end else "",
                })
    for c in comments:
        pi = c.get("paragraph")
        out.append({
            "kind": "word_comment",
            "paragraph": pi,
            "chapter": chapter_of(chapters, pi) if pi is not None else None,
            "colour": None,
            "note": c["text"],
            "author": c["author"],
            "anchored_text": (paragraphs[pi]["text"][:300] if pi is not None
                              and pi < len(paragraphs) else ""),
        })
    return out


def check_scaffolding(paragraphs, chapters, notes):
    """Leftover agent or drafting scaffolding in the body.

    Hits inside a known note are excluded, otherwise every note that warns about
    scaffolding reports itself as scaffolding.
    """
    note_spans = defaultdict(list)
    for n in notes:
        if n["paragraph"] is not None:
            note_spans[n["paragraph"]].append(n["note"])

    out = []
    for p in paragraphs:
        for pat in SCAFFOLDING:
            for m in re.finditer(pat, p["text"], re.I):
                inside_note = any(m.group(0) in nt for nt in note_spans.get(p["i"], []))
                if inside_note:
                    continue
                out.append({
                    "paragraph": p["i"],
                    "chapter": chapter_of(chapters, p["i"]),
                    "pattern": pat,
                    "match": m.group(0),
                    "quote": _quote(p["text"], m.span()),
                })
    return out


def check_structure(paragraphs, chapters):
    out = []
    for p in paragraphs:
        if p["is_heading"] and not p["text"].strip():
            out.append({
                "issue": "blank_heading",
                "paragraph": p["i"],
                "style": p["style"],
                "chapter": chapter_of(chapters, p["i"]),
                "detail": "Empty heading paragraph. Shows as a blank row in a generated TOC.",
            })
    # Headings that are really body text: a long heading is usually a paragraph
    # that picked up the wrong style.
    for p in paragraphs:
        if p["is_heading"] and len(p["text"].split()) > 15:
            out.append({
                "issue": "heading_too_long",
                "paragraph": p["i"],
                "style": p["style"],
                "chapter": chapter_of(chapters, p["i"]),
                "detail": f"{len(p['text'].split())} words in a heading.",
                "quote": p["text"][:180],
            })
    # Duplicate headings at the same level.
    seen = defaultdict(list)
    for p in paragraphs:
        if p["is_heading"] and p["text"].strip():
            seen[(p["style"], p["text"].strip().lower())].append(p["i"])
    for (style, txt), where in seen.items():
        if len(where) > 1:
            out.append({
                "issue": "duplicate_heading",
                "paragraph": where[0],
                "style": style,
                "detail": f"Heading '{txt}' appears {len(where)} times at {where}.",
            })
    return out


def check_crossrefs(paragraphs, chapters):
    """Figure and table references against the captions that actually exist."""
    caption_re = re.compile(r"^\s*(Figure|Table)\s+([0-9]+(?:\.[0-9]+)*)\s*[:.]", re.I)
    ref_re = re.compile(r"\b(Figure|Table)\s+([0-9]+(?:\.[0-9]+)*)", re.I)

    captions, refs = {}, defaultdict(list)
    for p in paragraphs:
        m = caption_re.match(p["text"])
        if m:
            key = (m.group(1).lower(), m.group(2))
            captions.setdefault(key, []).append(p["i"])
    for p in paragraphs:
        if caption_re.match(p["text"]):
            continue
        for m in ref_re.finditer(p["text"]):
            refs[(m.group(1).lower(), m.group(2))].append(p["i"])

    out = []
    for key, where in sorted(refs.items()):
        if key not in captions:
            out.append({
                "issue": "ref_without_caption",
                "kind": key[0], "number": key[1],
                "referenced_in": where[:6],
                "chapter": chapter_of(chapters, where[0]),
                "quote": _quote(paragraphs[where[0]]["text"]),
                "detail": f"{key[0].title()} {key[1]} is referenced but no caption defines it.",
            })
    for key, where in sorted(captions.items()):
        if key not in refs:
            out.append({
                "issue": "caption_never_referenced",
                "kind": key[0], "number": key[1],
                "paragraph": where[0],
                "chapter": chapter_of(chapters, where[0]),
                "quote": _quote(paragraphs[where[0]]["text"]),
                "detail": f"{key[0].title()} {key[1]} has a caption but nothing refers to it.",
            })
    for key, where in sorted(captions.items()):
        if len(where) > 1:
            out.append({
                "issue": "duplicate_caption",
                "kind": key[0], "number": key[1],
                "paragraph": where[0],
                "detail": f"{key[0].title()} {key[1]} is captioned {len(where)} times at {where}.",
            })

    # Numbering gaps inside each chapter series.
    for kind in ("figure", "table"):
        series = defaultdict(list)
        for (k, num) in captions:
            if k != kind:
                continue
            head = num.split(".")[0]
            tail = num.split(".")[-1]
            if tail.isdigit():
                series[head].append(int(tail))
        for head, nums in sorted(series.items()):
            nums = sorted(nums)
            expected = list(range(1, max(nums) + 1))
            missing = [n for n in expected if n not in nums]
            if missing:
                out.append({
                    "issue": "numbering_gap",
                    "kind": kind,
                    "detail": f"{kind.title()} series {head}: {head}.{{{','.join(map(str, missing))}}} missing; present {nums}.",
                })
    return out


NUM_RE = re.compile(
    r"(?<![\w.])"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)"
    r"\s*(%|per cent|percent|pp|percentage points)?"
)


def check_numbers(paragraphs, chapters):
    """Every numeric claim with its sentence, for the verification pass, plus an
    automatic internal-consistency clustering."""
    claims = []
    for p in paragraphs:
        if p["is_heading"]:
            continue
        # Bibliographic numbers (arXiv ids, page ranges, volumes) are not claims.
        if chapter_of(chapters, p["i"]).strip().lower() == "references":
            continue
        for sent in _sentences(p["text"]):
            for m in NUM_RE.finditer(sent):
                raw, unit = m.group(1), (m.group(2) or "").strip()
                # Skip pure section/figure pointers and years.
                lead = sent[max(0, m.start() - 12):m.start()].lower()
                if re.search(r"(figure|table|section|chapter|appendix|§|fm-|exp-|d\d)\s*$", lead):
                    continue
                if re.search(r"(arxiv|doi|pp?\.|vol\.|isbn|no\.)\s*[:.]?\s*$", lead):
                    continue
                # arXiv-style identifiers: 2303.17651
                if re.match(r"^\d{4}\.\d{4,5}$", raw):
                    continue
                val = float(raw.replace(",", ""))
                if not unit and 1900 <= val <= 2100 and float(val).is_integer():
                    continue  # a year
                # Signature is the content words immediately around the number,
                # not the whole sentence. A wider window matches unrelated
                # claims that merely share topic vocabulary.
                head = sent[:m.start()]
                tail = sent[m.end():]
                window = " ".join(head.split()[-WINDOW:] + tail.split()[:WINDOW])
                claims.append({
                    "paragraph": p["i"],
                    "chapter": chapter_of(chapters, p["i"]),
                    "in_table": p["in_table"],
                    "value": raw,
                    "unit": _norm_unit(unit),
                    "sentence": sent.strip(),
                    "sig": sorted(_content_words(window)),
                })

    conflicts = _number_conflicts(claims)
    return claims, conflicts


WINDOW = 6

STOP = set("""the a an of in on for to and or is are was were be been being with by
    at from as that this these those it its their our we they not no than then
    when which who whom whose but if so such over under between within into onto
    across per each every all any some most more less least about around up down
    out only also just both either neither because while after before against
    same other another had has have where there here what how why value values
    total number numbers point points cent percent percentage records reports
    report recorded gives give given puts put sits sit stands stand""".split())


def _content_words(text):
    return {w for w in re.findall(r"[a-z][a-z\-]{3,}", text.lower()) if w not in STOP}


def _norm_unit(unit):
    u = (unit or "").strip().lower()
    if u in {"%", "per cent", "percent"}:
        return "%"
    if u in {"pp", "percentage points"}:
        return "pp"
    return ""


def _number_conflicts(claims):
    """A conflict is the same quantity stated twice with different values.

    Guards, in order of how much noise each removes: never compare numbers from
    the same sentence, require the same unit, and require the local windows to
    overlap heavily rather than merely share a topic word.
    """
    conflicts, seen = [], set()
    by_unit = defaultdict(list)
    for c in claims:
        by_unit[c["unit"]].append(c)

    for unit, items in by_unit.items():
        for i in range(len(items)):
            a = items[i]
            if len(a["sig"]) < 3:
                continue
            for j in range(i + 1, len(items)):
                b = items[j]
                if a["sentence"] == b["sentence"]:
                    continue          # two numbers in one sentence are not a conflict
                if a["value"] == b["value"]:
                    continue
                if len(b["sig"]) < 3:
                    continue
                sa, sb = set(a["sig"]), set(b["sig"])
                shared = sa & sb
                if len(shared) < 3:
                    continue
                jaccard = len(shared) / len(sa | sb)
                if jaccard < 0.45:
                    continue
                key = tuple(sorted([(a["paragraph"], a["value"]),
                                    (b["paragraph"], b["value"])]))
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append({
                    "issue": "possible_number_conflict",
                    "shared_terms": sorted(shared),
                    "overlap": round(jaccard, 2),
                    "unit": unit,
                    "a": {"value": a["value"], "chapter": a["chapter"],
                          "paragraph": a["paragraph"], "sentence": a["sentence"]},
                    "b": {"value": b["value"], "chapter": b["chapter"],
                          "paragraph": b["paragraph"], "sentence": b["sentence"]},
                })
    conflicts.sort(key=lambda c: (-c["overlap"], -len(c["shared_terms"])))
    return conflicts


def check_style(paragraphs, chapters):
    """House-style violations from CLAUDE.md. Each has one correct answer.

    The References section is exempt: published titles are quoted as printed, so
    'Computers in Human Behavior' is correct there and an en dash in a title is
    the publisher's, not his.
    """
    out = []
    for p in paragraphs:
        if p["is_heading"]:
            continue
        if chapter_of(chapters, p["i"]).strip().lower() == "references":
            continue
        t = p["text"]
        for m in re.finditer("—", t):
            out.append({"issue": "em_dash", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "quote": _quote(t, m.span())})
        for w in BANNED_WORDS:
            for m in re.finditer(r"\b" + re.escape(w), t, re.I):
                out.append({"issue": "banned_word", "word": w, "paragraph": p["i"],
                            "chapter": chapter_of(chapters, p["i"]),
                            "quote": _quote(t, m.span())})
        for pat, uk in US_SPELLINGS:
            for m in re.finditer(pat, t, re.I):
                out.append({"issue": "us_spelling", "found": m.group(0), "uk": uk,
                            "paragraph": p["i"],
                            "chapter": chapter_of(chapters, p["i"]),
                            "quote": _quote(t, m.span())})
    return out


def check_spag(paragraphs, chapters):
    out = []
    for p in paragraphs:
        t = p["text"]
        if not t.strip() or p["is_heading"]:
            continue
        for m in re.finditer(r"\b(\w+)\s+\1\b", t, re.I):
            if m.group(1).lower() in {"had", "that", "very"}:
                continue
            out.append({"issue": "repeated_word", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "match": m.group(0), "quote": _quote(t, m.span())})
        for m in re.finditer(r"\s{2,}", t):
            out.append({"issue": "double_space", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "quote": _quote(t, m.span())})
        for m in re.finditer(r"\s+[,.;:!?]", t):
            out.append({"issue": "space_before_punctuation", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "quote": _quote(t, m.span())})
        for m in re.finditer(r"\(\s|\s\)", t):
            out.append({"issue": "bracket_spacing", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "quote": _quote(t, m.span())})
        # Unbalanced brackets, which usually means a truncated note.
        if t.count("(") != t.count(")"):
            out.append({"issue": "unbalanced_parens", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "quote": _quote(t)})
        if t.count("[") != t.count("]"):
            out.append({"issue": "unbalanced_brackets", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "quote": _quote(t)})
        if not p["in_table"] and len(t.split()) > 25 and not re.search(r"[.!?:;\"'”’)]\s*$", t.strip()):
            out.append({"issue": "no_terminal_punctuation", "paragraph": p["i"],
                        "chapter": chapter_of(chapters, p["i"]),
                        "quote": "..." + t.strip()[-120:]})
    return out


def check_duplicates(paragraphs, chapters):
    """Sentences repeated across the document. Catches copy-paste drift between
    the abstract, results and conclusion."""
    index = defaultdict(list)
    for p in paragraphs:
        if p["is_heading"] or p["in_table"]:
            continue
        for s in _sentences(p["text"]):
            norm = re.sub(r"[^a-z0-9 ]", "", s.lower())
            norm = re.sub(r"\s+", " ", norm).strip()
            if len(norm.split()) >= 12:
                index[norm].append((p["i"], s))
    out = []
    for norm, hits in index.items():
        if len(hits) > 1:
            out.append({
                "issue": "duplicate_sentence",
                "count": len(hits),
                "paragraphs": [h[0] for h in hits],
                "chapters": sorted({chapter_of(chapters, h[0]) for h in hits}),
                "quote": hits[0][1][:220],
            })
    return sorted(out, key=lambda d: -d["count"])


def check_citations(paragraphs, chapters):
    """Citations in the body against the References section, both directions."""
    ref_start = ref_end = None
    for p in paragraphs:
        if p["is_heading"] and p["text"].strip().lower() == "references":
            ref_start = p["i"]
        elif ref_start is not None and p["is_heading"] and p["style"].lower() == "heading1" \
                and p["text"].strip():
            ref_end = p["i"]
            break
    if ref_start is None:
        return [{"issue": "no_references_section",
                 "detail": "No Heading1 'References' found."}], []

    ref_end = ref_end or len(paragraphs)
    refs = [p["text"].strip() for p in paragraphs[ref_start + 1:ref_end] if p["text"].strip()]
    reftext = " ".join(refs)
    bodytext = " ".join(p["text"] for p in paragraphs[:ref_start])

    months = {"January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"}

    cite_re = re.compile(
        r"\b([A-Z][a-zA-ZÀ-ſ\-]+)"
        r"(?:\s+(?:et\s+al\.?|and\s+[A-Z][a-zA-Z\-]+|&\s*[A-Z][a-zA-Z\-]+))?"
        r"[,\s]*\(?((?:19|20)\d{2})[a-z]?\)?")

    cited = defaultdict(set)
    for m in cite_re.finditer(bodytext):
        name, year = m.group(1), m.group(2)
        if name in months:
            continue
        cited[name].add(year)

    out = []
    for name, years in sorted(cited.items()):
        if name not in reftext:
            out.append({"issue": "cited_not_in_references", "author": name,
                        "years": sorted(years),
                        "detail": f"'{name}' cited in body, absent from References."})
        else:
            for y in sorted(years):
                # Same surname present but that year missing is a year typo.
                window = [r for r in refs if name in r]
                if window and not any(y in r for r in window):
                    out.append({"issue": "citation_year_mismatch", "author": name,
                                "body_year": y,
                                "reference_entries": [r[:160] for r in window[:3]],
                                "detail": f"Body cites {name} {y}; References has no {y} entry for {name}."})

    orphan = []
    for r in refs:
        m = re.match(r"\s*\[?CC", r)
        if m:
            orphan.append({"issue": "note_inside_references", "quote": r[:220]})
            continue
        m = re.match(r"([A-Z][a-zA-ZÀ-ſ\-]+)", r.strip())
        if m and m.group(1) not in bodytext:
            orphan.append({"issue": "reference_never_cited", "author": m.group(1),
                           "quote": r[:200],
                           "detail": f"'{m.group(1)}' in References, never cited in body."})
    return out, orphan


def check_red_runs(paragraphs, chapters):
    """Inventory of red text. The red is incorporated prose and stays, but it is
    also where drafted-by-agent text ended up, so it is the target set for the
    AI-prose pass."""
    out = []
    for p in paragraphs:
        for r in p["runs"]:
            if r["colour"] in RED_COLOURS and r["text"].strip():
                out.append({
                    "paragraph": p["i"],
                    "chapter": chapter_of(chapters, p["i"]),
                    "colour": r["colour"],
                    "bold": r["bold"],
                    "size": r["size"],
                    "in_table": p["in_table"],
                    "words": len(r["text"].split()),
                    "text": r["text"].strip(),
                })
    return out


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def run(docx_path: str, outdir: str) -> dict:
    doc = extract(docx_path)
    paragraphs, comments = doc["paragraphs"], doc["comments"]
    chapters = split_chapters(paragraphs)

    notes = check_notes(paragraphs, comments, chapters)
    claims, conflicts = check_numbers(paragraphs, chapters)
    cite_missing, cite_orphan = check_citations(paragraphs, chapters)

    report = {
        "source": os.path.abspath(docx_path),
        "totals": {
            "paragraphs": len(paragraphs),
            "words": sum(len(p["text"].split()) for p in paragraphs),
            "chapters": len(chapters),
            "headings": sum(1 for p in paragraphs if p["is_heading"]),
        },
        "chapters": chapters,
        "notes": notes,
        "scaffolding": check_scaffolding(paragraphs, chapters, notes),
        "structure": check_structure(paragraphs, chapters),
        "crossrefs": check_crossrefs(paragraphs, chapters),
        "number_claims": claims,
        "number_conflicts": conflicts,
        "style": check_style(paragraphs, chapters),
        "spag": check_spag(paragraphs, chapters),
        "duplicates": check_duplicates(paragraphs, chapters),
        "citations_missing": cite_missing,
        "citations_orphan": cite_orphan,
        "red_runs": check_red_runs(paragraphs, chapters),
    }

    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "report.json"), "w") as f:
        json.dump(report, f, indent=1)

    # Per-chapter plain text, for the chapter agents.
    chdir = os.path.join(outdir, "chapters")
    os.makedirs(chdir, exist_ok=True)
    for n, c in enumerate(chapters):
        slug = re.sub(r"[^a-z0-9]+", "_", c["name"].lower()).strip("_")[:40]
        lines = []
        for p in paragraphs[c["start"]:c["end"]]:
            if not p["text"].strip():
                continue
            prefix = "### " if p["is_heading"] else ""
            lines.append(prefix + p["text"])
        with open(os.path.join(chdir, f"{n:02d}_{slug}.txt"), "w") as f:
            f.write("\n\n".join(lines))

    with open(os.path.join(outdir, "full.txt"), "w") as f:
        f.write("\n\n".join(p["text"] for p in paragraphs if p["text"].strip()))

    return report


def summarise(report):
    t = report["totals"]
    print(f"words {t['words']}  paragraphs {t['paragraphs']}  chapters {t['chapters']}")
    print()
    rows = [
        ("outstanding notes", len(report["notes"])),
        ("scaffolding in body", len(report["scaffolding"])),
        ("structure issues", len(report["structure"])),
        ("cross-reference issues", len(report["crossrefs"])),
        ("number claims extracted", len(report["number_claims"])),
        ("possible number conflicts", len(report["number_conflicts"])),
        ("house-style violations", len(report["style"])),
        ("SPaG issues", len(report["spag"])),
        ("duplicate sentences", len(report["duplicates"])),
        ("citations missing from refs", len(report["citations_missing"])),
        ("orphan reference entries", len(report["citations_orphan"])),
        ("red runs", len(report["red_runs"])),
    ]
    for name, n in rows:
        print(f"  {name:32} {n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("docx")
    ap.add_argument("--out", default="build/qa")
    args = ap.parse_args()
    report = run(args.docx, args.out)
    summarise(report)
    print(f"\nwritten to {args.out}/report.json and {args.out}/chapters/")


if __name__ == "__main__":
    main()
