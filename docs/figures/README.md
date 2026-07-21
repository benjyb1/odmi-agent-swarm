# Manuscript figures

Every figure the write-up draws on, in one place. Each entry names the script
that produces it, so any figure here can be rebuilt from the canonical DB
rather than trusted as an opaque artefact.

## Provenance and the duplication caveat

Figures fall into two groups by where their generating script writes **by
default**:

- **Written here directly.** `cost_report.py`, `risk_coverage.py` and
  `maturity_reconstruction_figure.py` take an output path and are pointed at
  this directory. Re-running them updates this copy.
- **Copied from `evaluation/figures/`.** The EXP-36 figure scripts default
  their `--out-dir` to `evaluation/figures/`, where they write the graphic
  **and** its CSV receipts side by side. Only the graphic is copied here; the
  receipts stay next to the script output.

The second group is therefore a copy, and a copy can go stale. If you re-run
one of those scripts, either re-copy the graphic here or pass
`--out-dir docs/figures` so it lands here directly. The receipts CSV in
`evaluation/figures/` is the authority on what any given figure was drawn from.

## EXP-36 held-out figures

| File | Script | Shows |
|---|---|---|
| `abstention_gold_class_by_code.png` | `evaluation/abstention_gold_class_by_code.py` | Gold-class composition of abstention codes E and G (§4.4) |
| `abstention_causes_by_country.svg` | `evaluation/abstention_causes_by_country.py` | Abstention rate per held-out country, decomposed by cause |
| `heldout_outcome_breakdown.svg` | `evaluation/heldout_outcome_breakdown.py` | Per-country outcome makeup, 100% stacked |
| `per_class_accuracy_vs_threshold.svg` | `evaluation/per_class_accuracy_vs_threshold.py` | Per-class accuracy against commit threshold |
| `per_class_accuracy_full_range.svg` | `evaluation/per_class_accuracy_full_range.py` | Per-class accuracy across the full confidence range, above and below the D37 floor |
| `reliability_by_class.svg` | `evaluation/reliability_by_class.py` | Reliability diagram split by gold class, with bin counts |
| `risk_coverage_curve.svg` | `evaluation/risk_coverage_curve.py` | Risk-coverage curve with a random-abstention null |
| `maturity_reconstruction.svg` | `evaluation/maturity_reconstruction_figure.py` | Published 2025 ODMI score against the swarm's reconstructed score |

## Cross-run figures

| File | Script | Shows |
|---|---|---|
| `abstention_by_country_dimension.svg` | `evaluation/abstention_by_country_dimension.py` | Abstention rate per country per ODMI dimension, heatmap |
| `abstention_by_country_dimension_complete_dims.svg` | same, `--complete-dims` | The same heatmap restricted to countries with all four dimensions run |
| `risk_coverage_main.svg` | `evaluation/risk_coverage.py` | Risk-coverage sweep over the main run |
| `cost_frontier.svg` | `evaluation/cost_report.py` | Cost against accuracy frontier |
| `cost_by_dimension.svg` | `evaluation/cost_report.py` | Cost per ODMI dimension |
| `cost_per_correct_country.svg` | `evaluation/cost_report.py` | Cost per correct answer, by country |
| `cost_role_share.svg` | `evaluation/cost_report.py` | Share of spend by agent role |

## Rebuilding

```bash
# EXP-36 set, straight into this directory
uv run --extra dev python evaluation/abstention_gold_class_by_code.py --outdir docs/figures
uv run python evaluation/abstention_causes_by_country.py       --out-dir docs/figures
uv run python evaluation/heldout_outcome_breakdown.py          --out-dir docs/figures
uv run python evaluation/per_class_accuracy_vs_threshold.py    --out-dir docs/figures
uv run python evaluation/per_class_accuracy_full_range.py      --out-dir docs/figures
uv run python evaluation/reliability_by_class.py               --out-dir docs/figures
uv run python evaluation/risk_coverage_curve.py                --out-dir docs/figures

# Writes here directly via its own manuscript flag
uv run python evaluation/maturity_reconstruction_figure.py --manuscript-dir docs/figures

# Cross-run
uv run python evaluation/abstention_by_country_dimension.py
uv run python evaluation/abstention_by_country_dimension.py --complete-dims
uv run python evaluation/risk_coverage.py --svg docs/figures/risk_coverage_main.svg
uv run python evaluation/cost_report.py --figures-dir docs/figures --out docs/COST_SURFACE.md
```

Passing `--out-dir docs/figures` also drops that script's CSV receipts here.
Move them back to `evaluation/figures/` if you want this directory to stay
graphics-only, which is how it is kept today.

`abstention_gold_class_by_code.py` needs matplotlib, which lives in the `dev`
extra; the rest emit hand-written SVG and need no plotting library.
