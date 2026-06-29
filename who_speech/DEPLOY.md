# Deploying the WHO/Europe speech-writer into a Copilot Studio space

This is the operator's guide for running the speech-writer as a service in
WHO's environment and connecting it to a Copilot Studio agent. It assumes the
reader can deploy a container to Azure and edit an agent in Copilot Studio.

## What it is

One MCP tool, `who_brief(country, question, format)`, that returns a verified,
cited WHO/Europe briefing. The agent in Copilot Studio is the chat front end;
this service does the work and the model call. The output is either bullet
points (one sourced point each) or speech-style paragraphs, from the same
verified evidence.

```
Copilot Studio agent (WHO tenant)
        |  MCP (Streamable HTTP)
        v
who_brief tool  --->  this service (Azure-hosted)
                          |-- IRIS client (DSpace REST)
                          |-- Docling extraction + provenance
                          |-- LanceDB hybrid retrieval
                          |-- researcher / verifier / attribution / adjudicator
                          |-- quote-gate + CC-licence gate
                          v
                      briefing pack (points + verbatim quotes + citations)
```

## Why this shape, not "inside Copilot"

Copilot Studio cannot run the Docling/LanceDB/reranker stack, and the
defensibility of the tool lives in the deterministic quote-gate and the
verifier/attribution swarm. Those must not be dissolved into a generative
agent. So the swarm stays a hardened service and Copilot Studio calls it as a
tool. Copilot Studio connects to MCP servers directly (Streamable HTTP
transport), with the server governed through connector infrastructure
(authentication, DLP, virtual-network integration).

## Decisions WHO must make first

These change the deployment; settle them before building.

1. **Model and where it runs.** Default backend is Azure OpenAI in WHO's
   tenant. Set `WHO_LLM_BACKEND=azure_openai` and the `AZURE_OPENAI_*`
   secrets. (The development backend, `claude`, routes through a local proxy
   and the parent ODMI repo; it is not for WHO deployment.)
2. **Hosting.** Which subscription and who operates the container and the
   index refresh job.
3. **IRIS access.** The service fetches bounded, polite per-country slices.
   Indexing a country at depth, or the whole ~23k-item EURO subtree, needs
   WHO's sign-off and ideally a data export rather than crawling (IRIS
   robots.txt sets a 10-second crawl delay). This is a governance decision,
   not a setting.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `WHO_LLM_BACKEND` | `claude` | `azure_openai` for WHO; `claude` for local dev |
| `AZURE_OPENAI_ENDPOINT` | – | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_KEY` | – | key (use Key Vault / managed identity) |
| `AZURE_OPENAI_DEPLOYMENT` | – | the chat deployment name |
| `AZURE_OPENAI_API_VERSION` | `2024-10-21` | Azure OpenAI API version |
| `WHO_INDEX_ROOT` | `~/.who_speech/index` | durable index location; mount a volume |
| `WHO_MAX_DOCS` | `25` | documents indexed per country |
| `WHO_INDEX_LANGUAGES` | `en` | ISO codes to index; widen for native-language coverage |
| `WHO_VERIFY_SOURCE` | `1` | re-verify each quote against an independent PDF extraction; drop non-reproducing points (set `0` to disable) |
| `WHO_MCP_TRANSPORT` | `streamable-http` | MCP transport for Copilot Studio |

The model prompts were tuned against Claude. After switching to Azure OpenAI,
re-validate before relying on it: confirm the model still quotes verbatim and
abstains when the evidence is thin (run the faithfulness harness, below).

## Build and run

```bash
# From the repository root
docker build -f who_speech/Dockerfile -t who-speech .

docker run --rm -p 8000:8000 \
    -e WHO_LLM_BACKEND=azure_openai \
    -e AZURE_OPENAI_ENDPOINT=... -e AZURE_OPENAI_API_KEY=... \
    -e AZURE_OPENAI_DEPLOYMENT=... \
    -v who_index:/data/index \
    who-speech
```

On Azure, Container Apps or App Service both work; put the secrets in Key
Vault and mount a file share at `/data/index`.

## Build the index (the refresh job)

The service answers only for countries whose index has been built; a query for
an unindexed country returns `status: "no_index"` with a clear message. Build
or refresh per country:

```bash
python -m who_speech.build "Kyrgyzstan" "Kazakhstan" "Republic of North Macedonia"
```

Run this on a schedule (e.g. an Azure Container Apps job) against the same
`WHO_INDEX_ROOT` volume. Use the exact IRIS MeSH heading for names that differ
from the common one (`Republic of North Macedonia`, `Georgia (Republic)`); the
resolver in `countries.py` handles the known cases and passes others through.

## Connect to Copilot Studio

1. Deploy the service and note its public HTTPS URL.
2. In Copilot Studio: add a tool, choose the MCP / custom-connector path, and
   point it at the service URL (Streamable HTTP). The `who_brief` tool and its
   inputs register automatically.
3. Build a topic that takes the country, the question and the desired format,
   calls `who_brief`, and returns `rendered`. The Regional Director's prose and
   the Divisional Director's bullets are the same call with
   `format=paragraphs` or `format=bullets`.

If the tenant restricts custom MCP servers, the fallback is to expose the same
service as a REST API and register it as a Power Platform custom connector.

## How the output stays defensible

- **Quote-gate.** Every point cites a verbatim quote that must appear, word for
  word, in the source passage the researcher read; otherwise it is dropped.
- **Licence gate.** Only CC-licensed IRIS items are quotable. Items without a
  permissive licence are used for retrieval but never quoted or redisplayed.
- **Attribution/relevance gate.** A point is dropped unless the action is WHO's
  (not a government's, an NGO's or the Red Cross's) and it answers the question.
- **Independent-source verification** (on by default; `WHO_VERIFY_SOURCE=0` to
  disable). After the swarm finalises, each quote is re-checked against a fresh,
  independent extraction (pypdf) of the cited PDF, tolerant of cosmetic
  extraction artifacts; a point whose quote does not reproduce is dropped. This
  guards the promise that a reader can find every quote in the document. It adds
  a per-point PDF re-download.
- **Faithfulness harness.** `who_speech/faithfulness.py` decomposes each point
  into atomic claims and labels them against the cited quote, optionally with a
  second model family, to report a faithfulness rate. Run it on a sample before
  any briefing reaches a director, and after any model swap.

## Limits (what this is not, yet)

- The demo index is shallow (a few English documents per country). Raise
  `WHO_MAX_DOCS` and widen `WHO_INDEX_LANGUAGES`, then rebuild, for real use.
- Native-language retrieval is configurable but not yet validated end to end.
- The Azure OpenAI backend is written but must be validated against a live
  deployment before production use.
