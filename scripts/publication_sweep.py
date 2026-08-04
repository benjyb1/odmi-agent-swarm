"""Publication-hygiene fan-out over the dissertation.

Reuses the overnight review harness (unit splitting, retries, resumable state,
heartbeat, watchdog) and swaps in a per-unit prompt aimed at what must not
appear in a published document, rather than at marks.

The deterministic layer is expected to have run already:
    python3 scripts/dissertation_qa.py <master> --out build/pub
    python3 scripts/verify_numbers.py --qa build/pub/report.json --out build/pub
    python3 scripts/ai_prose_scan.py --qa build/pub/report.json
    python3 scripts/package_audit.py <master> --out build/pub
    python3 scripts/pub_hygiene_scan.py --qa build/pub/report.json --out build/pub

Usage:
    python3 scripts/publication_sweep.py --qa build/pub --out build/pubsweep
    python3 scripts/publication_sweep.py --qa build/pub --out build/pubsweep --resume
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from overnight_review import (  # noqa: E402
    Supervisor, build_units, READ_TOOLS,
)

PROJECT = (
    "The document is an MSc Advanced Computing dissertation (King's College "
    "London). It reports an LLM agent swarm that answers EU Open Data Maturity "
    "Index (ODMI) questions across 36 countries, validated against ODMI's "
    "published answer key. Three agent roles (Researcher, Verifier, "
    "Adjudicator) debate and may abstain. Held-out evaluation is 8 countries x "
    "143 questions = 1,144 pairs."
)

SETTLED = (
    "ALREADY VERIFIED BY A PRIOR PASS. Do NOT report any of these, they are "
    "correct as they stand and re-raising them wastes the author's remaining "
    "time:\n"
    "- Every number in the document. 101 of 103 self-checking sentences "
    "reconcile; the 2 that do not are verbatim quotes from Fumega and Gao "
    "(2026) whose own arithmetic does not reconcile, and the document says so.\n"
    "- Opus 4.6 as the audit judge and Opus 4.8 as the cost-comparison model. "
    "Both are correct, they are different models used for different jobs.\n"
    "- The false-positive count convention: 91 is the headline figure, 94 is "
    "used only where the distinction between the two is stated.\n"
    "- The all-36 always-yes baseline of 81.8% over 4,146 binary golds.\n"
    "- Do NOT report that a base, denominator or population 'should be stated' "
    "or 'should be clarified'. That is not an error.\n"
    "- Do NOT report anything about text colour. Colour is handled by a "
    "separate deterministic pass and the text you are given has no colour "
    "information in it."
)

OUTPUT_CONTRACT = (
    "OUTPUT FORMAT, strictly, one block per finding, nothing else:\n\n"
    "QUOTE: <exact verbatim text copied from the file, 6-25 words, so the "
    "author can find it with Ctrl-F in Word>\n"
    "PROBLEM: <one line>\n"
    "FIX: <the exact replacement text if there is one right answer, otherwise "
    "the decision the author has to make>\n"
    "SEVERITY: MUST-NOT-SHIP | SHOULD-FIX | COSMETIC\n\n"
    "The QUOTE must be verbatim, character for character, copied from the file "
    "you were given. Paragraph numbers are useless to the reader. If you "
    "cannot quote it exactly, do not report it at all.\n"
    "SEVERITY means: MUST-NOT-SHIP is anything that would embarrass the author "
    "in a published document (an editorial note, a placeholder, an internal "
    "identifier, a sentence that contradicts itself, a claim with an obvious "
    "hole). SHOULD-FIX is a real error a reader could notice. COSMETIC is "
    "everything else.\n"
    "Do not praise anything. Do not summarise the document. Findings only. "
    "Your final message is the deliverable, so put the findings in it rather "
    "than describing what you found."
)


def unit_prompt(name, unit_path, qa_out):
    return f"""You are doing a publication-hygiene pass over part of an MSc dissertation that is about to be published. The author will not read it again in full. Assume anything you miss ships. READ-ONLY: you have Read, Grep and Glob. Do not attempt to edit anything.

{PROJECT}

YOUR TEXT: {unit_path}
Read that file in full. It is one part of the document, named "{name}". Every finding must come from that file.

Supporting material you may read if you need to check a claim against the rest of the document:
- {qa_out}/chapters/  (the other chapters)
- evaluation/results/exp36_headline.json  (canonical numbers)
- RESULTS.md

WHAT TO LOOK FOR, in this order of importance.

1. EDITORIAL AND PERSONAL NOTES. Any bracketed aside, any [CC:...] marker, any note to self, any instruction left in the body, any fragment written in an informal or exasperated register that was clearly a note rather than prose. A real example that survived in this document until recently: "[TABLE IS MISSING] AND IVE MESSED WITH THES SECTION ORDERING". Report EVERY bracketed fragment you find and let the author decide. Do not filter to the ones you judge important.

2. INTERNAL IDENTIFIERS that mean nothing to an outside reader: database paths, file paths, experiment ids, branch or worktree names, script names, localhost addresses, table names from a schema. Confirmed present elsewhere in this document: "data/odmi.db", "exp34_retrieval_strategy_s46", "exp36_model_opus". There will be more. For each, the FIX is either a rewording for an outside reader or moving the identifier to a footnote, so say which.

3. PLACEHOLDERS AND SCAFFOLDING: TODO, TBC, TBD, XXX, FIXME, [REF], FIGURE X, TABLE X, "STILL NEEDS DOING", "lorem", empty brackets, and any caption of the form "Table N Caption:".

4. SPaG that a script cannot catch. Spelling, agreement, tense, punctuation, doubled words, missing terminal punctuation, unbalanced brackets. A deterministic script has already found the mechanical ones, so spend your effort on the wrong word that is correctly spelled: "affect" for "effect", "principle" for "principal", "compliment" for "complement", "discrete" for "discreet", a plural verb on a singular subject, a tense that slips mid-paragraph.

5. HOUSE STYLE. UK English throughout. No em dashes. Never the word "genuinely". No AI-tell vocabulary: delve, crucial, landscape, testament, underscore, tapestry, navigate. No "it is important to note". Note that verbatim quotations from a source keep the source's own spelling, so a US spelling inside quotation marks is correct and is not a finding.

6. ANYTHING YOU WOULD BE EMBARRASSED TO SEE IN PRINT. A sentence that trails off unfinished. A heading with no section under it. A figure or table referenced but never shown, or shown but never referenced. A sentence that contradicts the one before it. A claim with an obvious hole in it. A sentence carrying two ideas that collide. Use judgement and report it.

{SETTLED}

Report every finding you are confident in. There is no cap, but a false finding costs the author more than a missed cosmetic one, so do not pad.

{OUTPUT_CONTRACT}
"""


def package_prompt(qa_out, out):
    return f"""You are doing the package-level check on an MSc dissertation .docx that is about to be published. These problems are invisible to any pass over the text: they live in the zip archive. READ-ONLY.

{PROJECT}

Read {qa_out}/package_audit.json in full. It is a deterministic dump of the .docx treated as a zip archive, produced by scripts/package_audit.py. Read that script too if you need to know exactly what a field means: scripts/package_audit.py

Go through every one of these and report what the author must deal with before publishing:

1. tracked_insertions and tracked_deletions. Unaccepted tracked changes ship as revision marks and are visible to any reader who opens the file. Report how many, by which author, and what they contain.

2. comments and comment_anchors. Word comments ship in the Review pane of the published file. Report every comment: who wrote it, what it says. Note that a comment marked resolved still ships inside the file. Pay attention to the author names on comments, which may identify a third party the author did not intend to name in a published document.

3. field_codes. Check the table of contents, page numbers and any cross-reference fields. A TOC field that has not been refreshed since the last edit shows stale page numbers. The relevant evidence is the field kinds, the dirty flag, and the LinksUpToDate property in docProps/app.xml.

4. docProps/core.xml. dc:creator, cp:lastModifiedBy, cp:revision, cp:lastPrinted, the created and modified timestamps. Say plainly what each one reveals to anyone who opens the file properties, and which of them the author may not want attached to a published document.

5. docProps/app.xml. Template and TotalTime especially.

6. media and pic_names and drawing_names. Stored image names ship inside the file. Report any that carry a local path, a person's name, or an internal identifier that means nothing to a reader.

7. vanish_runs, specVanish, highlight, shading_runs, strike_runs: hidden or marked-up text. embeddings, ole_objects, activex, vba: embedded objects beyond the images. These are expected to be zero or empty. Confirm explicitly whether each is still zero, and report it as a finding only if it is not.

8. local_paths_in_package, internal_ids_in_package, external_links_suspicious, settings. Report anything a reader should not see.

For this unit only, QUOTE may be the exact JSON key or value you are reporting on, since none of this is findable with Ctrl-F in Word. Everything else in the output contract holds.

{OUTPUT_CONTRACT}
"""


def crosscheck_prompt(qa_out):
    return f"""You are checking an MSc dissertation for the publication problems that only show up when you hold two chapters side by side. It is about to be published. READ-ONLY.

{PROJECT}

Read every chapter in {qa_out}/chapters/ .

Look ONLY for what a single-chapter reader could not see:

1. A sentence in one chapter that contradicts a sentence in another. Quote both.
2. A figure or table referenced in the text but never captioned anywhere in the document, or captioned but never referenced. The deterministic sweep flagged these candidates, so check each one against the actual text and say whether it is real or a parsing artefact: Figure 4.1.2, Figure 4.4.1, Table 4.1.2, Table 4.5.1, Table 3 and Table 7 (the last two in the Appendix) are referenced with no caption found; Figure 2.3, Figure 4.2, Table 4.4.1 and Table 4.7 have captions that nothing was found to reference.
3. A heading with no section under it, or a section promised in the Introduction and never delivered.
4. The same concept named two different ways in two chapters, where a reader would think they were different things.
5. A sentence duplicated word for word in two places. The deterministic sweep found these two, both shared between the Appendix and Background: "A tick means the work addresses and reports the criterion, not that it succeeds." and "Partial means it addresses one of the criterion's two conditions, or reports it without measuring it." Say whether the duplication is deliberate (a table legend repeated with its table) or an error.

{SETTLED}

{OUTPUT_CONTRACT}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qa", default="build/pub")
    ap.add_argument("--out", default="build/pubsweep")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    qa_out = os.path.abspath(args.qa)
    sup = Supervisor(args.out, resume=args.resume)
    os.makedirs(os.path.join(sup.out, "units"), exist_ok=True)
    sup.log("=" * 60)
    sup.log(f"publication sweep starting, pid {os.getpid()}, qa={qa_out}")

    try:
        sup.state["phase"] = "units"
        sup.save_state()
        units = build_units(sup, qa_out)
        sup.log(f"{len(units)} text units")

        jobs = []
        for name, _text in units:
            upath = os.path.join(sup.out, "units", f"{name}.txt")
            jobs.append((name, unit_prompt(name, upath, qa_out), READ_TOOLS))
        jobs.append(("_PACKAGE", package_prompt(qa_out, sup.out), READ_TOOLS))
        jobs.append(("_CROSSCHECK", crosscheck_prompt(qa_out), READ_TOOLS))
        sup.run_pool(jobs)

        sup.state["phase"] = "complete"
        sup.state["finished"] = sup.state.get("finished")
        sup.save_state()
        sup.log("COMPLETE")
    except Exception as exc:
        sup.state["phase"] = "crashed"
        sup.state["error"] = repr(exc)[:500]
        sup.save_state()
        sup.log(f"SUPERVISOR CRASHED: {exc!r}")
        raise
    finally:
        sup.stop()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
