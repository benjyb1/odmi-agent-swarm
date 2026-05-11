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
