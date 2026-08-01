"""Expert evidence-gap analysis (read-only diagnostic).

Reproduces the tables in docs/EXPERT_EVIDENCE_GAP.md from data/odmi.db so the
document's numbers replay deterministically (the repo's reproducibility
standard). Answers: for the (question, country) pairs the swarm abstains on,
how did the ODMI assessors answer, and where did their evidence sit?

Strictly read-only. Joins to ground_truth.explanation only to characterise the
assessor's evidence channel. Per D24 this is diagnostic: nothing here is written
to any table the swarm reads, and no expert answer or source leaves this script.

Run:  uv run python evaluation/expert_evidence_gap.py
      uv run python evaluation/expert_evidence_gap.py --db /path/to/odmi.db
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "odmi.db"

# National portal hosts, mirrored from run_coordinator.COUNTRIES portal_base.
# Hardcoded rather than imported to keep this script import-side-effect free and
# to make the classification transparent and auditable. Only the countries that
# appear in the abstained set need an entry; anything else falls to "other".
PORTAL_HOSTS = {
    "FR": "data.gouv.fr",
    "NL": "data.overheid.nl",
    "NO": "data.norge.no",
    "MT": "data.gov.mt",
    "EE": "avaandmed.eesti.ee",
    "FI": "avoindata.fi",
    "SE": "dataportal.se",
    "HR": "data.gov.hr",
    "AL": "opendata.gov.al",
}

# Yes-tier assessor responses (any positive commitment, including tiered yes).
YES_PREFIXES = ("yes",)

URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)

SOCIAL_HOSTS = ("linkedin.", "twitter.", "x.com", "facebook.", "instagram.")
FORM_HOSTS = ("docs.google.com", "forms.gle", "tally.so", "forms.office.com")
CODE_HOSTS = ("github.com", "gitlab.com", "bitbucket.")
# National-language legislation / government markers (deep gov sources).
GOVDOC_MARKERS = (
    "legifrance", "legislation.", "narodne-novine", "regjeringen",
    "gazette", "/eli/", "ministervan", "wetten.overheid", "lovdata",
)


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except ValueError:
        return ""


def is_portal_deeplink(url: str, country: str) -> bool:
    """True when the URL sits on the country's national portal below its root."""
    portal = PORTAL_HOSTS.get(country)
    if not portal:
        return False
    h = host_of(url)
    if portal not in h:
        return False
    path = urlparse(url).path.strip("/")
    return bool(path)  # a path beyond the front page = a deep-link


def classify_url(url: str, country: str) -> str:
    h = host_of(url)
    if any(m in h for m in SOCIAL_HOSTS):
        return "social_media"
    if any(m in url.lower() for m in FORM_HOSTS) or any(m in h for m in FORM_HOSTS):
        return "google_doc_or_form"
    if any(m in h for m in CODE_HOSTS):
        return "code_repository"
    if is_portal_deeplink(url, country):
        return "national_portal_deeplink"
    if any(m in url.lower() for m in GOVDOC_MARKERS):
        return "government_doc"
    return "other_web_domain"


def rule(title: str) -> None:
    print(f"\n{'=' * 4} {title} {'=' * 4}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help="path to odmi.db (default: repo data/odmi.db)")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ground_truth.explanation coverage
    rule("ground_truth coverage")
    gt = cur.execute(
        "SELECT COUNT(*) total, "
        "SUM(explanation IS NOT NULL AND TRIM(explanation) <> '') populated "
        "FROM ground_truth"
    ).fetchone()
    print(f"ground_truth rows: {gt['total']}")
    print(f"explanation populated: {gt['populated']} "
          f"({100.0 * gt['populated'] / gt['total']:.1f}%)")

    # non-committed population (row level)
    rule("non-committed population (phase2_final rows)")
    pop = cur.execute(
        "SELECT COUNT(*) total, "
        "SUM(final_answer='inconclusive') inconclusive, "
        "SUM(terminal_status='agent_failure') failure, "
        "SUM(terminal_status='agent_failure' AND final_answer='inconclusive') overlap "
        "FROM phase2_final"
    ).fetchone()
    noncommit_rows = pop["inconclusive"] + pop["failure"] - pop["overlap"]
    print(f"finalised rows:        {pop['total']}")
    print(f"inconclusive:          {pop['inconclusive']}")
    print(f"agent_failure:         {pop['failure']}")
    print(f"both (overlap):        {pop['overlap']}")
    print(f"non-committed (union): {noncommit_rows}")

    # distinct abstained pairs by country
    rule("distinct abstained pairs by country")
    abstained = cur.execute(
        "SELECT DISTINCT question_id, country_code FROM phase2_final "
        "WHERE final_answer='inconclusive' OR terminal_status='agent_failure'"
    ).fetchall()
    by_country = Counter(r["country_code"] for r in abstained)
    for cc, n in by_country.most_common():
        print(f"  {cc}: {n}")
    print(f"  total distinct abstained pairs: {len(abstained)}")

    # non-commit by ODMI dimension (row level)
    rule("non-commit by ODMI dimension (rows)")
    dims = cur.execute(
        "SELECT g.dimension, COUNT(*) rows_, "
        "SUM(f.final_answer='inconclusive') abstain, "
        "SUM(f.terminal_status='agent_failure') fail, "
        "SUM(f.final_answer='inconclusive' OR f.terminal_status='agent_failure') noncommit "
        "FROM phase2_final f "
        "JOIN ground_truth g ON g.question_id=f.question_id "
        "AND g.country_code=f.country_code "
        "GROUP BY g.dimension ORDER BY noncommit DESC"
    ).fetchall()
    print(f"{'dimension':20} {'rows':>5} {'abst':>5} {'fail':>5} {'ncom':>5} {'%':>6}")
    for d in dims:
        pct = 100.0 * d["noncommit"] / d["rows_"]
        print(f"{d['dimension']:20} {d['rows_']:>5} {d['abstain']:>5} "
              f"{d['fail']:>5} {d['noncommit']:>5} {pct:>5.1f}%")

    # assessor answer for the distinct abstained pairs
    rule("assessor answer for abstained pairs (distinct)")
    abstain_keys = {(r["question_id"], r["country_code"]) for r in abstained}
    gt_rows = cur.execute(
        "SELECT question_id, country_code, response, explanation FROM ground_truth"
    ).fetchall()
    gt_by_key = {(r["question_id"], r["country_code"]): r for r in gt_rows}

    buckets = Counter()
    yes_pairs = []          # (key, explanation) for yes-tier pairs
    no_no_justification = 0
    for key in abstain_keys:
        g = gt_by_key.get(key)
        resp = (g["response"] if g and g["response"] else "").strip().lower()
        expl = (g["explanation"] if g and g["explanation"] else "").strip()
        if resp.startswith(YES_PREFIXES):
            buckets["yes (any tier)"] += 1
            yes_pairs.append((key, expl))
        elif resp == "no":
            buckets["no"] += 1
            if len(expl) < 15:  # no substantive justification
                no_no_justification += 1
        elif resp == "i don't know":
            buckets["i don't know"] += 1
        else:
            buckets["percentage band / other"] += 1
    for label, n in buckets.most_common():
        print(f"  {label}: {n}")
    print(f"  (of the 'no' pairs, {no_no_justification} carry no substantive "
          f"justification)")

    # source-type classification of the yes-tier explanations
    rule("source-type of assessor yes-tier explanations (heuristic)")
    src_counts = Counter()
    domain_counter = Counter()
    yes_with_expl = 0
    yes_prose_only = 0
    for (qid, cc), expl in yes_pairs:
        if not expl:
            continue
        yes_with_expl += 1
        urls = URL_RE.findall(expl)
        if not urls:
            yes_prose_only += 1
            src_counts["prose_only_no_url"] += 1
            continue
        for u in urls:
            src_counts[classify_url(u, cc)] += 1
            h = host_of(u)
            if h:
                domain_counter[h] += 1
    print(f"yes-tier pairs with an explanation: {yes_with_expl} "
          f"(of {len(yes_pairs)} yes-tier abstained pairs)")
    print(f"prose-only (no URL anywhere):       {yes_prose_only}")
    print("URL classification (counts are URLs, a pair may cite several):")
    for label, n in src_counts.most_common():
        print(f"  {label}: {n}")

    rule("recurring domains in abstained yes-tier explanations")
    for dom, n in domain_counter.most_common(15):
        print(f"  {dom}: {n}")

    # findable vs structural
    rule("findable vs structural (yes-tier abstained pairs)")
    cites_url = sum(1 for (_k, e) in yes_pairs if e and URL_RE.search(e))
    prose_only = sum(1 for (_k, e) in yes_pairs if not e or not URL_RE.search(e))
    idk_count = buckets["i don't know"]
    print(f"cites >= 1 public URL (findable-but-missed): {cites_url}")
    print(f"prose-only / bare yes (structural):          {prose_only}")
    print(f"plus unjustified 'no' (structural):          {no_no_justification}")
    print(f"plus 'i don't know' (structural):            {idk_count}")

    conn.close()
    print("\n(read-only; no DB writes, no pipeline contact)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
