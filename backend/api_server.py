import json
import os
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from backend.query_normalizer import build_metric_terms, generate_query_candidates
except ImportError:
    from query_normalizer import build_metric_terms, generate_query_candidates


BASE_DIR = Path(__file__).resolve().parents[1]
CODE_PATH = BASE_DIR / "backend" / "indicator_graphrag_core.py"

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = os.getenv("CORS_ORIGIN", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

_load_lock = threading.Lock()
_graph_ns = None
_metric_terms = None


def load_graphrag():
    """加载图谱核心代码，去掉主文件末尾的演示和离线评估调用。"""
    global _graph_ns
    if _graph_ns is not None:
        return _graph_ns
    with _load_lock:
        if _graph_ns is not None:
            return _graph_ns
        source = CODE_PATH.read_text(encoding="utf-8")
        # embedding 服务是可选增强项；默认关闭，避免服务启动时同步等待远程向量接口。
        use_embedding = os.getenv("USE_REMOTE_EMBEDDING", "false").lower() == "true"
        source = source.replace(
            "USE_REMOTE_EMBEDDING = True",
            f"USE_REMOTE_EMBEDDING = {use_embedding}",
        )
        # Experimental opt-in. The cached bi-encoder fallback is useful for
        # comparison but is not safe as the production ranking owner.
        use_cross_encoder = os.getenv("USE_CROSS_ENCODER_RERANK", "false").lower() == "true"
        source = source.replace(
            'USE_CROSS_ENCODER_RERANK = os.getenv("USE_CROSS_ENCODER_RERANK", "false").lower() == "true"',
            f"USE_CROSS_ENCODER_RERANK = {use_cross_encoder}",
        )
        source = source.replace(
            'CROSS_ENCODER_TOP_N = int(os.getenv("CROSS_ENCODER_TOP_N", "12"))',
            f"CROSS_ENCODER_TOP_N = {int(os.getenv('CROSS_ENCODER_TOP_N', '12'))}",
        )
        demo_start = source.find("# PUBLIC_API_STOP")
        if demo_start != -1:
            source = source[:demo_start]
        namespace = {"__name__": "graphrag_backend_core"}
        exec(compile(source, str(CODE_PATH), "exec"), namespace)
        _graph_ns = namespace
    return _graph_ns


def build_answer_text(answer):
    lines = [f"问题：{answer.get('query', '')}", "", "推荐指标："]
    metrics = answer.get("matched_metrics", [])
    if not metrics:
        lines.append("暂未找到足够相关的指标，请补充对象、属性或时间范围。")
    for index, item in enumerate(metrics[:5], 1):
        categories = "、".join(item.get("categories", [])) or "未分类"
        reason = item.get("reason", "") or "候选指标与问题语义匹配"
        lines.append(f"{index}. {item.get('metric', '')}（{categories}）")
        lines.append(f"   匹配原因：{reason}")
        definitions = item.get("definitions", [])
        if definitions:
            lines.append(f"   口径：{definitions[0]}")
    if answer.get("clarification_question"):
        lines.extend(["", f"需要进一步确认：{answer['clarification_question']}"])
    return "\n".join(lines)


def get_metric_terms():
    global _metric_terms
    if _metric_terms is not None:
        return _metric_terms
    ns = load_graphrag()
    rows = []
    for metric in ns["get_all_metrics"](ns["G"]):
        detail = ns["get_metric_detail"](ns["G"], metric)
        rows.append({"metric": metric, "aliases": detail.get("aliases", [])})
    _metric_terms = build_metric_terms(rows)
    return _metric_terms


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "guizhou-graphrag",
        "llm_base_url": os.getenv("LLM_BASE_URL", "http://localhost:8000/v1"),
        "llm_model": os.getenv("LLM_MODEL", "your-model-name"),
        "cross_encoder_enabled": os.getenv("USE_CROSS_ENCODER_RERANK", "false").lower() == "true",
        "cross_encoder_url": os.getenv("CROSS_ENCODER_URL", ""),
        "graph_loaded": _graph_ns is not None,
    })


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(BASE_DIR / "assets", filename)


@app.post("/api/search")
def search():
    body = request.get_json(silent=True) or {}
    query = str(body.get("query", "")).strip()
    if not query:
        return jsonify({"error": "query 不能为空"}), 400
    try:
        top_k = max(1, min(int(body.get("top_k", 5)), 10))
        use_llm = bool(body.get("use_llm", True))
        # Preserve structural expansion for one-character entity queries.
        # The LLM planner/reranker can collapse "马" to the exact metric and
        # hide the related livestock indicators returned by the graph.
        ns = load_graphrag()
        if "use_cross_encoder" in body:
            ns["USE_CROSS_ENCODER_RERANK"] = bool(body.get("use_cross_encoder"))
        query_candidates = generate_query_candidates(query, get_metric_terms())
        selected_query = query
        if (
            len(query_candidates) > 1
            and query_candidates[1]["score"] >= 0.86
            and query_candidates[1].get("reason", "").startswith("拼音")
        ):
            selected_query = query_candidates[1]["text"]
        answer = ns["graphrag_search"](selected_query, top_k=top_k, use_llm=use_llm)
        answer["query"] = query
        answer["normalized_query"] = selected_query
        answer["query_candidates"] = query_candidates
        answer["answer_text"] = build_answer_text(answer)
        if selected_query != query:
            answer["answer_text"] = (
                f"识别为标准指标表达：{selected_query}\n\n"
                + answer["answer_text"]
            )
        answer["service"] = "python-graphrag-qwen"
        return jsonify(answer)
    except Exception as exc:
        app.logger.exception("GraphRAG search failed")
        return jsonify({"error": "检索服务暂时不可用", "detail": str(exc)}), 500


if __name__ == "__main__":
    load_graphrag()
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8090")),
        threaded=True,
    )
