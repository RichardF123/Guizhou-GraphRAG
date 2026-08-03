# Indicator GraphRAG

This repository contains a public-safe reference implementation for matching
natural-language questions to structured indicators with a graph-enhanced
retrieval pipeline.

The repository intentionally does not contain private model endpoints, API
keys, local datasets, private test outputs, or machine-specific paths.

## Quick Start

```powershell
py -3.11 -m pip install -r backend\requirements.txt
py -3.11 backend\api_server.py
```

Open `http://127.0.0.1:8090/` and use `POST /api/search` for API access.

For architecture, data modeling, retrieval, deployment, and evaluation, see
[`PUBLIC_DEPLOYMENT.md`](PUBLIC_DEPLOYMENT.md) and the technical design in the
private working copy or your approved documentation repository.

## Configuration

Configure model access through environment variables. Never commit secrets.

```powershell
$env:LLM_BASE_URL = "https://your-llm-gateway.example/v1"
$env:LLM_MODEL = "your-model-name"
$env:LLM_API_KEY = "set-this-only-in-the-runtime-environment"
$env:PORT = "8090"
py -3.11 backend\api_server.py
```

The API falls back to deterministic local retrieval when the optional LLM is
unavailable. The Cross-Encoder reranker is experimental and disabled by
default until a complete model service has passed the offline evaluation.

## Public Data Boundary

Only data approved for public distribution should be placed under `assets/`.
Private indicator files should be mounted at runtime or loaded through an
authenticated backend. Do not add internal network addresses, credentials,
private CSV/JSON exports, generated reports, caches, or local screenshots.
