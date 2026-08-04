"""Build Table 3.2: catalogue recompute against the self-reported answer.

Rows are one self-report line per country followed by one line per harvest, so
sample-size and route effects are visible rather than averaged away. Held-out
countries are excluded: this is a methodology table and D47 keeps the held-out
eight out of anything that informs a design decision.

Where a snapshot has more than one metrics pass, the latest computed_at wins.
Earlier passes are reported to stderr rather than dropped silently, because the
values differ materially on some countries and the choice needs to be visible.

    python3 evaluation/build_table_3_2.py > build/table_3_2.md
"""

from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict

DB = "data/odmi.db"

# The nine computable Quality questions, in questionnaire order.
QUESTIONS = ["Q12", "Q13", "Q16", "Q17", "Q18", "Q21", "Q22", "Q25", "Q27"]

SHORT = {
    "Q12": "Licence\npresence",
    "Q13": "Distinct\nlicences",
    "Q16": "Mandatory\nconformance",
    "Q17": "Recommended\nusage",
    "Q18": "Optional\nusage",
    "Q21": "Download\nURL",
    "Q22": "Access\nURL",
    "Q25": "Open\nlicence",
    "Q27": "Open\nformat",
}

# D47 held-out set, excluded here.
HELD_OUT = {"BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE"}

ROUTE_LABEL = {
    "dcat_rdf": "DCAT-AP RDF",
    "ckan_json": "CKAN",
    "al_dcat_api": "DCAT-AP API",
    "sparql_rdf": "SPARQL",
    "estonia_json": "bespoke JSON",
}


def fmt_value(qid, raw):
    if raw is None:
        return "--"
    if qid == "Q13":                      # a count of distinct licences
        return f"{raw:.0f}"
    return f"{raw:.1f}"


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    snaps = {}
    for r in con.execute("""select snapshot_id, country_code, harvest_route,
                                   dataset_count, page_count, partial,
                                   substr(fetched_at,1,10) as day,
                                   substr(content_sha256,1,7) as sha
                            from catalogue_snapshots"""):
        if r["country_code"] in HELD_OUT:
            continue
        if r["dataset_count"] == 0:       # failed harvests carry no metrics
            continue
        snaps[r["snapshot_id"]] = dict(r)

    # Latest metrics pass per (snapshot, question).
    latest, shadowed = {}, defaultdict(list)
    for r in con.execute("""select snapshot_id, question_id, raw_value, numerator,
                                   denominator, band_label, computed_at
                            from catalogue_metrics order by computed_at"""):
        if r["snapshot_id"] not in snaps:
            continue
        key = (r["snapshot_id"], r["question_id"])
        if key in latest and latest[key]["raw_value"] != r["raw_value"]:
            shadowed[key].append(latest[key])
        latest[key] = dict(r)

    selfrep = {}
    for r in con.execute("""select country_code, question_id, response
                            from ground_truth where question_id in
                            ({})""".format(",".join("?" * len(QUESTIONS))), QUESTIONS):
        selfrep[(r["country_code"], r["question_id"])] = r["response"]

    by_country = defaultdict(list)
    for sid, s in snaps.items():
        by_country[s["country_code"]].append(s)
    for c in by_country:
        by_country[c].sort(key=lambda s: (s["day"], s["dataset_count"]))

    # ---- emit -----------------------------------------------------------
    head = ["Country", "Source", "n"] + [SHORT[q].replace("\n", " ") for q in QUESTIONS] + ["Agree"]
    print("| " + " | ".join(head) + " |")
    print("|" + "|".join(["---"] * len(head)) + "|")

    totals = [0, 0]
    for cc in sorted(by_country):
        row = [cc, "*Self-reported*", "--"]
        for q in QUESTIONS:
            row.append(f"*{selfrep.get((cc, q), '--')}*")
        row.append("--")
        print("| " + " | ".join(row) + " |")

        for s in by_country[cc]:
            route = ROUTE_LABEL.get(s["harvest_route"], s["harvest_route"])
            if s["partial"]:
                route += ", partial"
            agree = total = 0
            cells = []
            for q in QUESTIONS:
                m = latest.get((s["snapshot_id"], q))
                if not m:
                    cells.append("--")
                    continue
                want = selfrep.get((cc, q))
                got = m["band_label"]
                if want is not None and got is not None:
                    total += 1
                    if str(want).strip() == str(got).strip():
                        agree += 1
                        cells.append(f"**{fmt_value(q, m['raw_value'])}**")
                    else:
                        cells.append(fmt_value(q, m["raw_value"]))
                else:
                    cells.append(fmt_value(q, m["raw_value"]))
            totals[0] += agree
            totals[1] += total
            print("| | " + " | ".join([route, f"{s['dataset_count']:,}"] + cells
                                      + [f"{agree}/{total}"]) + " |")

    print()
    print(f"Agreement across all reported harvests: {totals[0]} of {totals[1]} "
          f"({totals[0] / totals[1] * 100:.0f}%). Bold marks a recomputed value "
          f"falling in the band the country reported. Values are percentages "
          f"except distinct licences, which is a count.")

    if shadowed:
        print("\n<!-- earlier metrics passes not used, see stderr -->")
        print("\nSUPERSEDED METRICS PASSES (same snapshot, different value):",
              file=sys.stderr)
        for (sid, q), olds in sorted(shadowed.items()):
            cur = latest[(sid, q)]
            for o in olds:
                print(f"  {snaps[sid]['country_code']} {q} {sid}: "
                      f"{o['raw_value']} ({o['computed_at']}) superseded by "
                      f"{cur['raw_value']} ({cur['computed_at']})", file=sys.stderr)


if __name__ == "__main__":
    main()
