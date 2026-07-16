"""EXP-39 Part A, step 1: freeze the machine translations.

Standalone script: needs `argostranslate` and `langdetect`, which do not
resolve inside the project venv (spacy has no CPython 3.14 wheels under the
project's constraint set). Run it in any side venv:

  uv venv /tmp/exp39mt && uv pip install --python /tmp/exp39mt/bin/python \
      argostranslate langdetect
  /tmp/exp39mt/bin/python evaluation/exp39_translate.py

It reads the 150 frozen EXP-11 stage-1 candidates, language-IDs each
candidate's evidence surface (evidence quote + adversarial snippet texts),
keeps the English-evidence subset, translates that surface en->fr, en->bg
and en->sq with argostranslate (OPUS-MT models, local CPU, versioned), and
writes one JSONL record per (cand_id, target_lang) to
`evaluation/results/exp39_translations.jsonl`, including the argos package
versions used. The JSONL is the frozen translation artefact: step 2
(`exp39_language_swap.py`, project venv) makes the LLM calls from it, so an
examiner can replay the LLM step without installing any MT tooling.

Translation unit: the evidence the verifier reads. The researcher's
evidence_quote and each adversarial snippet text are translated; queries,
the researcher's own English reasoning, and all prompt scaffolding stay
English, mirroring the production shape of a native-evidence pair (English
question, English agent prose, national-language evidence).

Deterministic given the installed argos package versions; re-running
overwrites the JSONL wholesale (no partial appends), so the artefact is
always a single coherent generation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0

RESULTS = Path(__file__).resolve().parent / "results"
STAGE1 = RESULTS / "verifier_redesign_verifier_tristate_v1.jsonl"
OUT = RESULTS / "exp39_translations.jsonl"
TARGETS = ["fr", "bg", "sq"]
MIN_DETECT_CHARS = 40


def load_freezes() -> dict[str, dict]:
    fr = {}
    for line in STAGE1.open():
        rec = json.loads(line)
        if rec["kind"] == "freeze":
            fr[rec["cand_id"]] = rec
    return fr


def evidence_surface(rec: dict) -> tuple[str, list[str]]:
    fz = rec["freeze"]
    quote = fz["evidence_quote"] or ""
    snips = [s["snippet"] for s in fz["adversarial_snippets"]]
    return quote, snips


def main() -> None:
    import argostranslate.package as apkg
    import argostranslate.translate as atrans

    apkg.update_package_index()
    installed = {}
    for pkg in apkg.get_available_packages():
        if pkg.from_code == "en" and pkg.to_code in TARGETS:
            apkg.install_from_path(pkg.download())
            installed[pkg.to_code] = f"{pkg.package_version}"
    missing = [t for t in TARGETS if t not in installed]
    if missing:
        sys.exit(f"argos lacks en->{missing}; aborting")

    freezes = load_freezes()
    english, skipped = [], []
    for cid, rec in sorted(freezes.items()):
        quote, snips = evidence_surface(rec)
        surface = " ".join([quote] + snips).strip()
        if len(surface) < MIN_DETECT_CHARS:
            skipped.append((cid, "too_short"))
            continue
        try:
            lang = detect(surface)
        except Exception:  # noqa: BLE001
            skipped.append((cid, "detect_error"))
            continue
        if lang == "en":
            english.append(cid)
        else:
            skipped.append((cid, lang))

    print(f"{len(freezes)} candidates: {len(english)} English-evidence, "
          f"{len(skipped)} excluded")
    from collections import Counter
    print("excluded by:", Counter(reason for _, reason in skipped))

    records = []
    for i, cid in enumerate(english, 1):
        rec = freezes[cid]
        quote, snips = evidence_surface(rec)
        for target in TARGETS:
            records.append(
                dict(
                    cand_id=cid,
                    target_lang=target,
                    argos_package_version=installed[target],
                    evidence_quote_translated=atrans.translate(quote, "en", target)
                    if quote.strip() else "",
                    snippets_translated=[
                        atrans.translate(s, "en", target) if s.strip() else ""
                        for s in snips
                    ],
                )
            )
        if i % 10 == 0:
            print(f"  translated {i}/{len(english)}")

    with OUT.open("w") as fh:
        fh.write(json.dumps(dict(
            kind="meta",
            english_subset=english,
            excluded=[{"cand_id": c, "reason": r} for c, r in skipped],
            targets=TARGETS,
            argos_versions=installed,
            langdetect_seed=0,
        )) + "\n")
        for r in records:
            fh.write(json.dumps(r) + "\n")
    print(f"Wrote {len(records)} translation records to {OUT}")


if __name__ == "__main__":
    main()
