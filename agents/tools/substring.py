"""Normalised substring check for the Verifier.

Per Q11 (resolved), the check is normalised: lowercase, whitespace
collapsed, punctuation stripped. Strict literal match is too brittle:
quotes from search snippets and quotes from the live page often
differ in whitespace, smart-quotes, or non-breaking spaces.

The check answers one question only: is the Verifier's quote actually
present in the fetched page content? It does not interpret meaning.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Sequence


_WS_RE = re.compile(r"\s+")
# Strip punctuation but keep alphanumerics and spaces. Hyphens and
# apostrophes are normalised away because they vary between sources.
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)


def normalise(text: str) -> str:
    """Lowercase, NFKC-normalise, strip punctuation, collapse whitespace.

    NFKC handles smart quotes and non-breaking spaces so a snippet
    that says "Loi pour une République numérique" matches a page that
    says "Loi pour une République numérique" with non-breaking spaces.
    """
    nfkc = unicodedata.normalize("NFKC", text)
    lowered = nfkc.casefold()
    no_punct = _PUNCT_RE.sub(" ", lowered)
    collapsed = _WS_RE.sub(" ", no_punct).strip()
    return collapsed


def contains(haystack: str, needle: str) -> bool:
    """True iff the normalised needle appears as a substring of the
    normalised haystack.
    """
    if not needle or not needle.strip():
        return False
    return normalise(needle) in normalise(haystack)


# Matcher v2 (EXP-11 P4): per-snippet, ellipsis-aware, with provenance.
#
# v1 (`contains`) joins all snippets into one corpus before matching,
# which lets a quote stitched across the junction of two unrelated
# snippets pass (the normalised "\n\n" join collapses to a space, so
# fragments that sit either side of the boundary read as contiguous).
# v1 also matches very short quotes, the FM-11 false-match risk.
#
# v2 fixes both: a quote may be a single passage or an ellipsis-joined
# set of fragments, but every fragment must clear a minimum length and
# all fragments must appear, in order, inside ONE snippet. Same-passage
# elision stays legal and checkable; cross-source splicing cannot pass.
# The matched snippet index is returned so the caller can record
# provenance (and flag a quote-URL mismatch, FM-10).
#
# See docs/EXPERIMENTS_VERIFIER_REDESIGN.md S0.1 and
# docs/VERIFIER_REDESIGN.md section 7.

# Minimum length, in normalised characters, of every quote fragment.
# A fragment shorter than this is too weak to be a grounding match
# (FM-11). ResearcherOutput.evidence_quote has a raw min_length of 10,
# so a handful of real quotes sit below this floor; the S0.1 replay
# measures how many, before the gate ships.
MIN_FRAGMENT_CHARS = 15

# Ellipsis markers that join fragments of a stitched quote. Matches a
# run of two or more dots or the U+2026 ellipsis, optionally wrapped in
# square brackets, with surrounding whitespace eaten. A run of >=2 dots
# avoids splitting on sentence-internal abbreviations ("e.g.", "U.S.").
_ELLIPSIS_RE = re.compile(r"\s*(?:\[\s*(?:\.{2,}|…)\s*\]|\.{2,}|…)\s*")


@dataclass(frozen=True)
class MatchResult:
    """Outcome of a v2 match.

    `matched` is the verdict. `snippet_index` is the index of the
    snippet that carried every fragment (provenance), or None on a
    miss. `reason` explains a miss:
      - 'fragment_too_short': a fragment is under MIN_FRAGMENT_CHARS.
      - 'cross_snippet_only': v1 would have matched the joined corpus,
        but no single snippet holds every fragment (the splice case).
      - 'no_match': the quote is absent under both matchers.
    `n_fragments` is the fragment count after the ellipsis split.
    """

    matched: bool
    snippet_index: Optional[int] = None
    reason: Optional[str] = None
    n_fragments: int = 0


def split_fragments(needle: str) -> List[str]:
    """Split a quote on ellipsis markers into its fragments.

    A quote with no ellipsis returns a single-element list. Empty
    pieces (e.g. a leading ellipsis) are dropped.
    """
    parts = _ELLIPSIS_RE.split(needle)
    return [p for p in (s.strip() for s in parts) if p]


def _fragments_in_order(norm_snippet: str, norm_fragments: Sequence[str]) -> bool:
    """True iff every fragment appears in `norm_snippet`, in order, no
    overlap. Both inputs must already be normalised.
    """
    pos = 0
    for frag in norm_fragments:
        idx = norm_snippet.find(frag, pos)
        if idx == -1:
            return False
        pos = idx + len(frag)
    return True


def contains_v2(snippets: Sequence[str], needle: str) -> MatchResult:
    """Per-snippet, ellipsis-aware grounding check.

    `snippets` is the list of snippet texts the agent read (not a
    pre-joined corpus). Returns a MatchResult; `.matched` is the
    verdict the caller acts on.
    """
    if not needle or not needle.strip():
        return MatchResult(False, None, "no_match", 0)

    norm_fragments = [normalise(f) for f in split_fragments(needle)]
    norm_fragments = [f for f in norm_fragments if f]
    n = len(norm_fragments)
    if n == 0:
        return MatchResult(False, None, "no_match", 0)

    if any(len(f) < MIN_FRAGMENT_CHARS for f in norm_fragments):
        return MatchResult(False, None, "fragment_too_short", n)

    for i, snip in enumerate(snippets):
        if snip and _fragments_in_order(normalise(snip), norm_fragments):
            return MatchResult(True, i, None, n)

    # No single snippet carried every fragment. Distinguish a genuine
    # absence from a cross-snippet splice that v1 would have waved
    # through, so the replay can count the splices v2 newly catches.
    corpus = "\n\n".join(s for s in snippets if s)
    if contains(corpus, needle):
        return MatchResult(False, None, "cross_snippet_only", n)
    return MatchResult(False, None, "no_match", n)
