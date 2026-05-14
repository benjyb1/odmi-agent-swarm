"""Harness CLI for high-level swarm commands.

A single entry point that bundles the most common operations so they
can be invoked by name rather than by stringing together
`dispatch_subtrios.py`, `check_data_leakage.py`, and bespoke SQL.

Examples
--------

    # See what is in the DB right now.
    uv run python scripts/harness.py status
    uv run python scripts/harness.py status --country FR

    # List pairs that still need a swarm answer.
    uv run python scripts/harness.py pending --country FR --limit 10

    # Audit the DB for ODMI data-leakage violations (read-only).
    uv run python scripts/harness.py audit

    # Delete every pair_run row that cites a banned source.
    uv run python scripts/harness.py purge-leakage --yes

    # Run every unfinished FR pair that fits in a £3 budget.
    uv run python scripts/harness.py run --country FR --budget-gbp 3

    # Run a single named pair.
    uv run python scripts/harness.py run-pair P1 FR

    # Tail the latest finalised pairs.
    uv run python scripts/harness.py recent --limit 20

Design rules
------------
- Read-only commands are safe to call without flags.
- Destructive commands (`purge-leakage`, `run`, `run-pair`) require an
  explicit `--yes` flag to actually do anything; without it they print
  what they would do and exit.
- Cost figures are shown in £ everywhere; the underlying column is
  still USD (`estimated_cost_usd`), converted via
  `dashboard.lib.currency`.
"""

from __future__ import annotations

import argparse
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dashboard.lib.currency import format_gbp, to_gbp  # noqa: E402

DB_PATH = REPO_ROOT / "data" / "odmi.db"
GBP_PER_USD = 0.79   # mirror of USD_TO_GBP in dashboard.lib.currency

# Sensible fall-back if claude_usage_log is empty: ~£0.08 per finished
# subtrio based on Sonnet pricing × ~6 calls per pair.
_FALLBACK_PAIR_COST_USD = 0.10


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# Status / inspection
# ============================================================

def cmd_status(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        where = ""
        params: tuple = ()
        if args.country:
            where = "WHERE country_code = ?"
            params = (args.country,)

        gt = conn.execute(
            f"SELECT COUNT(*) FROM ground_truth {where}", params
        ).fetchone()[0]
        finals = conn.execute(
            f"SELECT COUNT(*) FROM phase2_final {where}", params
        ).fetchone()[0]
        researchers = conn.execute(
            f"SELECT COUNT(*) FROM phase2_researcher_runs {where}", params
        ).fetchone()[0]
        verifiers = conn.execute(
            f"SELECT COUNT(*) FROM phase2_verifier_runs {where}", params
        ).fetchone()[0]

        # Cost in the rolling 5-hour window.
        cost_5h = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) "
            "FROM claude_usage_log "
            "WHERE timestamp >= datetime('now', '-5 hours')"
        ).fetchone()[0]
        cost_today = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) "
            "FROM claude_usage_log "
            "WHERE timestamp >= date('now')"
        ).fetchone()[0]
        cost_total = conn.execute(
            "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) "
            "FROM claude_usage_log"
        ).fetchone()[0]

        label = f"({args.country})" if args.country else "(all countries)"
        print(f"DB status {label}:")
        print(f"  ground_truth pairs   : {gt:>5}")
        print(f"  finals               : {finals:>5}")
        print(f"  researcher rows      : {researchers:>5}")
        print(f"  verifier rows        : {verifiers:>5}")
        print()
        print("Cost (£):")
        print(f"  last 5 hours         : {format_gbp(cost_5h):>8}")
        print(f"  today                : {format_gbp(cost_today):>8}")
        print(f"  all time             : {format_gbp(cost_total):>8}")
        return 0
    finally:
        conn.close()


def cmd_pending(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        sql = """
            SELECT gt.question_id, gt.country_code, gt.dimension, gt.indicator
            FROM ground_truth gt
            LEFT JOIN phase2_final f
              ON f.question_id = gt.question_id
             AND f.country_code = gt.country_code
            WHERE f.id IS NULL
        """
        params: tuple = ()
        if args.country:
            sql += " AND gt.country_code = ?"
            params = (args.country,)
        sql += " ORDER BY gt.dimension, gt.question_id"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"

        rows = conn.execute(sql, params).fetchall()
        if not rows:
            print("No pending pairs.")
            return 0
        print(f"Pending pairs: {len(rows)}")
        for r in rows:
            print(f"  {r['question_id']:>5}  {r['country_code']:>3}  "
                  f"{r['dimension']:<28}  {r['indicator']}")
        return 0
    finally:
        conn.close()


def cmd_recent(args: argparse.Namespace) -> int:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT question_id, country_code, final_answer,
                   created_at, terminal_status
            FROM phase2_final
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(args.limit or 20),),
        ).fetchall()
        if not rows:
            print("No finals yet.")
            return 0
        print(f"Latest {len(rows)} final(s):")
        for r in rows:
            print(f"  {r['created_at']:<20}  {r['question_id']:>5}  "
                  f"{r['country_code']:>3}  {(r['final_answer'] or '—'):<6}  "
                  f"({r['terminal_status']})")
        return 0
    finally:
        conn.close()


# ============================================================
# Data-leakage audit / purge
# ============================================================

def _run_audit_script(*extra: str) -> int:
    cmd = ["uv", "run", "python", str(REPO_ROOT / "scripts" / "check_data_leakage.py"), *extra]
    return subprocess.call(cmd, cwd=REPO_ROOT)


def cmd_audit(args: argparse.Namespace) -> int:
    extra = []
    if args.quiet:
        extra.append("--quiet")
    if args.csv:
        extra += ["--csv", args.csv]
    return _run_audit_script(*extra)


def cmd_purge_leakage(args: argparse.Namespace) -> int:
    if not args.yes:
        # Dry-run preview.
        print("Dry-run: scanning the DB for ODMI data-leakage violations.")
        print("Run with --yes to actually delete the tainted pair_run rows.")
        return _run_audit_script("--quiet")

    print("Purging tainted pair_run rows.")
    return _run_audit_script("--purge")


# ============================================================
# Run
# ============================================================

def _avg_pair_cost_usd(conn: sqlite3.Connection) -> float:
    """Average cost per finalised pair, in USD.

    Looks at the most recent 200 final rows and computes the per-pair
    average across their LLM calls. Falls back to a sensible default
    when the DB is sparse.
    """
    row = conn.execute(
        """
        WITH recent AS (
            SELECT pair_run_id FROM phase2_final
            ORDER BY id DESC LIMIT 200
        )
        SELECT COUNT(DISTINCT u.subtrio_id), SUM(u.estimated_cost_usd)
        FROM claude_usage_log u
        WHERE u.subtrio_id IN (SELECT pair_run_id FROM recent)
        """
    ).fetchone()
    n_pairs, total = row
    if not n_pairs or not total or n_pairs < 5:
        return _FALLBACK_PAIR_COST_USD
    return float(total) / int(n_pairs)


def _pending_pairs(conn: sqlite3.Connection, country: str, limit: int | None) -> list[tuple[str, str]]:
    sql = """
        SELECT gt.question_id, gt.country_code
        FROM ground_truth gt
        LEFT JOIN phase2_final f
          ON f.question_id = gt.question_id
         AND f.country_code = gt.country_code
        WHERE f.id IS NULL AND gt.country_code = ?
        ORDER BY gt.question_id
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [(r[0], r[1]) for r in conn.execute(sql, (country,)).fetchall()]


def cmd_run(args: argparse.Namespace) -> int:
    if not args.country:
        print("error: --country is required for `run`.")
        return 2

    conn = _connect()
    try:
        pending = _pending_pairs(conn, args.country, args.limit)
        if not pending:
            print(f"No pending pairs for {args.country}.")
            return 0
        avg_cost = _avg_pair_cost_usd(conn)
    finally:
        conn.close()

    budget_usd = (args.budget_gbp / GBP_PER_USD) if args.budget_gbp else None
    if budget_usd is not None:
        budget_n = int(budget_usd / max(avg_cost, 1e-9))
        chosen = pending[: max(0, budget_n)]
    else:
        chosen = pending

    if not chosen:
        print(
            f"{len(pending)} pending pairs, but the £{args.budget_gbp:.2f} budget "
            f"covers 0 at the current average cost of "
            f"{format_gbp(avg_cost)}/pair."
        )
        return 1

    est_cost_usd = avg_cost * len(chosen)
    print(f"Country : {args.country}")
    print(f"Pending : {len(pending)} pair(s)")
    print(f"Selected: {len(chosen)} pair(s) "
          f"(avg ~{format_gbp(avg_cost)}/pair, "
          f"est total ~{format_gbp(est_cost_usd)})")

    if not args.yes:
        print("\nDry run. Pass --yes to actually dispatch.")
        if len(chosen) <= 20:
            for qid, cc in chosen:
                print(f"  - {qid}:{cc}")
        else:
            for qid, cc in chosen[:10]:
                print(f"  - {qid}:{cc}")
            print(f"  ... and {len(chosen) - 10} more")
        return 0

    pair_args = [f"{qid}:{cc}" for qid, cc in chosen]
    dispatch_cmd = [
        "uv", "run", "python", str(REPO_ROOT / "scripts" / "dispatch_subtrios.py"),
        "--pairs", *pair_args,
        "--soft-limit-usd", f"{est_cost_usd * 1.5:.2f}",
    ]
    if args.strategy:
        dispatch_cmd += ["--strategy", args.strategy]
    if args.parallel:
        dispatch_cmd += ["--parallel", str(args.parallel)]

    print(f"\nDispatching:\n  {shlex.join(dispatch_cmd)}\n")
    return subprocess.call(dispatch_cmd, cwd=REPO_ROOT)


def cmd_run_pair(args: argparse.Namespace) -> int:
    cmd = [
        "uv", "run", "python", str(REPO_ROOT / "scripts" / "run_coordinator.py"),
        "--question-id", args.question_id,
        "--country", args.country,
    ]
    if args.strategy:
        cmd += ["--strategy", args.strategy]
    if not args.yes:
        print("Dry run. Pass --yes to actually run.")
        print(f"  {shlex.join(cmd)}")
        return 0
    return subprocess.call(cmd, cwd=REPO_ROOT)


# ============================================================
# Argparse wiring
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="High-level commands for the ODMI swarm. "
                    "Read-only by default; destructive ops require --yes.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="DB summary.")
    p_status.add_argument("--country", help="Filter to one country code (e.g. FR).")
    p_status.set_defaults(func=cmd_status)

    p_pending = sub.add_parser("pending", help="List pairs with no final answer yet.")
    p_pending.add_argument("--country")
    p_pending.add_argument("--limit", type=int, default=None)
    p_pending.set_defaults(func=cmd_pending)

    p_recent = sub.add_parser("recent", help="Show the most recent finals.")
    p_recent.add_argument("--limit", type=int, default=20)
    p_recent.set_defaults(func=cmd_recent)

    p_audit = sub.add_parser("audit", help="Scan for ODMI data-leakage violations.")
    p_audit.add_argument("--quiet", action="store_true")
    p_audit.add_argument("--csv", default=None)
    p_audit.set_defaults(func=cmd_audit)

    p_purge = sub.add_parser(
        "purge-leakage",
        help="Delete pair_run rows that cite banned sources.",
    )
    p_purge.add_argument("--yes", action="store_true",
                         help="Required to actually delete rows.")
    p_purge.set_defaults(func=cmd_purge_leakage)

    p_run = sub.add_parser(
        "run",
        help="Dispatch pending pairs for a country (optionally under a budget).",
    )
    p_run.add_argument("--country", required=True)
    p_run.add_argument("--budget-gbp", type=float, default=None,
                       help="Stop selecting pairs once est. cost exceeds £BUDGET.")
    p_run.add_argument("--limit", type=int, default=None,
                       help="Hard cap on number of pairs (applied before budget).")
    p_run.add_argument("--strategy", default=None)
    p_run.add_argument("--parallel", type=int, default=None)
    p_run.add_argument("--yes", action="store_true",
                       help="Required to actually dispatch.")
    p_run.set_defaults(func=cmd_run)

    p_run_pair = sub.add_parser(
        "run-pair",
        help="Run a single (question, country) pair end-to-end.",
    )
    p_run_pair.add_argument("question_id")
    p_run_pair.add_argument("country")
    p_run_pair.add_argument("--strategy", default=None)
    p_run_pair.add_argument("--yes", action="store_true")
    p_run_pair.set_defaults(func=cmd_run_pair)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
