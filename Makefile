# Convenience targets for the ODMI agent swarm repo.
# Run via: make <target>

.PHONY: verify-diy verify-diy-live test test-all snippet-fixtures eyeball help

help:  ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'

verify-diy:  ## Run all non-live DIY-Tavily tests (the pre-commit gate)
	uv run pytest \
		tests/test_search_provider_arg.py \
		tests/test_search_serper.py \
		tests/test_snippet_picker.py \
		tests/test_snippet_picker_prompt.py \
		tests/test_search_diy.py \
		tests/test_search_diy_blocked.py \
		tests/test_search_cache.py \
		tests/test_extract.py \
		-v

verify-diy-live:  ## Run live DIY-Tavily tests (real Claude + Serper, costs API calls)
	uv run pytest \
		tests/test_snippet_picker_boilerplate.py \
		tests/test_snippet_picker_multilang.py \
		tests/test_drift_live.py \
		tests/test_snippet_quality.py \
		-m live -v -s

test:  ## Run the full non-live test suite
	uv run pytest tests/ -v

test-all:  ## Run everything including live tests
	uv run pytest tests/ -m "live or not live" -v

snippet-fixtures:  ## Regenerate snippet_quality.jsonl from the DB
	uv run python evaluation/build_snippet_fixtures.py

eyeball:  ## Generate the eyeball HTML harness (3-query smoke)
	uv run python evaluation/snippet_eyeball.py --providers diy,serper_raw --queries 3
