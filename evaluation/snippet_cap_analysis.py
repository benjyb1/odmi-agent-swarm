"""Snippet-cap effect analysis (read-only diagnostic).

EXP-24 Phase A. Measures the effect of the 600-char snippet cap in
`agents/tools/search.py:format_for_prompt` without running the swarm, purely
from rows already stored in `data/odmi.db`.

A0. Dataset shape sanity-check.
A1. Where does the cited `evidence_quote` sit WITHIN its own snippet? Histogram
    of start positions. The Researcher only saw the first 600 chars, so a quote
    must locate at position 0..600 of one of the snippets in its row; clustering
    near 500-600 means the cap is biting on committed pairs.
A2. For abstained binary pairs that have at least one snippet > 1500 chars,
    does question-relevant content sit past position 600 in that same snippet?
    Heuristic: two or more distinct content keywords within a 200-char window.
A3. Cost projection. From stored input_tokens, project per-cap chars shown to
    the LLM and the extra input tokens at caps [600, 1000, 1500, 2500, 4000, 8000].

Strictly read-only. Joins to ground_truth and questions only for keyword and
dimension labels; no expert answer is written to any pipeline-facing table
(D24 firewall).

Run:  uv run python evaluation/snippet_cap_analysis.py
      uv run python evaluation/snippet_cap_analysis.py --db /path/to/odmi.db
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "odmi.db"

# format_for_prompt's default cap, the variable under test.
PRODUCTION_CAP = 600

# Cap candidates for the cost projection.
PROJECTION_CAPS = (600, 1000, 1500, 2500, 4000, 8000)

# A2 trigger: an individual snippet must exceed this length for content to fit
# past the 600 cap PLUS the 200-char cluster window (so >= 800).
A2_MIN_SNIPPET_CHARS = 800

# A2 windowing: a "content cluster" is K distinct content keywords inside a W-char window.
A2_KEYWORD_WINDOW = 200
A2_MIN_DISTINCT_KEYWORDS = 2

# Chars-per-token approximation for Claude. Used for the projection only; the
# real tokeniser would be more accurate but the relative deltas are what matter.
CHARS_PER_TOKEN = 4.0

# Country code -> human name; pulled from run_coordinator.COUNTRIES, hardcoded
# here to keep this script free of swarm imports.
COUNTRY_NAMES = {
    "FR": "France", "RO": "Romania", "DE": "Germany", "NL": "Netherlands",
    "HU": "Hungary", "EE": "Estonia", "MT": "Malta", "NO": "Norway",
    "SK": "Slovakia", "SI": "Slovenia", "SE": "Sweden", "AL": "Albania",
    "BA": "Bosnia and Herzegovina", "MK": "North Macedonia", "ME": "Montenegro",
    "BG": "Bulgaria", "FI": "Finland", "HR": "Croatia", "BE": "Belgium",
    "AT": "Austria", "CZ": "Czechia", "CY": "Cyprus", "DK": "Denmark",
    "ES": "Spain", "GR": "Greece", "IE": "Ireland", "IT": "Italy",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "PL": "Poland",
    "PT": "Portugal", "CH": "Switzerland", "IS": "Iceland", "LI": "Liechtenstein",
    "UA": "Ukraine",
}

# Generic English stopwords plus ODMI-question filler that would otherwise match
# tangentially. Excluding these is what makes the A2 cluster check meaningful.
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "did",
    "of", "to", "in", "on", "for", "by", "with", "at", "as", "from",
    "this", "that", "these", "those", "and", "or", "if", "then", "than",
    "be", "been", "being", "have", "has", "had", "not", "no", "yes",
    "you", "your", "our", "we", "us", "they", "them", "their", "its", "it",
    "there", "what", "which", "when", "where", "how", "why", "whether",
    "please", "describe", "explain", "explanation", "example", "examples",
    "any", "all", "some", "most", "many", "each", "every", "other", "also",
    "such", "country", "portal", "data", "national", "open", "approach",
    "process", "provide", "would", "could", "should", "may", "might",
}


def rule(s: str) -> None:
    print(f"\n{'=' * 4} {s} {'=' * 4}")


def normalise(s: str) -> str:
    """Lowercase + collapse whitespace. Used for substring search."""
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def keywords_for(question_text: str, country_name: str) -> list[str]:
    """Content keywords from the question and country name."""
    txt = f"{question_text or ''} {country_name or ''}"
    raw = re.findall(r"[A-Za-zÀ-ſ][A-Za-zÀ-ſ\-]{3,}", txt.lower())
    return [w for w in raw if w not in STOPWORDS]


def find_quote_in_snippets(quote: str, search_snippets: str) -> tuple[int, int] | None:
    """Locate the cited quote inside one of the stored snippet objects.

    Returns (snippet_index, start_pos_within_snippet) or None.
    Match is whitespace-normalised, case-insensitive.
    """
    if not quote or not search_snippets:
        return None
    norm_quote = normalise(quote)
    if len(norm_quote) < 10:
        return None
    try:
        snips = json.loads(search_snippets)
    except (ValueError, TypeError):
        return None
    if not isinstance(snips, list):
        return None
    for i, s in enumerate(snips):
        body = s.get("snippet") if isinstance(s, dict) else None
        if not body:
            continue
        pos = normalise(body).find(norm_quote)
        if pos >= 0:
            return (i, pos)
    return None


def first_keyword_cluster_pos(snippet: str, keywords: list[str]) -> int | None:
    """First position of a >=K-distinct-keyword cluster within W chars.

    Returns the start of the window, or None when no cluster is found.
    """
    if not snippet:
        return None
    text = normalise(snippet)
    hits: list[tuple[int, str]] = []
    for kw in set(keywords):
        if len(kw) < 4:
            continue
        for m in re.finditer(re.escape(kw), text):
            hits.append((m.start(), kw))
    if len(hits) < A2_MIN_DISTINCT_KEYWORDS:
        return None
    hits.sort()
    for i, (start_i, _) in enumerate(hits):
        distinct: set[str] = set()
        for j in range(i, len(hits)):
            start_j, kw_j = hits[j]
            if start_j - start_i > A2_KEYWORD_WINDOW:
                break
            distinct.add(kw_j)
            if len(distinct) >= A2_MIN_DISTINCT_KEYWORDS:
                return start_i
    return None


def pct(num: int, den: int) -> str:
    return f"{100.0 * num / max(1, den):.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help="path to odmi.db (default: repo data/odmi.db)")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # A0: dataset shape
    rule("A0. dataset shape (sanity)")
    shape = cur.execute(
        "SELECT COUNT(*) total, "
        "SUM(search_snippets IS NOT NULL AND search_snippets <> '[]') with_snippets, "
        "SUM(LENGTH(search_snippets) > 600) blob_over_600, "
        "SUM(LENGTH(search_snippets) > 1500) blob_over_1500, "
        "SUM(LENGTH(search_snippets) > 5000) blob_over_5000 "
        "FROM phase2_researcher_runs"
    ).fetchone()
    for k in shape.keys():
        print(f"  {k}: {shape[k]}")

    # A1: cited-quote position within its own snippet
    rule("A1. cited evidence_quote position within its own snippet")
    print("# The Researcher only saw the first 600 chars of each snippet, so a")
    print("# quote that ends up cited must locate at 0..600 in some snippet of its row.")
    print("# Clustering near 500-600 means the cap is biting on committed pairs.")
    rows = cur.execute(
        "SELECT evidence_quote, search_snippets "
        "FROM phase2_researcher_runs "
        "WHERE evidence_quote IS NOT NULL AND LENGTH(evidence_quote) >= 20 "
        "  AND search_snippets IS NOT NULL AND search_snippets <> '[]'"
    ).fetchall()
    bands: Counter[str] = Counter()
    snippet_idx_counter: Counter[int] = Counter()
    not_found = 0
    for r in rows:
        hit = find_quote_in_snippets(r["evidence_quote"], r["search_snippets"])
        if hit is None:
            not_found += 1
            continue
        idx, pos = hit
        snippet_idx_counter[idx] += 1
        if pos < 100:
            bands["a 0-100"] += 1
        elif pos < 300:
            bands["b 100-300"] += 1
        elif pos < 500:
            bands["c 300-500"] += 1
        elif pos < 600:
            bands["d 500-600 (cap-adjacent)"] += 1
        else:
            bands["e past 600 (data anomaly)"] += 1
    located = len(rows) - not_found
    print(f"  rows scanned: {len(rows)}")
    print(f"  quote located in some snippet: {located} ({pct(located, len(rows))})")
    print(f"  quote not located (paraphrased / substring-broken): {not_found} "
          f"({pct(not_found, len(rows))})")
    print("  position-in-snippet distribution (of located):")
    for k in sorted(bands):
        print(f"    {k}: {bands[k]} ({pct(bands[k], located)})")
    print("  which-snippet-index was cited (idx 0 = first SERP result):")
    total_idx = sum(snippet_idx_counter.values())
    for idx, n in sorted(snippet_idx_counter.items())[:10]:
        print(f"    snippet[{idx}]: {n} ({pct(n, total_idx)})")

    # A2: hidden-answer scan on abstained binary pairs
    rule(f"A2. abstained pairs: relevant content past 600 in same snippet "
         f"(min snippet {A2_MIN_SNIPPET_CHARS}c, "
         f"cluster {A2_MIN_DISTINCT_KEYWORDS}kw/{A2_KEYWORD_WINDOW}c)")
    abst = cur.execute(
        "SELECT DISTINCT f.question_id, f.country_code "
        "FROM phase2_final f "
        "WHERE f.final_answer='inconclusive' OR f.terminal_status='agent_failure'"
    ).fetchall()
    print(f"  distinct abstained pairs: {len(abst)}")

    qtext = {r["question_id"]: r["question_text"] for r in cur.execute(
        "SELECT question_id, COALESCE(question_text,'') AS question_text FROM questions"
    ).fetchall()}

    n_with_long = 0
    n_hidden_any = 0
    examples: list[tuple[str, str, int, str]] = []
    by_country: Counter[str] = Counter()
    by_country_long: Counter[str] = Counter()
    for ab in abst:
        # Scan EVERY retry for this pair: earlier retries often hold the
        # richest snippets, while the final retry can be a thin reformulation.
        rrows = cur.execute(
            "SELECT search_snippets FROM phase2_researcher_runs "
            "WHERE question_id=? AND country_code=? "
            "  AND search_snippets IS NOT NULL AND search_snippets <> '[]'",
            (ab["question_id"], ab["country_code"]),
        ).fetchall()
        if not rrows:
            continue
        long_snips: list[str] = []
        for rr in rrows:
            try:
                snips = json.loads(rr["search_snippets"])
            except (ValueError, TypeError):
                continue
            if not isinstance(snips, list):
                continue
            for s in snips:
                if (isinstance(s, dict)
                        and len(s.get("snippet", "")) > A2_MIN_SNIPPET_CHARS):
                    long_snips.append(s["snippet"])
        if not long_snips:
            continue
        n_with_long += 1
        by_country_long[ab["country_code"]] += 1

        kws = keywords_for(qtext.get(ab["question_id"], ""),
                           COUNTRY_NAMES.get(ab["country_code"], ""))
        if not kws:
            continue
        hidden_here = False
        for body in long_snips:
            pos = first_keyword_cluster_pos(body, kws)
            if pos is None:
                continue
            if pos > PRODUCTION_CAP:
                hidden_here = True
                if len(examples) < 10:
                    examples.append(
                        (ab["question_id"], ab["country_code"], pos,
                         body[pos:pos + 160].replace("\n", " "))
                    )
                break
        if hidden_here:
            n_hidden_any += 1
            by_country[ab["country_code"]] += 1

    print(f"  abstained pairs with a snippet > {A2_MIN_SNIPPET_CHARS}c: {n_with_long} "
          f"({pct(n_with_long, len(abst))} of abstentions)")
    print(f"  of those, pairs with a relevant cluster past 600 in the same snippet: "
          f"{n_hidden_any} ({pct(n_hidden_any, n_with_long)})")
    print("  per-country hidden-rate (among long-snippet abstentions):")
    for cc in sorted(by_country_long):
        long_n = by_country_long[cc]
        hid_n = by_country[cc]
        print(f"    {cc}: {hid_n}/{long_n} ({pct(hid_n, long_n)})")
    print("  sample hidden clusters (snippet substring starting at the cluster):")
    for q, cc, pos, snip in examples:
        print(f"    {q}/{cc} pos={pos}: {snip[:140]}...")

    # A3: cost projection
    rule("A3. cost projection per cap (extra input tokens vs current 600 cap)")
    cap_chars = {c: 0 for c in PROJECTION_CAPS}
    cap_rows = {c: 0 for c in PROJECTION_CAPS}
    base_in: list[int] = []
    base_secs: list[float] = []
    for r in cur.execute(
        "SELECT search_snippets, input_tokens, wall_clock_ms "
        "FROM phase2_researcher_runs "
        "WHERE search_snippets IS NOT NULL AND input_tokens IS NOT NULL"
    ):
        try:
            snips = json.loads(r["search_snippets"])
        except (ValueError, TypeError):
            continue
        if not isinstance(snips, list):
            continue
        if r["input_tokens"]:
            base_in.append(r["input_tokens"])
        if r["wall_clock_ms"]:
            base_secs.append(r["wall_clock_ms"] / 1000.0)
        bodies = [s.get("snippet", "") for s in snips if isinstance(s, dict)]
        for cap in PROJECTION_CAPS:
            cap_chars[cap] += sum(min(len(b), cap) for b in bodies)
            cap_rows[cap] += 1
    print(f"  rows used: {len(base_in)}")
    if not base_in:
        print("  (no usable rows)")
        return 0
    base_avg_in = sum(base_in) / len(base_in)
    base_avg_secs = (sum(base_secs) / len(base_secs)) if base_secs else 0.0
    print(f"  baseline Researcher input_tokens (mean): {base_avg_in:.0f}")
    print(f"  baseline Researcher wall-clock (mean):   {base_avg_secs:.1f}s")
    print()
    base_chars = cap_chars[PRODUCTION_CAP] / max(1, cap_rows[PRODUCTION_CAP])
    print(f"  {'cap':>5}  {'avg_chars_shown':>15}  "
          f"{'extra_chars_vs_600':>18}  {'extra_tokens':>12}  "
          f"{'extra_%_of_input':>16}")
    for cap in PROJECTION_CAPS:
        avg = cap_chars[cap] / max(1, cap_rows[cap])
        extra_chars = avg - base_chars
        extra_tokens = extra_chars / CHARS_PER_TOKEN
        pct_extra = 100.0 * extra_tokens / base_avg_in
        marker = "  <-- baseline" if cap == PRODUCTION_CAP else ""
        print(f"  {cap:>5}  {avg:>14.0f}c  "
              f"{extra_chars:>+17.0f}c  {extra_tokens:>+11.0f}t  "
              f"{pct_extra:>+15.1f}%{marker}")

    conn.close()
    print("\n(read-only; no DB writes, no pipeline contact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
