# Indicator GraphRAG Technical Design

## 1. Purpose

This project matches natural-language questions to indicators in an approved
indicator catalog. It does not ask an LLM to invent indicator names. Every
returned result must come from the configured indicator graph or indicator
store.

The design targets four requirements:

- natural-language and colloquial questions;
- synonym and alias matching;
- parent/child indicator relationships;
- explainable, reproducible Top-K retrieval.

## 2. Architecture

```text
Approved indicator files
        |
        v
Parse -> normalize -> extract object/property/condition
        |
        +--> indicator graph
        +--> category/community summaries
        +--> keyword index
        +--> embedding index
        |
User query
        |
        +--> normalize and route
        +--> optional LLM query planning
        |
        +--> exact and alias retrieval
        +--> keyword retrieval
        +--> embedding retrieval
        +--> graph expansion
        |
Candidate fusion and filtering
        |
Rule ranking -> optional LLM explanation
        |
Top-K indicators with definitions and graph paths
```

The browser is a client. Private indicator data, model endpoints and API keys
belong in a protected backend, never in GitHub Pages or frontend bundles.

## 3. Indicator Modeling

Each source indicator is parsed into a record containing:

```json
{
  "metric_name": "example indicator",
  "category": "example category",
  "definition": "approved statistical definition",
  "source": "approved reporting source",
  "aliases": [],
  "objects": [],
  "properties": [],
  "conditions": [],
  "value_type": "count"
}
```

The original text is retained for traceability. A separate matching form is
used for whitespace, punctuation and synonym normalization. The raw spelling
is still preserved so an exact user phrase can outrank its aliases.

## 4. Knowledge Graph

### Nodes

- `Category`: indicator category or community;
- `Metric`: approved indicator entity;
- `Alias`: synonym, abbreviation or colloquial phrase;
- `Definition`: statistical definition;
- `Source`: reporting source;
- `Object`: measured object;
- `Property`: measured property;
- `Condition`: scope or constraint;
- `Intent`: count, boolean, area, rate, source, list, and similar intents.

### Edges

```text
Category -HAS_METRIC-> Metric
Metric -PARENT_METRIC-> Metric
Metric -HAS_SUB_METRIC-> Metric
Metric -HAS_ALIAS-> Alias
Metric -HAS_DEFINITION-> Definition
Metric -HAS_SOURCE-> Source
Metric -HAS_OBJECT-> Object
Metric -HAS_PROPERTY-> Property
Metric -HAS_CONDITION-> Condition
Metric -SAME_OBJECT-> Metric
Metric -SAME_PROPERTY-> Metric
```

The graph is used for controlled expansion and explanation. It is not used to
connect every indicator to every other indicator. Expansion is limited to
parents, children, same-object metrics, same-property metrics and category
neighbors.

## 5. Query Processing

### 5.1 Normalization

The system removes conversational filler while retaining the semantic core.
It extracts likely objects, properties, conditions and query intent.

Example:

```text
Question: How many elderly people in the village have no one looking after them?
Plan: object=elderly people, condition=no caregiver, intent=count
Candidate phrase: left-behind elderly people
```

### 5.2 Query Routing

The router selects one of three modes:

- `local`: find specific indicators;
- `global`: find indicators under one category;
- `cross_category`: compare or retrieve across several categories.

Local queries optimize indicator Top1. Global queries optimize category coverage
and return a broader set of indicators.

### 5.3 LLM Query Planning

An OpenAI-compatible LLM can produce a structured query plan:

```json
{
  "objects": [],
  "properties": [],
  "conditions": [],
  "intent": "unknown",
  "categories": [],
  "candidate_phrases": [],
  "synonyms": []
}
```

The plan is retrieval evidence, not an answer. The model is not allowed to
create an indicator outside the candidate set or the graph.

## 6. Hybrid Retrieval

The first stage combines:

1. exact metric-name retrieval;
2. alias and synonym retrieval;
3. fuzzy and token coverage retrieval;
4. embedding retrieval;
5. graph relationship retrieval;
6. category routing and query-plan retrieval.

The first stage should favor recall. Ranking is performed after the candidate
set is built.

The base score is conceptually:

```text
BaseScore = lexical + coverage + embedding + graph + semantic
          + intent + query_plan + route - broad_metric_penalty
```

All score components are retained in the match reason for debugging and
offline evaluation.

## 7. Precision Rules

### Literal-first alias policy

Synonyms should recall one another without stealing the user's exact phrase:

```text
query: exact metric name -> exact metric first
query: alias -> alias metric first
query: semantic paraphrase -> semantic ranking
```

For example, equivalent terms can both be returned, but the exact input term
is ranked first.

### Short-query guard

Single-character queries are restricted to exact metric matches. This prevents
substring expansion from turning a query for a short indicator into unrelated
longer indicators.

### Definition and object guard

Shared generic words such as “number”, “area” or “processing” are not enough
to establish relevance. Object, property, condition, alias and definition
evidence must agree before a candidate receives a strong score.

## 8. Optional Second-Stage Reranker

The repository includes an adapter and a standalone service for a real
Cross-Encoder. It receives the query and structured indicator cards, then
returns scores for the first-stage candidates.

```text
Top30 candidates
      |
      v
Cross-Encoder(query, metric card)
      |
      v
Rule validation and exact-match protection
      |
      v
Top5
```

The reranker is opt-in because a generic embedding model is not equivalent to
a Cross-Encoder. It must pass the same test set before becoming the default
ranking owner.

## 9. Deployment

### API service

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
py -3.11 -m pip install -r backend\requirements.txt

$env:LLM_BASE_URL = "https://your-llm-gateway.example/v1"
$env:LLM_MODEL = "your-model-name"
$env:LLM_API_KEY = "runtime-secret"
$env:PORT = "8090"
py -3.11 backend\api_server.py
```

### Reranker service

```powershell
$env:RERANK_MODEL = "your-approved-cross-encoder"
$env:RERANK_PORT = "8018"
py -3.11 backend\reranker_server.py
```

Then configure the API process with the protected reranker URL and enable the
feature only after evaluation.

### Static frontend

The static frontend can be deployed with the included GitHub Pages workflow.
It must contain only approved public assets. Private indicators and all model
credentials must remain behind the API service.

## 10. Evaluation

Use identical test cases for baseline and experimental variants. Record:

- Top1 accuracy for local indicator queries;
- Recall@5;
- MRR@5;
- category recall;
- alias precision;
- short-query precision;
- obvious-noise rate;
- latency and model-call count.

The current reference baseline is approximately:

```text
Top1: 89.58%
Recall@5: 100%
MRR@5: 94.44%
Category recall: 96.15%
```

The reranker should only be enabled when it improves Top1 without degrading
Recall@5 or boundary-case precision.

## 11. Security Boundary

Before every public push:

- scan for API key prefixes and bearer tokens;
- scan for private IP addresses and internal hostnames;
- scan for user home directories and machine-specific paths;
- exclude `.env`, caches, logs, screenshots, PDFs, test exports and private
  indicator files;
- review the staged diff, not just the working tree.

The public repository is a deployment reference. Runtime secrets and private
data are supplied through environment variables, secret managers, or protected
storage.
