# GraphRAG API Service

## Install and Run

```powershell
py -3.11 -m pip install -r backend\requirements.txt

$env:LLM_BASE_URL = "https://your-llm-gateway.example/v1"
$env:LLM_MODEL = "your-model-name"
$env:LLM_API_KEY = "set-at-runtime-only"
$env:PORT = "8090"

py -3.11 backend\api_server.py
```

The service listens on `http://127.0.0.1:8090` by default.

## API

```http
GET /health
```

```http
POST /api/search
Content-Type: application/json

{"query":"natural language question","top_k":5,"use_llm":true}
```

The response contains matched indicator names, scores, explanations,
categories, definitions, and graph paths. All returned indicators must come
from the configured indicator store.

## Optional Reranker

The repository includes `backend/reranker_server.py` for a separately hosted
Cross-Encoder. Keep it disabled until a complete model has passed the same
offline evaluation as the baseline.

```powershell
$env:RERANK_MODEL = "your-approved-reranker"
$env:RERANK_PORT = "8018"
py -3.11 backend\reranker_server.py
```

Then configure the API process with:

```powershell
$env:USE_CROSS_ENCODER_RERANK = "true"
$env:CROSS_ENCODER_URL = "http://your-reranker-service/v1/rerank"
```

## Security Rules

- Store API keys in a secret manager or process environment variables.
- Put private indicator files behind an authenticated backend.
- Do not expose internal model endpoints in frontend code or documentation.
- Do not commit `.env` files, private datasets, generated test outputs, or
  machine-specific paths.
