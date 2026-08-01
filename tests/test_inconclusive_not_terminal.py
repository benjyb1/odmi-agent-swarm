"""Tests for the _is_abstention and _should_accept_verifier_pass helpers.

These helpers enforce that `inconclusive` is treated as an abstention and
never allowed to terminate the coordinator loop via a Verifier pass.
`not_applicable` is a valid determination and must not be treated as an
abstention.

D36 adds a COMMIT_CONFIDENCE_FLOOR (0.65): a Verifier pass is only accepted
when the answer's confidence meets the floor, preventing confident-wrong
false positives from low-confidence answers slipping through.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_coordinator import _is_abstention, _should_accept_verifier_pass


class TestIsAbstention:
    # True cases: inconclusive in all case/whitespace variants

    def test_lowercase(self):
        assert _is_abstention("inconclusive") is True

    def test_leading_trailing_whitespace(self):
        assert _is_abstention("  Inconclusive  ") is True

    def test_all_caps(self):
        assert _is_abstention("INCONCLUSIVE") is True

    # False cases: real answers

    def test_yes(self):
        assert _is_abstention("yes") is False

    def test_no(self):
        assert _is_abstention("no") is False

    def test_not_applicable(self):
        # `not_applicable` is a valid determination, not an abstention.
        assert _is_abstention("not_applicable") is False

    # False cases: empty / None

    def test_empty_string(self):
        assert _is_abstention("") is False

    def test_none(self):
        assert _is_abstention(None) is False


class TestShouldAcceptVerifierPass:
    # Accepted: pass + real answer + confidence at or above the floor

    def test_pass_yes_above_floor(self):
        assert _should_accept_verifier_pass("pass", "yes", 0.7) is True

    def test_pass_yes_at_floor(self):
        # Exactly at the floor (0.65) must be accepted.
        assert _should_accept_verifier_pass("pass", "yes", 0.65) is True

    def test_pass_not_applicable_above_floor(self):
        # `not_applicable` is valid; a pass on it must be accepted when
        # confidence clears the floor.
        assert _should_accept_verifier_pass("pass", "not_applicable", 0.8) is True

    # Rejected: pass + real answer + confidence below the floor

    def test_pass_yes_just_below_floor(self):
        assert _should_accept_verifier_pass("pass", "yes", 0.64) is False

    def test_pass_yes_well_below_floor(self):
        assert _should_accept_verifier_pass("pass", "yes", 0.55) is False

    def test_pass_yes_none_confidence(self):
        # Missing confidence is treated as 0.0, so it must be rejected.
        assert _should_accept_verifier_pass("pass", "yes", None) is False

    # Rejected: pass + inconclusive abstention, regardless of confidence

    def test_pass_inconclusive_high_confidence(self):
        assert _should_accept_verifier_pass("pass", "inconclusive", 0.9) is False

    def test_pass_inconclusive_above_floor(self):
        assert _should_accept_verifier_pass("pass", "inconclusive", 0.7) is False

    def test_pass_inconclusive_with_whitespace(self):
        assert _should_accept_verifier_pass("pass", "  inconclusive ", 0.9) is False

    # Rejected: fail verdict, regardless of answer or confidence

    def test_fail_yes_above_floor(self):
        assert _should_accept_verifier_pass("fail", "yes", 0.9) is False

    def test_fail_yes_below_floor(self):
        assert _should_accept_verifier_pass("fail", "yes", 0.5) is False
