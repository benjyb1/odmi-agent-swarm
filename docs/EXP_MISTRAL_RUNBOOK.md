# Mistral cross-family arm — runbook

How to plug in a Mistral API key and run the swarm on Mistral so its results
compare like-for-like against the Claude baseline. This is the cross-family arm
of EXP-9 (model variants): same Researcher / Verifier / Adjudicator prompts,
same schemas, same retry logic, a different model family on a separate quota.

## How it is wired

- A Mistral model id (anything starting `mistral`) passed to any agent routes
  through `agents/tools/mistral_provider.py` instead of CLIProxyAPI. The single
  branch lives in `agents/tools/llm.py:call_for_structured`, so every existing
  per-agent override flag works unchanged.
- Mistral is called directly against its OpenAI-compatible endpoint. Calls are
  off the Claude Max budget, so nothing lands in `claude_usage_log`. The per-pair
  receipt still records tokens and a real Mistral cost in `phase2_final`.
- `estimated_cost_usd` for a Mistral pair is the real Mistral list price, not the
  arithmetic-equivalent Claude figure. The `model_version` on every receipt names
  the provider, so the two cost bases are never silently mixed.

## 1. Add the key

The key is read from `MISTRAL_API_KEY` in `.env`. A fresh worktree has no `.env`
(it is gitignored), so copy it from the main checkout first, then add the key:

```bash
cp ../../../.env .env          # only if this worktree has no .env yet
printf '\nMISTRAL_API_KEY=your-key-here\n' >> .env
```

## 2. Smoke-test before dispatching

```bash
uv run python scripts/check_mistral.py
```

This runs an auth probe and one real structured-output call through the swarm's
own code path. A key that authenticates but cannot return schema-valid JSON is
caught here, not mid-dispatch. Use `--model mistral-small-latest` for a cheaper
check.

## 3. Dispatch the Mistral arm

Run it on the SAME (question, country) set as the Claude baseline so the
comparison is paired. Tag it with an experiment id to keep it out of the
headline numbers (D27):

```bash
uv run python scripts/dispatch_subtrios.py --questions P1 P2 --countries MT \
    --researcher-model mistral-large-latest \
    --verifier-model mistral-large-latest \
    --adjudicator-model mistral-large-latest \
    --experiment-id exp9_mistral
```

The three model flags are independent. A mixed trio (cheap Researcher, Claude
Adjudicator) is the more interesting design — it tests which role actually needs
the stronger model:

```bash
    --researcher-model mistral-large-latest \
    --verifier-model mistral-large-latest \
    --adjudicator-model claude-sonnet-4-6
```

## 4. Read the comparison

```bash
uv run python evaluation/claude_vs_mistral.py --mistral-experiment exp9_mistral
```

Prints per-arm exact-match / match+near / abstention / modelled cost / tokens /
latency, then a paired view over the pairs both arms ran: same-answer rate,
per-arm accuracy, the accuracy delta, and a row-by-row disagreement table
(ODMI vs Claude vs Mistral). Baseline defaults to main runs; pass
`--baseline-experiment <id>` if the Claude arm is itself tagged.

## Notes

- Free-tier Mistral throttles to ~1 req/s; the provider paces calls and backs
  off on HTTP 429. A spent hard quota raises after the retries and is reported
  as a failed pair rather than masked.
- Pricing in `mistral_provider.PRICING_USD_PER_M` is hard-coded for reproducible
  cost receipts; refresh deliberately if Mistral's prices move.
- Confounds to hold in mind when reading the delta: a Mistral loss can be weaker
  reasoning, weaker coverage of the specific EU languages in the sample, or
  weaker JSON compliance. A schema failure surfaces cleanly (the pair errors),
  so the third is separable from the first two in the logs.
