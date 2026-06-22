#!/usr/bin/env python3
"""Phase 0, counter-evidence independence (LLM-free).

Proxy for the chaining-entropy question: if the Verifier's counter-evidence just
re-cites what the Researcher already read, it carries no new entropy, so retry
chaining's gains cannot come from it; they come from the Researcher's divergent
re-searches (D33). For every Verifier run that produced a counter_source_url,
compare it to the Researcher run it judged: same exact URL, or same host, or the
URL already in the Researcher's fetched_urls.

(The precise per-recovery origin split needs the EvidenceItem origins persisted
on the chained run, which they are not; that is a small instrumentation, logged
here as owed. This independence measure is the recoverable proxy.)
"""
import sqlite3
from urllib.parse import urlparse

def host(u):
    try: return (urlparse(u).hostname or "").lower().lstrip("www.")
    except Exception: return ""

c = sqlite3.connect("data/odmi.db").cursor()
rows = c.execute("""
  SELECT v.counter_source_url, r.source_url, r.fetched_urls
  FROM phase2_verifier_runs v
  JOIN phase2_researcher_runs r ON r.id = v.researcher_run_id
  WHERE v.counter_source_url IS NOT NULL AND trim(v.counter_source_url) <> ''
    AND lower(trim(v.counter_source_url)) NOT IN ('(none)','none','null')
""").fetchall()

n=same_url=same_host=in_fetched=0
for cu, rsu, fetched in rows:
    n+=1
    cu_s=(cu or "").strip(); rsu_s=(rsu or "").strip()
    if cu_s and cu_s==rsu_s: same_url+=1
    if host(cu_s) and host(cu_s)==host(rsu_s): same_host+=1
    if cu_s and fetched and cu_s in fetched: in_fetched+=1

print(f"Verifier counter-evidence with a URL: n={n}")
if n:
    print(f"  same exact URL as Researcher's source : {same_url:>4} ({100*same_url/n:.0f}%)")
    print(f"  same host as Researcher's source      : {same_host:>4} ({100*same_host/n:.0f}%)")
    print(f"  URL already in Researcher's fetched set: {in_fetched:>4} ({100*in_fetched/n:.0f}%)")
    redundant = sum(1 for cu,rsu,f in rows if (cu and ((cu.strip()==(rsu or '').strip()) or (f and cu.strip() in f))))
    print(f"  redundant (exact source OR in fetched) : {redundant:>4} ({100*redundant/n:.0f}%)")
    print("\nReading: the higher these are, the less independent entropy the Verifier's")
    print("counter-search adds, supporting carrying the Researcher corpus (not the")
    print("verifier counter-quote) across retries (EXP-7 recommendation).")
