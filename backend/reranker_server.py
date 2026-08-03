"""Small HTTP service for a real Cross-Encoder reranker.

Start after installing sentence-transformers and making the model available:
  $env:RERANK_MODEL='BAAI/bge-reranker-v2-m3'
  python backend/reranker_server.py
"""

import os
from functools import lru_cache

import numpy as np
from flask import Flask, jsonify, request

app = Flask(__name__)
MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")


@lru_cache(maxsize=1)
def load_model():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(MODEL_NAME, max_length=512)


@app.get("/health")
def health():
    return jsonify({"status": "ok", "model": MODEL_NAME, "loaded": load_model.cache_info().currsize > 0})


@app.post("/v1/rerank")
def rerank():
    body = request.get_json(silent=True) or {}
    query = str(body.get("query", "")).strip()
    documents = body.get("documents", [])
    if not query or not isinstance(documents, list):
        return jsonify({"error": "query and documents are required"}), 400
    documents = [str(item) for item in documents]
    try:
        scores = np.asarray(
            load_model().predict([(query, document) for document in documents], show_progress_bar=False),
            dtype=float,
        ).reshape(-1)
        results = [
            {"index": int(index), "relevance_score": float(score)}
            for index, score in enumerate(scores)
        ]
        results.sort(key=lambda item: item["relevance_score"], reverse=True)
        top_n = int(body.get("top_n", len(results)))
        return jsonify({"results": results[:max(1, top_n)], "model": MODEL_NAME})
    except Exception as exc:
        app.logger.exception("reranker failed")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("RERANK_PORT", "8018")),
        threaded=True,
    )
