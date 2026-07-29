"""Tests for the EXP-40 cooperative arm and the D24 verifier-counter-source
deny-list fix.

Covers:
  - the pure deny-list scrub helper (verdict kept, ODMI source stripped);
  - the fair corroborate V2 prompt (anti-rubber-stamp, steps 1-3 shared);
  - the attempt-1 seed reconstruction against the DB (skipped if exp34 absent).
"""
from __future__ import annotations

import sqlite3

import pytest

from agents.models import VerifierOutput
from agents.verifier import _scrub_forbidden_counter_source
import agents.prompts.verifier as vp


def _fail_output(counter_url: str) -> VerifierOutput:
    return VerifierOutput(
        verdict="fail",
        verifier_answer="no",
        verifier_confidence=0.7,
        substring_check_result="pass",
        rejection_reason="the answer looks wrong",
        counter_evidence_quote="ODMI reports this country scored low",
        counter_source_url=counter_url,
    )


def test_denylist_scrub_strips_odmi_mirror_keeps_verdict():
    out = _fail_output("https://www.europeandataportal.eu/en/impact-studies/x")
    scrubbed = _scrub_forbidden_counter_source(out)
    assert scrubbed is not None, "a blocked ODMI mirror must be scrubbed"
    assert scrubbed.counter_source_url is None
    assert "europeandataportal" not in (scrubbed.counter_evidence_quote or "")
    assert "ODMI reports" not in (scrubbed.counter_evidence_quote or "")
    # verdict is left intact so the loop retries for an admissible source
    assert scrubbed.verdict == "fail"
    assert "forbidden_odmi_source" in scrubbed.rejection_reason


def test_denylist_scrub_passes_clean_source():
    out = _fail_output("https://data.gouv.fr/some/page")
    assert _scrub_forbidden_counter_source(out) is None


def test_denylist_scrub_ignores_pass_with_no_source():
    out = VerifierOutput(
        verdict="pass",
        verifier_answer="yes",
        verifier_confidence=0.8,
        substring_check_result="pass",
    )
    assert _scrub_forbidden_counter_source(out) is None


def test_corroborate_is_fair_not_strawman():
    """The properties EXP-40 needed from the corroborative prompt.

    Version bumped 2 -> 3 for EXP-42, which added the staleness mirror to the
    preamble. The fairness properties below are unchanged by that and are
    asserted here for both versions; the V3-specific checks live in
    tests/test_exp42_stance.py.
    """
    spec = vp.STRATEGIES["verifier-corroborate"]
    assert spec.version >= 2, "V1 was the strawman and must never be live again"
    sys = spec.system
    # the anti-rubber-stamp guard is present
    assert "Adjacency is not corroboration" in sys
    # the V1 strawman phrasing is gone
    assert "default stance is confirmation-seeking" not in sys
    assert "Related material on the same topic counts toward support" not in sys
    # steps 1-3 shared with disprove base (the one-variable claim)
    dis = vp.STRATEGIES["verifier-disprove"].system
    for probe in ("Substring check.", "Source authority.",
                  "Evidence fit. Does the quoted passage"):
        assert probe in sys and probe in dis, probe


def test_seed_reconstruction_from_exp34():
    """Integration: reconstruct a seed from a real exp34 wide_only row.

    Skips cleanly if this DB has not been synced from canonical (the seed
    rows live there), so the suite passes on a fresh worktree DB too.
    """
    from agents.tools.db import DB_PATH
    from scripts.run_coordinator import _seed_researcher_from_experiment

    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT question_id, country_code FROM phase2_researcher_runs "
        "WHERE experiment_id='exp34_retrieval_strategy_s46' "
        "AND condition_label='wide_only' AND retry_count=0 "
        "AND answer IS NOT NULL AND lower(trim(answer))!='inconclusive' LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        pytest.skip("exp34 wide_only not in this DB (sync from canonical first)")

    q, cc = row
    seed = _seed_researcher_from_experiment(
        seed_experiment_id="exp34_retrieval_strategy_s46",
        seed_condition_label="wide_only",
        question_id=q, country_code=cc,
    )
    assert seed is not None
    seed_row, snippets = seed
    assert seed_row["answer"] and seed_row["evidence_quote"]
    # snippets rebuilt as SearchResult objects the Verifier can read
    for s in snippets:
        assert hasattr(s, "snippet") and hasattr(s, "url")

    # a non-existent pair falls back (None -> live researcher)
    assert _seed_researcher_from_experiment(
        seed_experiment_id="exp34_retrieval_strategy_s46",
        seed_condition_label="wide_only",
        question_id="ZZZ-nope", country_code="XX",
    ) is None
