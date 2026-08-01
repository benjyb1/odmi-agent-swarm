"""The number-verification ledger must actually hold the packs it declares.

`verify_numbers.py` declared two ledger sources that did not exist, and
`build_ledger` skipped a missing file without a word. The FP-audit and EXP-41
figures were therefore never looked up at all, and every number in Chapters 4.3
and 4.6 passed the check by absence. These tests pin the three things that
stopped that being visible:

1. Every declared source resolves to a readable file.
2. The FP-audit pack is JSONL, and its tallies (not its raw records) are what
   reaches the ledger, including the verdicts that are zero.
3. The figures docs/RESULTS.md §6 and §9 quote are present in their own pack,
   not merely somewhere in the ledger.

Offline: no LLM, no DB, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scripts.verify_numbers import (  # noqa: E402
    LEDGER_SOURCES, build_ledger, load_pack, summarise_fp_audit,
)

FP_PACK = "heldout_fp_audit_merged94.jsonl"
E41_PACK = "exp41_analysis.json"


@pytest.fixture(scope="module")
def ledger():
    led, missing = build_ledger(str(REPO_ROOT))
    assert missing == [], f"declared ledger sources did not load: {missing}"
    return led


def test_every_declared_source_exists():
    absent = [s for s in LEDGER_SOURCES if not (REPO_ROOT / s).exists()]
    assert absent == [], f"LEDGER_SOURCES points at files that do not exist: {absent}"


def test_fp_audit_and_exp41_packs_are_declared():
    """The two packs whose absence went unnoticed."""
    names = {Path(s).name for s in LEDGER_SOURCES}
    assert FP_PACK in names
    assert E41_PACK in names


def test_jsonl_loads_as_records():
    recs = load_pack(str(REPO_ROOT / "evaluation/results" / FP_PACK))
    assert isinstance(recs, list)
    assert len(recs) == 94
    assert all(r["gold_answer"] == "no" for r in recs)


def test_fp_audit_tallies_match_the_register():
    """Values as published in docs/RESULTS.md §6."""
    s = summarise_fp_audit(load_pack(str(REPO_ROOT / "evaluation/results" / FP_PACK)))
    assert s["n_records"] == 94
    assert s["n_adjudicated"] == 91
    assert s["n_unadjudicated"] == 3
    # "not applicable" also occurs unscored in the pack; both spellings are one key.
    assert s["by_final_answer"] == {"yes": 91, "not_applicable": 3}
    assert s["by_country"] == {"MK": 25, "FI": 14, "ME": 13, "BA": 10,
                               "BG": 10, "SE": 10, "BE": 6, "HR": 6}
    ch = s["adjudicated"]["charitable"]
    assert (ch["genuine_error"], ch["definitional_gap"],
            ch["defensible_or_stale_gold"]) == (16, 69, 6)
    ad = s["adjudicated"]["adversarial"]
    assert (ad["swarm_over_read"], ad["ambiguous"], ad["gold_wrong"]) == (68, 23, 0)
    assert s["adjudicated"]["evidence_supports_yes"] == 7
    assert s["adjudicated"]["evidence_too_weak"] == 84
    assert s["adjudicated"]["gold_is_self_report"] == 81


def test_zero_verdicts_still_reach_the_ledger(ledger):
    """0/91 gold_wrong is the chapter's headline. Counted from the data alone
    the key would be missing, because no record carries that verdict."""
    paths = ledger.get(0.0, [])
    assert f"{FP_PACK}::adjudicated.adversarial.gold_wrong" in paths


def _in_pack(ledger, value, pack, dp):
    for lv, paths in ledger.items():
        if round(lv, dp) == round(value, dp) and abs(lv - value) < 10 ** -dp:
            if any(p.startswith(pack) for p in paths):
                return True
    return False


# docs/RESULTS.md §6, the false-positive audit.
S6_FIGURES = [94, 91, 3, 16, 69, 6, 81, 7, 84, 68, 23, 0, 25, 14, 13]

# docs/RESULTS.md §9, EXP-41 reproducibility.
S9_FIGURES = [148, 0.7027, 0.654, 0.0143, 0.0541, 0.9216, 0.849, 0.6053,
              47, 42, 17, 0.8936, 0.4662, 0.6912, 74]


@pytest.mark.parametrize("value", S6_FIGURES)
def test_section6_figure_is_in_the_fp_pack(ledger, value):
    assert _in_pack(ledger, value, FP_PACK, 10), \
        f"§6 figure {value} is not in {FP_PACK}"


@pytest.mark.parametrize("value", S9_FIGURES)
def test_section9_figure_is_in_the_exp41_pack(ledger, value):
    dp = 3 if isinstance(value, float) else 10
    assert _in_pack(ledger, value, E41_PACK, dp), \
        f"§9 figure {value} is not in {E41_PACK}"


def test_missing_source_is_reported_not_swallowed(tmp_path, monkeypatch):
    """A source that goes absent must surface, which is the whole defect."""
    import scripts.verify_numbers as vn
    monkeypatch.setattr(vn, "LEDGER_SOURCES", ["evaluation/results/does_not_exist.json"])
    led, missing = vn.build_ledger(str(tmp_path))
    assert led == {}
    assert len(missing) == 1
    assert "does_not_exist.json" in missing[0]
