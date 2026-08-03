import json
import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parents[1]
CODE_PATH = BASE_DIR / "outputs" / "indicator_graphrag_semantic_optimized.py"

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = os.getenv("CORS_ORIGIN", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

_load_lock = threading.Lock()
_graph_ns = None


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
        demo_start = source.find("# 覆盖不同大类的示例")
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
        ns = load_graphrag()
        if "use_cross_encoder" in body:
            ns["USE_CROSS_ENCODER_RERANK"] = bool(body.get("use_cross_encoder"))
        answer = ns["graphrag_search"](query, top_k=top_k, use_llm=use_llm)
        answer["answer_text"] = build_answer_text(answer)
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
