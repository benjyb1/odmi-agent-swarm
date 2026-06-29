# WHO/Europe speech-writer: an MCP service that Copilot Studio connects to.
#
# Build from the repository root so the who_speech package copies in cleanly:
#   docker build -f who_speech/Dockerfile -t who-speech .
#
# The first model load downloads BGE-M3 + the reranker (~5 GB). Bake them into
# the image or a mounted cache for fast cold starts in production.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Minimal system libraries Docling's PDF stack expects. Extend if a document
# fails to convert in your environment.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY who_speech/requirements.txt /app/who_speech/requirements.txt
RUN pip install -r /app/who_speech/requirements.txt

COPY who_speech /app/who_speech

# Defaults for a WHO deployment. Set the AZURE_OPENAI_* secrets at runtime
# (via Key Vault / container secrets), never bake them into the image.
ENV WHO_LLM_BACKEND=azure_openai \
    WHO_INDEX_ROOT=/data/index \
    WHO_MCP_TRANSPORT=streamable-http

# The index is built by the refresh job and must survive restarts.
VOLUME ["/data/index"]

EXPOSE 8000

CMD ["python", "-m", "who_speech.server"]
