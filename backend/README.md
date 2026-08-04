# GraphRAG API Service

## Install and Run

```powershell
py -3.11 -m pip install -r backend\requirements.txt

$env:LLM_BASE_URL = "https://your-llm-gateway.example/v1"
$env:LLM_MODEL = "your-model-name"
$env:LLM_API_KEY = "set-at-runtime-only"
$env:INDICATOR_PATH = "data\approved-indicators.json"
$env:INDICATOR_DATA_DIR = "data"
$env:GRAPHRAG_RUNTIME_DIR = "runtime"
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

## Optional Voice Query

The web page includes a microphone upload action. The endpoint accepts an
audio file, transcribes it, then sends the transcript through the same typo,
Guizhou oral-language, GraphRAG, and Qwen ranking pipeline:

```http
POST /api/voice-query
Content-Type: multipart/form-data

audio=<wav-or-browser-audio-file>&top_k=5&use_llm=true
```

For an existing ASR service, configure it without exposing the URL in the
frontend:

```powershell
$env:ASR_URL = "http://your-asr-service/transcribe"
$env:ASR_HOTWORDS = "马铃薯,洋芋,玉米,包谷,甘薯,红苕"
```

Alternatively install the optional local adapter:

```powershell
py -3.11 -m pip install -r backend\requirements-speech.txt
$env:ASR_MODEL = "paraformer-zh"
$env:ASR_VAD_MODEL = "fsmn-vad"
$env:ASR_PUNC_MODEL = "ct-punc"
```

The response includes `audio_text`, `asr`, `normalized_query`, and the same
`query_candidates` and `matched_metrics` fields as text search.

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
