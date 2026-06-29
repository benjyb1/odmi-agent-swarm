"""Build evaluation/failure_modes.csv from per-pair classifications. Read-only on DB."""
import sqlite3, json, csv
db=sqlite3.connect("data/odmi.db"); db.row_factory=sqlite3.Row

# (primary, contributing, runner_up, confidence, evidence_note)
# Keyed by pair_run_id. addressed_by derived from primary mode below.
C = {
 # --- N2 adjudication_propagation_loss (adjudicator computed ODMI-correct answer, final recorded inconclusive) ---
 "2ddae530-d7e5-49d9-bd64-13dbb9f2b448":("adjudication_propagation_loss","verifier_substring_gate_collapse","evidence_absent_or_self_report","high",
   "Adjudicator verdict=verifier_correct, adjudicator_answer='yes' (matches ODMI), but final_answer='inconclusive'. Researcher rt1 also answered 'yes'. run_coordinator.py:979-990 synthesises final from verifier output, discarding adjudicator_answer. All 4 verifier rounds substring_check=fail; EE gov PDFs 403."),
 "809531c0-019e-41cb-9f27-3dc1c1a05c70":("adjudication_propagation_loss","verifier_substring_gate_collapse","evidence_absent_or_self_report","high",
   "Adjudicator verdict=verifier_correct, adjudicator_answer='yes'; final='inconclusive'. Researcher rt2='yes'. Same coordinator path drops adjudicator_answer. 4/4 substring fail."),
 "2cf1cd42-2fd3-48d4-8f59-0e6234927417":("adjudication_propagation_loss","verifier_substring_gate_collapse","zero_weight_descriptive","high",
   "P26-b: adjudicator verdict=verifier_correct, adjudicator_answer='yes'; final='inconclusive'. Researcher rt0,rt1='yes'. ODMI is a long FR self-report (data-literacy/DINUM). Zero score weight. 3/3 substring fail, 403."),
 "bdbcdb72-5511-4249-ae78-08f28168dc9f":("adjudication_propagation_loss","verifier_substring_gate_collapse","inconclusive_collapse","high",
   "PT14: adjudicator verdict=researcher_correct, adjudicator_answer='yes'; final='inconclusive'. Researcher rt0-2='yes' then rt3='inconclusive'; coordinator took researcher_outputs[-1] (the inconclusive), not the adjudged 'yes'. ODMI: requests tracked on forum.data.gouv.fr (public)."),

 # --- N1 verifier_substring_gate_collapse (researcher found ODMI-correct answer, verbatim substring gate rejected it -> reverted to inconclusive/no) ---
 "3d4ce613-d4f4-42fb-b587-0dffba39302c":("verifier_substring_gate_collapse","selection_or_interpretation_miss","ground_truth_contested","high",
   "I11: researcher rt0='yes' then rt1='no' after verifier substring_check=fail. ODMI: 4300+ reuse cases classified by public taxonomy at data.gouv.fr/fr/reuses/ (verifier's own counter-evidence cited that exact page). Correct evidence reachable; killed on verbatim match."),
 "347150a5-0014-457f-88a5-34cf00d6bfe5":("verifier_substring_gate_collapse","evidence_absent_or_self_report","inconclusive_collapse","medium",
   "I5: researcher rt0='yes' then rt1='inconclusive'; 1/2 substring fail. ODMI is a 4286-char self-report (Bothorel report). Found-then-abandoned."),
 "541a3b6e-57e5-4209-9fab-d2927865ad12":("verifier_substring_gate_collapse","zero_weight_descriptive","evidence_absent_or_self_report","medium",
   "I8-a: researcher rt0='yes' (automated impact dashboards) then collapsed; verifier substring_check=fail; abstain. ODMI self-report cites data.gouv.fr/fr/dashboard (public). Zero score weight."),
 "1a39d65d-142f-457a-8315-32fe9413d510":("verifier_substring_gate_collapse","fetch_blocked_403","evidence_absent_or_self_report","medium",
   "P13 EE: researcher rt1='yes' then reverted; 3/3 substring fail, 403. ODMI self-report (expert community ~700 people) - a count not on open web; found-then-killed."),
 "cc48a133-680a-4302-ba97-7a96fda1cb18":("verifier_substring_gate_collapse","fetch_blocked_403","evidence_absent_or_self_report","high",
   "P25: researcher rt0,rt1='yes' then inconclusive; 4/4 substring fail, 403; escalated. ODMI: marginal-cost charging in French law (public, citable)."),
 "c278cff9-a714-4043-a96f-bfa507704226":("verifier_substring_gate_collapse","fetch_blocked_403","selection_or_interpretation_miss","high",
   "PT10 EE: researcher rt1='yes' having found portal source code (dataset-rating.entity.ts, metadataRating); verifier rejected on substring/relevance, reverted. ODMI confirms rating when logged in (public). Correct answer found and destroyed."),
 "c381f17d-6eaa-47a2-9ce2-1fb061aa3a81":("verifier_substring_gate_collapse","fetch_blocked_403","evidence_absent_or_self_report","high",
   "PT11 EE: researcher rt0='yes' then inconclusive; 1/2 substring fail, 403. ODMI: discussions + news sections at avaandmed.eesti.ee (public URLs)."),
 "e6b8a727-7b27-430c-bcbd-57f7fbb61a9c":("verifier_substring_gate_collapse","evidence_absent_or_self_report","selection_or_interpretation_miss","high",
   "PT12 EE: researcher rt0='yes' then inconclusive; 1/2 substring fail. ODMI: RSS feed + logged-in notifications (public portal feature)."),
 "1bb5d25c-61b7-4aeb-a715-3e0ac707f17c":("verifier_substring_gate_collapse","evidence_absent_or_self_report","inconclusive_collapse","high",
   "PT41: researcher rt1='yes' then inconclusive; 3/3 substring fail. ODMI: portal sustainability strategy, mission defined by law (public)."),
 "c8f570b3-58a0-484f-839b-b61909c626c5":("verifier_substring_gate_collapse","fetch_blocked_403","evidence_absent_or_self_report","high",
   "Q23 FR: researcher rt0='yes' (metadata quality score) then inconclusive; 1/2 substring fail, 403. ODMI cites public post on data.gouv.fr metadata quality score."),

 # --- M6 inconclusive_collapse (found then abandoned, NOT driven by substring gate) ---
 "26e68b85-2c48-45df-853a-7df2e4167fff":("inconclusive_collapse","evidence_absent_or_self_report","verifier_substring_gate_collapse","medium",
   "PT44: researcher rt0='yes' then rt1='inconclusive' with no substring failure recorded; caved on its own. ODMI self-report (monitors data characteristics over time)."),

 # --- N2 zero_weight as PRIMARY (descriptive, non-scored, nothing else going on) ---
 "a317928b-68da-42cd-911d-a0a210f5cf8b":("zero_weight_descriptive","evidence_absent_or_self_report","","high",
   "I8-d: question_text literally 'Other', scoring yes=0/no=0, ODMI max_score=0. Disagreement carries no score. rt0 inconclusive, no retry."),

 # --- M4 selection_or_interpretation_miss (public artefact existed, often URL'd in ODMI explanation, swarm gave up - mostly rt0) ---
 "a0a699a0-84e1-48d1-bbab-deee81ccc442":("selection_or_interpretation_miss","","evidence_absent_or_self_report","medium",
   "P17: inconclusive at rt0 (no retry). ODMI explanation itself gives public URLs: data.gouv.fr/fr/pages/team/ and a legifrance decree defining team responsibilities. Governance doc is public; swarm did not surface it."),
 "4050a3c2-8ea7-4786-aaeb-470e7d6418f0":("selection_or_interpretation_miss","","evidence_absent_or_self_report","medium",
   "P18: inconclusive at rt0. ODMI: 'the open data team IS the data.gouv.fr team https://www.data.gouv.fr/fr/pages/team/'. Trivially public page not found."),
 "9f174507-39bc-4cfb-90f8-e43d28486584":("selection_or_interpretation_miss","","ground_truth_contested","medium",
   "P6: swarm 'no' at rt0. ODMI 'yes' reads the open-to-all roadmap (citizens/journalists can publish) as the incentive measure. Roadmap is public; swarm read 'incentive measures' narrowly. Defensible interpretation gap."),
 "30123e31-99b7-4aa4-9fbe-ce1df30a7124":("selection_or_interpretation_miss","fetch_blocked_403","evidence_absent_or_self_report","low",
   "Q1 EE: inconclusive rt3, 4/4 substring fail, no answer ever found. ODMI cites Public Information Act (riigiteataja law URL). Public law reachable in principle but EE 403s blocked it."),
 "3c0a9db5-aedc-4dbf-bdb4-1b58eab6f008":("selection_or_interpretation_miss","","evidence_absent_or_self_report","medium",
   "Q11 FR: inconclusive rt0. ODMI: licence recommendation LOV2/ODbL, public bodies must choose (policy/legifrance, public). Not surfaced."),
 "f45ee214-e2cd-41ee-af20-a924fce09af2":("selection_or_interpretation_miss","","evidence_absent_or_self_report","medium",
   "Q4 FR: inconclusive rt0. ODMI: file-type options on data.gouv.fr publish flow (documentation/API/code repo) - a public portal feature. Not surfaced."),

 # --- M2 ground_truth_contested (candidate swarm win) ---
 "84aea4d0-a8b3-47b7-b8ee-4f20fd9b4ccf":("ground_truth_contested","","selection_or_interpretation_miss","high",
   "PT4: swarm 'no' (conf 0.92), quoting data.gouv.fr's own guide that it has NO SPARQL endpoint and redirects to data.europa.eu. Live check 2026-06-02 confirmed verbatim. ODMI 'yes' cites a generic REST API reference, not SPARQL. Swarm is likely correct."),

 # --- M7 format_failure (out of allowed set) ---
 "ba86ec3c-7e63-4da9-a480-4af21cce4537":("format_failure","selection_or_interpretation_miss","","high",
   "PT37: ordinal_magnitude question; swarm emitted 'yes' (not in allowed set). Substantively the evidence found (nightly harvesting of all local portals) supports ODMI's 'all datasets'. Pure shape error."),

 # --- M1 evidence_absent_or_self_report (gold answer is a country self-report / internal practice / catalogue computation, not on open web) ---
 "562ea82d-9d89-4082-8efb-fd09b21ab6f9":("evidence_absent_or_self_report","verifier_substring_gate_collapse","","high",
   "I18 EE: inconclusive, 4/4 substring fail, never found. ODMI self-report (Equality Center reuse example). No retrievable public artefact."),
 "6f6fa151-b7cb-4773-b566-0957f16a8bc3":("evidence_absent_or_self_report","fetch_blocked_403","verifier_substring_gate_collapse","high",
   "I19 EE: inconclusive, 403, 4/4 substring fail. ODMI self-report (Ministry of Climate housing reuse). Self-reported reuse case."),
 "26992c8d-f48b-41fa-9940-3739cfbe8bb9":("evidence_absent_or_self_report","zero_weight_descriptive","","high",
   "I8-b: inconclusive, zero score weight. ODMI self-report (IGN survey via tally.so form)."),
 "8f1ccc47-598a-4961-968e-a70118ce0f6b":("evidence_absent_or_self_report","zero_weight_descriptive","verifier_substring_gate_collapse","high",
   "I9-b: inconclusive, zero weight, 4/4 substring fail. ODMI self-report (open data team social media activity)."),
 "1fbd718b-c221-48e9-809e-66f878b3540e":("evidence_absent_or_self_report","zero_weight_descriptive","","high",
   "I9-c: inconclusive rt0, zero weight, 403. ODMI self-report (annual reuser survey)."),
 "9b952a12-1499-4368-ab8a-4fb6f8f1451d":("evidence_absent_or_self_report","zero_weight_descriptive","","medium",
   "P14 EE: categorical, swarm inconclusive vs ODMI 'top-down'; zero weight, 4/4 substring fail. ODMI self-report about ministry reorganisation of the open data team. Governance approach is a self-report."),
 "45486fb1-5ce8-4e0f-af34-417228193df1":("evidence_absent_or_self_report","fetch_blocked_403","selection_or_interpretation_miss","medium",
   "P24 FR: inconclusive rt0, 403. ODMI is a 5493-char self-report of portal objectives. Long narrative, no single citable artefact."),
 "ee7ca52f-6f1a-431b-abc4-d777688fcd2f":("evidence_absent_or_self_report","","ground_truth_contested","medium",
   "P10-b FR: swarm 'no' rt0. ODMI 'yes' is aspirational self-report ('Ministries are working on inventories... will include data that cannot be published' - future tense). Swarm's 'no' is defensible; weakly sourced either way."),
 "89444812-9a4b-42d7-b431-e66b494e4c23":("evidence_absent_or_self_report","","","high",
   "PT24 FR: inconclusive rt3. ODMI self-report ('we run analytics on API usage... Matomo'). Internal monitoring practice, not externally verifiable."),
 "f396133c-65f4-4ca0-8d90-ae97828f2691":("evidence_absent_or_self_report","verifier_substring_gate_collapse","","high",
   "PT28 FR: inconclusive rt3, 3/4 substring fail. ODMI self-report ('we monitor search keywords... UX research'). Internal practice."),
 "8cfe5060-1280-414c-a1fd-3ce4b043ce6f":("evidence_absent_or_self_report","verifier_substring_gate_collapse","","high",
   "PT33 FR: inconclusive rt2, 2/3 substring fail, ODMI explanation N/A. Internal-process question (identify non-publishing providers). No public artefact."),
 "7f8b3065-2463-460e-9472-f5964a38113e":("evidence_absent_or_self_report","fetch_blocked_403","","high",
   "Q10 EE: inconclusive, 403, 2/2 substring fail. ODMI self-report (national data description standard, DCAT-AP minimum metadata)."),
 "4d3685f8-d7c2-43e8-b213-1510bc2b287f":("evidence_absent_or_self_report","fetch_blocked_403","ground_truth_contested","high",
   "Q12 EE: percentage_band (catalogue-derivable set). ODMI '>90%' with N/A explanation - a self-report needing catalogue computation. 403 blocked the EE catalogue. Swarm cannot get this from web search."),
 "2cdb6c72-3385-46f6-8975-c0ab1f240d89":("evidence_absent_or_self_report","verifier_substring_gate_collapse","","medium",
   "Q1 FR: inconclusive rt3, 2/2 substring fail, escalated. ODMI short self-report ('we automatically update metadata via APIs/harvesting'). Internal practice."),
 "e0c01040-9fc9-47ab-a065-cec506159b53":("evidence_absent_or_self_report","ground_truth_contested","","high",
   "Q12 FR: percentage_band (catalogue-derivable). ODMI '>90%' (N/A explanation, self-report). Researcher correctly notes no web statistic exists. D30 independent recompute read FR licence coverage ~38%, so ODMI's >90% is contested. Inconclusive is the honest web answer."),
 "ad68ee6d-0744-4e28-a560-c77a1990749a":("evidence_absent_or_self_report","ground_truth_contested","","high",
   "Q17 FR: percentage_band (catalogue-derivable). ODMI '>90%' self-report. D30 recompute much lower. Not answerable from open web; ODMI contested."),
 "230a9fa9-8c0b-4c00-a55c-e41450eb6999":("evidence_absent_or_self_report","ground_truth_contested","","high",
   "Q18 FR: percentage_band (catalogue-derivable, DCAT-AP conformance). ODMI '>90%' self-report; D30 recompute ~32%. Not web-answerable; ODMI contested."),
 "7cbd6e33-2e5f-47f3-8b62-9e3c07d5b43c":("evidence_absent_or_self_report","verifier_substring_gate_collapse","","high",
   "Q20 FR: inconclusive rt2, 2/3 substring fail. ODMI self-report (HVD reporting, DCAT-AP care). Internal practice."),
 "a14b23e0-d2bf-4de6-879f-d21b9a702795":("evidence_absent_or_self_report","verifier_substring_gate_collapse","","high",
   "Q6 FR: inconclusive rt1, 1/2 substring fail. ODMI self-report (HVD interoperability measures beyond DCAT-AP)."),
}

ADDR = {
 "evidence_absent_or_self_report":"Out of reach for web search: gold answer is a country self-report / internal practice / catalogue computation. Route catalogue-derivable percentages to the D30 tool; otherwise human escalation or accept 'inconclusive' as the honest answer and stop scoring it as a swarm error. Neither lever A nor C touches this.",
 "ground_truth_contested":"Human glance: likely swarm win against a stale or loose ODMI self-report. No automated fix; flag for the disagreement-review log.",
 "selection_or_interpretation_miss":"Coverage/commit fix: enforce a minimum-retry floor (many are rt0 give-ups) and improve source selection. Lever A (diverge queries on rejection) is partially relevant; C is not.",
 "inconclusive_collapse":"Commit-policy / confidence-threshold fix so a found answer is not abandoned. Lever A may help; the substring gate is not the cause here.",
 "verifier_substring_gate_collapse":"Fix the Verifier's verbatim substring gate: verify against actually-fetched page text, or allow semantic/normalised match, instead of rejecting quotes that cannot be re-matched on un-fetched or 403'd pages. NEITHER lever A nor C addresses this.",
 "adjudication_propagation_loss":"Pipeline fix: write adjudicator_answer to final_answer on verifier_correct / researcher_correct (run_coordinator.py:973-990). Immediate free wins; no lever needed.",
 "zero_weight_descriptive":"Non-scored question (max_score=0): exclude from accuracy or reclassify as non-error. No fix warranted.",
 "format_failure":"Lever C directly (constrain output to the allowed answer set). Plus schema-retry hardening for the no_swarm_answer set.",
}

def norm(s): return (s or "").strip().lower()
def om(sw,od):
    sw,od=norm(sw),norm(od)
    return bool(sw and od and (sw==od or (sw=='yes' and od.startswith('yes')) or (sw=='no' and od=='no')))
def near(shape,allowed,fa,od):
    if shape not in ('percentage_band','ordinal_magnitude','count_band'): return False
    try: al=[x.strip().lower() for x in json.loads(allowed)]
    except: return False
    a,b=norm(fa),norm(od)
    return a in al and b in al and abs(al.index(a)-al.index(b))==1

rows=db.execute("""
SELECT f.pair_run_id pid, f.question_id q, f.country_code cc, f.final_answer fa, f.retry_count rt, f.terminal_status term,
       q.dimension dim, q.answer_shape shape, q.allowed_answers allowed, gt.response odmi, gt.max_score mx, gt.explanation expl
FROM phase2_final f
LEFT JOIN ground_truth gt ON gt.question_id=f.question_id AND gt.country_code=f.country_code AND gt.cycle_year=2025
LEFT JOIN questions q ON q.question_id=f.question_id
WHERE f.experiment_id IS NULL AND gt.response IS NOT NULL AND TRIM(gt.response)<>''
ORDER BY q.dimension, f.country_code, f.question_id
""").fetchall()

out=[]
for r in rows:
    fa=r['fa']
    if fa is None or not fa.strip():
        ms='no_swarm_answer'
    elif om(fa,r['odmi']):
        ms='match'
    elif near(r['shape'],r['allowed'],fa,r['odmi']):
        ms='near_match'
    else:
        ms='differ'
    if ms=='match': continue
    if ms=='no_swarm_answer':
        prim,contrib,run,conf="format_failure","","","high"
        note=f"terminal_status={r['term']}, final_failure_reason=schema_invalid after 3 retries. Researcher never emitted a schema-valid answer; ODMI='{r['odmi']}'."
    elif ms=='differ':
        if r['pid'] not in C:
            raise SystemExit(f"UNCLASSIFIED differ pid {r['pid']} {r['q']}/{r['cc']}")
        prim,contrib,run,conf,note=C[r['pid']]
    else:  # near_match (none expected)
        prim,contrib,run,conf,note="near_match_adjacent_band","","","high","adjacent band miss"
    out.append({
        "question_id":r['q'],"country_code":r['cc'],"dimension":r['dim'],"answer_shape":r['shape'],
        "swarm_answer":fa,"odmi_response":r['odmi'],"match_status":ms,"terminal_status":r['term'],
        "retry_count":r['rt'],"primary_mode":prim,"contributing_factor":contrib,
        "addressed_by":ADDR.get(prim,""),"classification_confidence":conf,
        "evidence_note":note,"runner_up_mode":run,
    })

cols=["question_id","country_code","dimension","answer_shape","swarm_answer","odmi_response",
      "match_status","terminal_status","retry_count","primary_mode","contributing_factor",
      "addressed_by","classification_confidence","evidence_note","runner_up_mode"]
with open("evaluation/failure_modes.csv","w",newline="") as fh:
    w=csv.DictWriter(fh,fieldnames=cols); w.writeheader()
    for o in out: w.writerow(o)

# print tallies for the writeup
from collections import Counter
print("rows:",len(out))
print("by match_status:",Counter(o['match_status'] for o in out))
print("\nPRIMARY MODE counts (all failed pairs):")
for m,n in Counter(o['primary_mode'] for o in out).most_common(): print(f"  {n:2}  {m}")
print("\nPRIMARY MODE x dimension:")
dd=Counter((o['primary_mode'],o['dimension']) for o in out)
for (m,d),n in sorted(dd.items()): print(f"  {n:2}  {m} / {d}")
print("\nby country:",Counter(o['country_code'] for o in out))
print("\ncontributing factor counts:",Counter(o['contributing_factor'] for o in out if o['contributing_factor']))
