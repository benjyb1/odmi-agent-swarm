"""Shared prompt fragments injected verbatim into multiple agent prompts.

Anything exported here is rendered into the system prompt of more than
one agent (Researcher, Verifier, Adjudicator). Editing a fragment here
changes the text every consumer sends to the model, so bump the
VERSION on each consumer when you edit so the receipts trace cleanly.

Versioning rationale. The `prompt_versions` table fingerprints each
registered prompt by `(prompt_name, version)`. Two consumers sharing a
fragment is fine because every consumer registers its own
fully-rendered system prompt and version; the fragment is just a way
to keep the wording aligned across them. The D24 forbidden-source list
is the only fragment that has drifted across consumers in the past
(the Verifier and Adjudicator carried a shorter list than the
Researcher), and unifying it here is the point.
"""

from __future__ import annotations


# D24 forbidden-source list, the canonical comprehensive version. Used
# by the Researcher, Verifier and Adjudicator system prompts to state
# which URLs are off-limits because they are the ground truth we are
# validating against. The deny-list in
# `agents/tools/blocked_domains.py` is the deterministic enforcement
# layer; this is the prompt-level statement of the same rule, kept in
# sync so every agent reasons against the same list.
FORBIDDEN_SOURCES_BULLETS = (
    "- data.europa.eu (and any subdomain)\n"
    "- publications.europa.eu, op.europa.eu\n"
    "- europeandataportal.eu (legacy redirect)\n"
    "- web.archive.org, archive.today and similar mirror caches\n"
    "- any page whose URL contains \"open-data-maturity\", \"odmi\", "
    "\"merged_responses\", or \"odm-questionnaire\""
)
