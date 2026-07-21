"""EXP-41: the cache purge, and the frozen-config claim the campaign rests on.

The campaign's whole argument is that four dispatches ran under an identical
configuration with no evidence carried between them. Both halves of that are
mechanical and therefore testable, so they are tested rather than asserted.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "evaluation" / "specs"
CACHE_TABLES = ("search_cache_serp", "search_cache_fetch", "search_cache_snippet")

sys.path.insert(0, str(REPO))

from scripts.gen_exp41_specs import FROZEN_KNOBS, RUNS  # noqa: E402
from scripts.purge_search_cache import archive, counts  # noqa: E402


def _db_with_cache(path: Path, rows: int = 3) -> Path:
    conn = sqlite3.connect(str(path))
    for t in CACHE_TABLES:
        conn.execute(f"CREATE TABLE {t} (cache_key TEXT PRIMARY KEY, payload TEXT)")
        conn.executemany(
            f"INSERT INTO {t} VALUES (?, ?)",
            [(f"{t}-{i}", "x") for i in range(rows)],
        )
    conn.commit()
    conn.close()
    return path


def _purge(db: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "purge_search_cache.py"),
         "--db", str(db), *args],
        capture_output=True, text=True, cwd=str(REPO),
    )


# --- the purge -------------------------------------------------------------

def test_dry_run_deletes_nothing(tmp_path):
    db = _db_with_cache(tmp_path / "a.db")
    assert _purge(db).returncode == 0
    conn = sqlite3.connect(str(db))
    assert sum(counts(conn).values()) == 9
    conn.close()


def test_apply_empties_every_cache_table(tmp_path):
    db = _db_with_cache(tmp_path / "b.db")
    res = _purge(db, "--apply")
    assert res.returncode == 0
    assert "VERIFIED EMPTY" in res.stdout
    conn = sqlite3.connect(str(db))
    assert counts(conn) == {t: 0 for t in CACHE_TABLES}
    conn.close()


def test_archive_captures_rows_before_the_delete(tmp_path):
    """The receipt has to be the pre-purge state, or it records nothing."""
    db = _db_with_cache(tmp_path / "c.db")
    arc = tmp_path / "receipts" / "rep1.db"
    assert _purge(db, "--apply", "--archive", str(arc)).returncode == 0

    conn = sqlite3.connect(str(arc))
    assert counts(conn) == {t: 3 for t in CACHE_TABLES}
    conn.close()

    conn = sqlite3.connect(str(db))
    assert sum(counts(conn).values()) == 0
    conn.close()


def test_archive_refuses_to_overwrite_and_purges_nothing(tmp_path):
    """One run's receipt must not be silently replaced by another's.

    The failure this campaign exists to repair is a run whose receipts went
    missing, so a clobbered archive fails loudly and leaves the cache intact.
    """
    db = _db_with_cache(tmp_path / "d.db")
    arc = tmp_path / "rep1.db"
    assert _purge(db, "--apply", "--archive", str(arc)).returncode == 0

    db2 = _db_with_cache(tmp_path / "e.db")
    res = _purge(db2, "--apply", "--archive", str(arc))
    assert res.returncode == 2
    assert "refusing to overwrite" in res.stdout

    conn = sqlite3.connect(str(db2))
    assert sum(counts(conn).values()) == 9, "cache purged despite a failed archive"
    conn.close()


def test_archive_helper_raises_on_existing_destination(tmp_path):
    db = _db_with_cache(tmp_path / "f.db")
    arc = tmp_path / "taken.db"
    arc.write_bytes(b"")
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(FileExistsError):
            archive(conn, arc)
    finally:
        conn.close()


def test_missing_cache_tables_are_not_an_error(tmp_path):
    """The tables self-recreate lazily, so a DB without them must purge cleanly."""
    db = tmp_path / "empty.db"
    sqlite3.connect(str(db)).close()
    res = _purge(db, "--apply")
    assert res.returncode == 0
    assert "VERIFIED EMPTY" in res.stdout


# --- the frozen-config claim ----------------------------------------------

def _spec(eid: str) -> dict:
    return json.loads((SPECS / f"{eid}.json").read_text())["experiments"][0]


def test_specs_on_disk_match_the_generator():
    """Guards against a spec being hand-edited away from FROZEN_KNOBS."""
    res = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_exp41_specs.py"), "--check"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_three_replicates_are_knob_identical():
    reps = [_spec(f"exp41_stability_rep{i}")["baseline_knobs"] for i in (1, 2, 3)]
    assert reps[0] == reps[1] == reps[2]


def test_cooperative_differs_in_exactly_one_knob():
    """The one-variable rule: stance is the only thing that moves."""
    trio = _spec("exp41_stability_rep1")["baseline_knobs"]
    coop = _spec("exp41_cooperative_rerun")["baseline_knobs"]
    diff = {k for k in set(trio) | set(coop) if trio.get(k) != coop.get(k)}
    assert diff == {"pipeline_mode"}


def test_every_spec_runs_cold_and_carries_no_seed():
    for run in RUNS:
        knobs = _spec(run["experiment_id"])["baseline_knobs"]
        assert knobs["no_cache"] is True, run["experiment_id"]
        assert "seed_experiment_id" not in knobs, run["experiment_id"]
        assert "seed_condition_label" not in knobs, run["experiment_id"]


def test_replicates_have_distinct_experiment_ids():
    """Sharing an id would make run_experiments skip replicates 2 and 3
    outright, and would let _find_resumable_researcher share evidence."""
    ids = [r["experiment_id"] for r in RUNS]
    assert len(set(ids)) == len(ids)


def test_no_model_knob_is_left_to_the_stale_model_defaults_row():
    """model_defaults still holds claude-sonnet-5, which is cut (D59)."""
    for run in RUNS:
        knobs = _spec(run["experiment_id"])["baseline_knobs"]
        for k in ("researcher_model", "verifier_model",
                  "adjudicator_model", "picker_model"):
            assert knobs.get(k) == "claude-sonnet-4-6", f"{run['experiment_id']}/{k}"


def test_battery_is_the_156_pair_dev_set_and_identical_across_specs():
    pairs = [tuple(_spec(r["experiment_id"])["pairs"]) for r in RUNS]
    assert all(len(p) == 156 for p in pairs)
    assert len(set(pairs)) == 1, "the four specs do not share one pair list"

    countries = [p.split(":")[1] for p in pairs[0]]
    assert {c: countries.count(c) for c in set(countries)} == {
        "MT": 60, "NL": 52, "AL": 44
    }
    assert set(countries).isdisjoint(
        {"BA", "MK", "ME", "BG", "FI", "HR", "SE", "BE"}
    ), "a D47 held-out country reached the spec"


def test_frozen_knobs_pins_every_behavioural_default():
    """Anything a spec leaves out silently takes a dispatch default. The
    campaign claims none do, so the pinned set is asserted explicitly."""
    expected = {
        "researcher_model", "verifier_model", "adjudicator_model", "picker_model",
        "provider", "search_strategy", "max_results_per_query", "num_queries",
        "query_language", "strategy", "verifier_prompt_variant", "prompt_variant",
        "verifier_search", "adjudicator_selection", "max_retries",
        "snippet_picker", "max_snippet_chars", "picker_max_chunks",
        "page_text_cap", "no_cache",
    }
    assert set(FROZEN_KNOBS) == expected
