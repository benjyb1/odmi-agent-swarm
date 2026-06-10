"""Read-only trail dumper for failure-mode analysis. No writes."""
import sqlite3, json, sys, textwrap

db = sqlite3.connect("data/odmi.db")
db.row_factory = sqlite3.Row

def j(s):
    if not s: return []
    try: return json.loads(s)
    except Exception: return [s]

def cached(url):
    if not url: return None
    r = db.execute("SELECT status_code, backend, length(content) AS n, content FROM search_cache_fetch WHERE url=?", (url,)).fetchone()
    return r

def dump(pid):
    f = db.execute("SELECT * FROM phase2_final WHERE pair_run_id=?", (pid,)).fetchone()
    q = db.execute("SELECT * FROM questions WHERE question_id=?", (f["question_id"],)).fetchone()
    gt = db.execute("SELECT * FROM ground_truth WHERE question_id=? AND country_code=? AND cycle_year=2025", (f["question_id"], f["country_code"])).fetchone()
    print("="*90)
    print(f"PAIR {pid}  {f['question_id']} / {f['country_code']}  [{q['dimension']}/{q['answer_shape']}]")
    print(f"QTEXT: {q['question_text'][:300]}")
    print(f"ALLOWED: {q['allowed_answers']}")
    print(f"FINAL: answer={f['final_answer']!r} term={f['terminal_status']} rt={f['retry_count']} adj={f['adjudicator_involved']}")
    print(f"FINAL_EXPL: {(f['final_answer_explanation'] or '')[:400]}")
    print(f"FINAL_EVID: {(f['final_evidence_quote'] or '')[:300]}")
    print(f"FINAL_URL: {f['final_source_url']}")
    print(f"ODMI: {gt['response']!r}  score={gt['awarded_score']}/{gt['max_score']}")
    print(f"ODMI_EXPL: {(gt['explanation'] or '')[:500]}")
    print("-"*90)
    for r in db.execute("SELECT * FROM phase2_researcher_runs WHERE pair_run_id=? ORDER BY retry_count, id", (pid,)):
        print(f"  RESEARCHER rt={r['retry_count']}: answer={r['answer']!r} retr_conf={r['retrieval_confidence']} ans_conf={r['answer_confidence']} fmode={r['failure_mode']}")
        print(f"    queries: {j(r['search_queries_used'])}")
        fu = j(r["fetched_urls"])
        print(f"    fetched_urls ({len(fu)}):")
        for u in fu:
            c = cached(u)
            tag = f"[cache {c['status_code']} {c['backend']} {c['n']}b]" if c else "[NOT CACHED]"
            print(f"       {tag} {u}")
        print(f"    evidence: {(r['evidence_quote'] or '')[:200]}")
        print(f"    expl: {(r['answer_explanation'] or '')[:300]}")
        print(f"    notes: {(r['notes'] or '')[:200]}")
    print("-"*90)
    for v in db.execute("SELECT * FROM phase2_verifier_runs WHERE pair_run_id=? ORDER BY retry_count, id", (pid,)):
        print(f"  VERIFIER rt={v['retry_count']} strat={v['strategy_label']}: verdict={v['verdict']} subcheck={v['substring_check_result']} conf={v['verifier_confidence']}")
        print(f"    reject: {(v['rejection_reason'] or '')[:300]}")
        print(f"    counter_evid: {(v['counter_evidence_quote'] or '')[:200]}  url={v['counter_source_url']}")
        print(f"    suggested_q: {v['suggested_search_query']}")
        print(f"    indep_queries: {j(v['independent_search_queries'])}")
    print("-"*90)
    for a in db.execute("SELECT * FROM phase2_adjudications WHERE pair_run_id=? ORDER BY id", (pid,)):
        print(f"  ADJUDICATOR: verdict={a['adjudicator_verdict']} answer={a['adjudicator_answer']!r} conf={a['adjudicator_confidence']}")
        print(f"    reasoning: {(a['adjudicator_reasoning'] or '')[:500]}")
        print(f"    chosen_url: {a['chosen_source_url']}")
        print(f"    chosen_evid: {(a['chosen_evidence_quote'] or '')[:200]}")

for pid in sys.argv[1:]:
    dump(pid)
