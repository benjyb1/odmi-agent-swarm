"""Diagnostic: where does the DIY snippet pipeline lose the evidence quote?

For each snippet_quality fixture, fetch the RAW page (no tag-strip, no cap) and
measure whether the historically-accepted evidence_quote (normalised) is present
at each pipeline boundary:

  raw_plain[:4000]   -- what the CURRENT pipeline feeds the picker (fetch.py cap)
  raw_plain[:8000]   -- the picker's own PAGE_TEXT_CAP
  raw_plain[:16000]  -- a larger cap
  raw_plain (full)   -- whole page, tag-stripped (findability ceiling, no extract)
  trafilatura(raw)   -- proper main-content extraction on RAW html

No Claude calls. Pure network + string checks, so it is cheap to re-run.
Documents the extraction-ceiling finding behind the D29 fetch/extract
reorder: with the old 4000-char tag-stripped cap the evidence quote was
present in only ~38% of inputs; running trafilatura on the raw HTML lifts
that ceiling to ~78%.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import trafilatura

from agents.tools.substring import normalise, contains
from agents.tools.fetch import DEFAULT_USER_AGENT

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "snippet_quality.jsonl"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def raw_plain(html: str) -> str:
    """Replicate fetch._html_to_text WITHOUT the cap (tags->space, collapse ws)."""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()


def probe(fix: dict) -> dict:
    url = fix["source_url"]
    quote = fix["evidence_quote"]
    out = {"q": fix["question_id"], "cc": fix["country_code"], "url": url}
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True,
                          headers={"User-Agent": DEFAULT_USER_AGENT}) as c:
            r = c.get(url)
        out["status"] = r.status_code
        if r.status_code != 200:
            out["err"] = f"http_{r.status_code}"
            return out
        html = r.text
    except Exception as exc:  # noqa: BLE001
        out["err"] = f"{type(exc).__name__}"
        return out

    plain = raw_plain(html)
    traf = trafilatura.extract(html, favor_recall=True, include_comments=False,
                               include_tables=True, url=url) or ""
    out["raw_html_len"] = len(html)
    out["plain_len"] = len(plain)
    out["traf_len"] = len(traf)
    out["in_4000"] = contains(plain[:4000], quote)
    out["in_8000"] = contains(plain[:8000], quote)
    out["in_16000"] = contains(plain[:16000], quote)
    out["in_full"] = contains(plain, quote)
    out["in_traf"] = contains(traf, quote)
    out["in_traf16k"] = contains(traf[:16000], quote)
    # where does the quote first appear in normalised full plain? (approx offset)
    nq = normalise(quote)
    np_ = normalise(plain)
    out["offset"] = np_.find(nq[:40]) if len(nq) >= 40 else np_.find(nq)
    return out


def main() -> None:
    fixtures = [json.loads(l) for l in FIXTURE.read_text(encoding="utf-8").splitlines() if l.strip()]
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(probe, fixtures))

    hdr = f"{'q/cc':<9} {'stat':>4} {'rawlen':>7} {'plain':>7} {'traf':>6} {'4k':>3} {'8k':>3} {'16k':>4} {'full':>5} {'traf':>5} {'offset':>7}"
    print(hdr)
    print("-" * len(hdr))
    agg = {k: 0 for k in ["ok", "in_4000", "in_8000", "in_16000", "in_full", "in_traf", "in_traf16k"]}
    for o in rows:
        tag = f"{o['q']}/{o['cc']}"
        if o.get("err"):
            print(f"{tag:<9} {o.get('status','-'):>4}  ERR {o['err']}")
            continue
        agg["ok"] += 1
        for k in ["in_4000", "in_8000", "in_16000", "in_full", "in_traf", "in_traf16k"]:
            agg[k] += 1 if o[k] else 0
        b = lambda x: "Y" if x else "."
        print(f"{tag:<9} {o['status']:>4} {o['raw_html_len']:>7} {o['plain_len']:>7} "
              f"{o['traf_len']:>6} {b(o['in_4000']):>3} {b(o['in_8000']):>3} "
              f"{b(o['in_16000']):>4} {b(o['in_full']):>5} {b(o['in_traf']):>5} {o['offset']:>7}")

    n = agg["ok"]
    print("\n=== AGGREGATE (of", n, "successfully fetched) ===")
    print(f"  quote present in current 4000-char input : {agg['in_4000']:>3}/{n}  ({agg['in_4000']/n:.0%})  <- CURRENT CEILING")
    print(f"  quote present in 8000-char input          : {agg['in_8000']:>3}/{n}  ({agg['in_8000']/n:.0%})")
    print(f"  quote present in 16000-char input         : {agg['in_16000']:>3}/{n}  ({agg['in_16000']/n:.0%})")
    print(f"  quote present in full tag-stripped page   : {agg['in_full']:>3}/{n}  ({agg['in_full']/n:.0%})  <- findability ceiling (no extract)")
    print(f"  quote present in trafilatura(raw html)    : {agg['in_traf']:>3}/{n}  ({agg['in_traf']/n:.0%})  <- with proper extraction")
    print(f"  quote present in trafilatura[:16000]      : {agg['in_traf16k']:>3}/{n}  ({agg['in_traf16k']/n:.0%})  <- extraction + sane cap")


if __name__ == "__main__":
    main()
