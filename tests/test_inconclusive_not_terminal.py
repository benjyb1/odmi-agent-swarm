"""Tests for the _is_abstention and _should_accept_verifier_pass helpers.

These helpers enforce that `inconclusive` is treated as an abstention and
never allowed to terminate the coordinator loop via a Verifier pass.
`not_applicable` is a valid determination and must not be treated as an
abstention.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_coordinator import _is_abstention, _should_accept_verifier_pass


class TestIsAbstention:
    # --- True cases: inconclusive in all case/whitespace variants ---

    def test_lowercase(self):
        assert _is_abstention("inconclusive") is True

    def test_leading_trailing_whitespace(self):
        assert _is_abstention("  Inconclusive  ") is True

    def test_all_caps(self):
        assert _is_abstention("INCONCLUSIVE") is True

    # --- False cases: real answers ---

    def test_yes(self):
        assert _is_abstention("yes") is False

    def test_no(self):
        assert _is_abstention("no") is False

    def test_not_applicable(self):
        # `not_applicable` is a valid determination, not an abstention.
        assert _is_abstention("not_applicable") is False

    # --- False cases: empty / None ---

    def test_empty_string(self):
        assert _is_abstention("") is False

    def test_none(self):
        assert _is_abstention(None) is False


class TestShouldAcceptVerifierPass:
    # --- Accepted: pass + real answer ---

    def test_pass_yes(self):
        assert _should_accept_verifier_pass("pass", "yes") is True

    def test_pass_not_applicable(self):
        # `not_applicable` is valid; a pass on it must be accepted.
        assert _should_accept_verifier_pass("pass", "not_applicable") is True

    # --- Rejected: pass + inconclusive abstention ---

    def test_pass_inconclusive(self):
        assert _should_accept_verifier_pass("pass", "inconclusive") is False

    def test_pass_inconclusive_with_whitespace(self):
        assert _should_accept_verifier_pass("pass", "  inconclusive ") is False

    # --- Rejected: fail verdict, regardless of answer ---

    def test_fail_yes(self):
        assert _should_accept_verifier_pass("fail", "yes") is False
