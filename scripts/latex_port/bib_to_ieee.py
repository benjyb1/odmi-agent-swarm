"""Convert references.bib from biblatex fields to what IEEEtranN.bst reads.

The KCL template (Final Report Latex Template, 7CCSMPRJ) builds its
bibliography with BibTeX and an IEEE .bst, not with biblatex and biber.
BibTeX ignores any field it does not know, silently, so a straight swap
of the style would have dropped every journal name, every arXiv
identifier and every DOI without a word of complaint. This script does
the mapping explicitly and reports it.

Mappings, all reversible:

  journaltitle -> journal
  location     -> address
  @report      -> @techreport
  doi          -> url = https://doi.org/<doi>   (nothing else prints it)
  eprint + eprinttype=arxiv -> note fragment "arXiv:<id>"
  urldate      -> note fragment "accessed <D Month YYYY>"

BibTeX also case-folds titles to sentence case, which is correct IEEE
style but destroys proper nouns that are not braced. BRACE_TITLES lists
every protection applied, one line per entry, so the choice is auditable
rather than a regex guessing at capitals.

Usage: python3 bib_to_ieee.py in.bib out.bib
"""

import re
import sys
from collections import Counter

MONTHS = ("January February March April May June July August September "
          "October November December").split()

RENAME = {"journaltitle": "journal", "location": "address"}

# Proper nouns that must survive BibTeX's sentence-casing. Keyed by cite
# key; each pair is (as written, as braced). Everything not listed here
# is ordinary prose and is meant to be lowercased.
BRACE_TITLES = {
    "anthropic2024": [("Claude", "{Claude}"), ("Opus", "{Opus}"),
                      ("Sonnet", "{Sonnet}"), ("Haiku", "{Haiku}")],
    # the formal name of the annual publication, cited as a name in the text
    "edp2024": [("Open Data Maturity Report 2024",
                 "{Open Data Maturity Report 2024}")],
    "edp2025": [("Open Data Maturity Report 2025",
                 "{Open Data Maturity Report 2025}")],
    "thellmann2024": [("European", "{European}")],
    # BibTeX lowercases the pronoun, and "trust me, i'm wrong" is wrong
    "simhi2025": [("I'm", "{I}'m")],
    # a sentence boundary BibTeX does not recognise (only colons restart
    # capitalisation), so the "A" after the question mark is protected
    "smit2024": [("? A Look", "? {A} Look")],
    "unece2025": [("HLG-MOS Report", "{HLG-MOS} Report")],
}


def split_entries(text: str):
    """Yield (preamble_or_entry_text, is_entry) in file order."""
    out, pos = [], 0
    for m in re.finditer(r"^@(\w+)\{([^,]+),\n(.*?)^\}\n", text,
                         re.S | re.M):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(0), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def parse_fields(body: str):
    """Field list in source order. Values may span lines."""
    fields = []
    for m in re.finditer(r"^\s*(\w+)\s*=\s*\{(.*?)\},?\s*$", body,
                         re.S | re.M):
        fields.append([m.group(1), m.group(2)])
    return fields


def human_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS[int(m) - 1]} {y}"


def convert(text: str) -> tuple[str, Counter]:
    stats: Counter = Counter()
    pieces = []
    for chunk, is_entry in split_entries(text):
        if not is_entry:
            pieces.append(chunk)
            continue
        m = re.match(r"^@(\w+)\{([^,]+),\n(.*?)^\}\n", chunk, re.S | re.M)
        etype, key, body = m.group(1), m.group(2), m.group(3)
        fields = parse_fields(body)
        stats["entries"] += 1

        if etype == "report":
            etype = "techreport"
            stats["report->techreport"] += 1

        note_extra, kept, applied = [], [], set()
        eprint = eprinttype = None
        for name, value in fields:
            if name == "eprint":
                eprint = value
                continue
            if name == "eprinttype":
                eprinttype = value
                continue
            if name == "urldate":
                note_extra.append(f"accessed {human_date(value)}")
                stats["urldate->note"] += 1
                continue
            if name == "doi":
                kept.append(["url", f"https://doi.org/{value}"])
                stats["doi->url"] += 1
                continue
            if name in RENAME:
                stats[f"{name}->{RENAME[name]}"] += 1
                name = RENAME[name]
            if name in ("title", "type"):
                for pair in BRACE_TITLES.get(key, []):
                    if pair[0] in value:
                        value = value.replace(pair[0], pair[1])
                        stats["title braces"] += 1
                        applied.add(pair[0])
            kept.append([name, value])

        missed = {p[0] for p in BRACE_TITLES.get(key, [])} - applied
        if missed:
            raise SystemExit(f"{key}: brace target(s) not found: {missed}")

        if eprint:
            label = "arXiv" if (eprinttype or "").lower() == "arxiv" \
                else (eprinttype or "eprint")
            note_extra.insert(0, f"{label}:{eprint}")
            stats["eprint->note"] += 1

        if note_extra:
            existing = next((f for f in kept if f[0] == "note"), None)
            if existing:
                existing[1] = existing[1] + ", " + ", ".join(note_extra)
            else:
                kept.append(["note", ", ".join(note_extra)])

        width = max(len(n) for n, _ in kept)
        lines = "\n".join(f"  {n.ljust(width)} = {{{v}}}," for n, v in kept)
        pieces.append(f"@{etype}{{{key},\n{lines}\n}}\n")
    return "".join(pieces), stats


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    text = open(src, encoding="utf-8").read()
    out, stats = convert(text)
    open(dst, "w", encoding="utf-8").write(out)
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
