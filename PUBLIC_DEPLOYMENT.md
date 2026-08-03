# Public Deployment Guide

This guide describes how to deploy the public-safe GraphRAG reference
implementation. It does not contain any private endpoint, credential, local
dataset, or machine-specific path.

## 1. Components

```text
Browser / API client
        |
        v
GraphRAG API service
        |
        +--> indicator store mounted at runtime
        +--> optional embedding service
        +--> optional LLM gateway
        +--> optional Cross-Encoder reranker
```

The static frontend can be published through GitHub Pages. The Python API and
model services should run in a protected backend network. GitHub Pages must
not contain private indicator data or model credentials.

## 2. Local or Server Installation

Use Python 3.11 or later:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
py -3.11 -m pip install -r backend\requirements.txt
```

Start the API:

```powershell
$env:PORT = "8090"
$env:LLM_BASE_URL = "https://your-llm-gateway.example/v1"
$env:LLM_MODEL = "your-model-name"
$env:LLM_API_KEY = "runtime-secret"
py -3.11 backend\api_server.py
```

The API exposes:

- `GET /health`
- `POST /api/search`
- `GET /` for the bundled frontend

Do not place the real key in a script, notebook, frontend bundle, README, or
GitHub Actions log.

## 3. Indicator Data Deployment

Indicator data is an application input, not source code. For private data:

1. Store it in a private object store, database, or mounted volume.
2. Grant the API service a read-only identity.
3. Load or build the graph during a controlled deployment step.
4. Never commit raw JSON, CSV exports, embedding caches, or graph snapshots
   that contain private indicator content.
5. Apply access control before returning indicator definitions to a client.

For public demonstrations, use a separately approved synthetic or public data
subset under `assets/`.

At runtime, point the service to the mounted file without committing it:

```powershell
$env:INDICATOR_PATH = "data\approved-indicators.json"
$env:INDICATOR_DATA_DIR = "data"
$env:GRAPHRAG_RUNTIME_DIR = "runtime"
py -3.11 backend\api_server.py
```

The `runtime` directory contains generated triples, graph tables and optional
embedding caches. It is intentionally ignored by Git.

## 4. LLM Configuration

The LLM is used for query planning and optional explanation/reranking. It must
not invent indicators outside the configured graph. The backend should pass
only the candidate indicators retrieved from the graph to the model.

Required runtime variables:

```text
LLM_BASE_URL=https://your-llm-gateway.example/v1
LLM_MODEL=your-model-name
LLM_API_KEY=<secret>
```

When the LLM is unavailable, deterministic exact, alias, keyword, embedding,
and graph retrieval remains available.

## 5. Optional Cross-Encoder Service

The second-stage reranker is intentionally opt-in. Deploy it separately:

```powershell
$env:RERANK_MODEL = "your-approved-cross-encoder"
$env:RERANK_PORT = "8018"
py -3.11 backend\reranker_server.py
```

Configure the GraphRAG API:

```text
USE_CROSS_ENCODER_RERANK=true
CROSS_ENCODER_URL=http://your-reranker-service:8018/v1/rerank
CROSS_ENCODER_TIMEOUT=8
```

The reranker receives a query and structured indicator cards. It must only
reorder the first-stage candidates and must not create new indicator names.

## 6. GitHub Pages

The repository includes a Pages workflow under `.github/workflows/pages.yml`.

1. Enable GitHub Pages in repository settings.
2. Select GitHub Actions as the build and deployment source.
3. Push the approved public frontend and documentation branch.
4. Verify that no private data or secrets are present in the artifact.

GitHub Pages is a static host. It cannot securely protect private indicator
files or server-side API keys. Use a backend proxy for all private services.

## 7. Evaluation Before Production

Run the 100-case evaluator against a protected backend:

```powershell
$env:TEST_USE_LLM = "false"
$env:TEST_USE_CROSS_ENCODER = "false"
$env:TEST_VERSION = "baseline"
py -3.11 backend\run_api_100_tests.py
```

Then run the same cases with the reranker enabled:

```powershell
$env:TEST_USE_CROSS_ENCODER = "true"
$env:TEST_VERSION = "reranker"
py -3.11 backend\run_api_100_tests.py
```

Promote the reranker only when Top1 improves without degrading Recall@5,
short-query precision, alias precision, or category recall.

## 8. Secret and Privacy Checklist

Before pushing:

- Search for API key prefixes such as `sk-`.
- Search for private IP ranges and internal hostnames.
- Search for `C:\Users`, `/home/`, and machine-specific paths.
- Confirm `.env`, caches, test outputs, PDFs, screenshots, and private data are
  ignored.
- Review `git diff --cached` manually.
- Rotate any credential that was ever committed.

The public repository should contain code and deployment guidance only. Model
credentials, internal URLs, private indicators, and evaluation exports remain
outside GitHub.
