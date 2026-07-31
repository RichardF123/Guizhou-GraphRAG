import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests


BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "outputs"
API_URL = "http://127.0.0.1:8090/api/search"
SOURCE_CASES = OUT / "graphrag_test_cases_100_generalized.csv"
DETAIL_PATH = OUT / "api_qwen_100_test_details.csv"
SUMMARY_PATH = OUT / "api_qwen_100_test_summary.json"

SPECIAL_CASES = [
    {"id": "S01", "query": "马铃薯", "query_type": "local", "expected_metrics": "马铃薯;土豆", "expected_categories": "粮食作物"},
    {"id": "S02", "query": "马", "query_type": "local", "expected_metrics": "马", "expected_categories": ""},
    {"id": "S03", "query": "土豆有多少", "query_type": "local", "expected_metrics": "土豆;马铃薯", "expected_categories": "粮食作物"},
    {"id": "S04", "query": "村里没人照顾的老人有多少", "query_type": "local", "expected_metrics": "留守老人", "expected_categories": "人口状况"},
    {"id": "S05", "query": "生活垃圾做没做分类", "query_type": "local", "expected_metrics": "生活垃圾是否进行分类", "expected_categories": "垃圾处理"},
]


def split(value):
    if value is None or pd.isna(value):
        return []
    return [x.strip() for x in str(value).replace("；", ";").split(";") if x.strip()]


def norm(value):
    text = str(value or "")
    for ch in " \t\n\r（）(),，：:":
        text = text.replace(ch, "")
    return text


def name_hit(predicted, expected):
    p = norm(predicted)
    return any(norm(x) and (p == norm(x) or norm(x) in p or p in norm(x)) for x in expected)


def rank_of(predicted, expected):
    for index, item in enumerate(predicted, 1):
        if name_hit(item, expected):
            return index
    return None


def request_case(row):
    expected_metrics = split(row.get("expected_metrics", ""))
    expected_categories = split(row.get("expected_categories", ""))
    try:
        response = requests.post(
            API_URL,
            json={"query": str(row["query"]), "top_k": 5, "use_llm": True},
            timeout=180,
        )
        response.raise_for_status()
        answer = response.json()
        predicted_metrics = [x.get("metric", "") for x in answer.get("matched_metrics", [])]
        predicted_categories = []
        for item in answer.get("matched_metrics", []):
            for category in item.get("categories", []):
                if category and category not in predicted_categories:
                    predicted_categories.append(category)
        rank = rank_of(predicted_metrics[:5], expected_metrics)
        category_hit = bool(set(expected_categories) & set(predicted_categories)) if expected_categories else True
        return {
            "id": str(row["id"]),
            "query": str(row["query"]),
            "expected_type": str(row.get("query_type", "local")),
            "expected_metrics": ";".join(expected_metrics),
            "predicted_metrics_top5": ";".join(predicted_metrics[:5]),
            "expected_categories": ";".join(expected_categories),
            "predicted_categories": ";".join(predicted_categories[:10]),
            "metric_rank": rank or "",
            "metric_top1_hit": rank == 1,
            "metric_top5_hit": rank is not None,
            "category_hit": category_hit,
            "error": "",
        }
    except Exception as exc:
        return {
            "id": str(row["id"]), "query": str(row["query"]),
            "expected_type": str(row.get("query_type", "local")),
            "expected_metrics": ";".join(expected_metrics),
            "predicted_metrics_top5": "", "expected_categories": ";".join(expected_categories),
            "predicted_categories": "", "metric_rank": "",
            "metric_top1_hit": False, "metric_top5_hit": False,
            "category_hit": False, "error": f"{type(exc).__name__}: {exc}",
        }


def main():
    if "--recalculate" in sys.argv:
        recalculate_existing()
        return
    base = pd.read_csv(SOURCE_CASES, encoding="utf-8-sig").head(95).to_dict("records")
    cases = base + SPECIAL_CASES
    # 特殊样例放在末尾，方便在明细文件中快速定位。
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(request_case, row) for row in cases]
        details = [future.result() for future in as_completed(futures)]
    df = pd.DataFrame(details).sort_values("id", key=lambda col: col.astype(str))
    local = df[df.expected_type == "local"]
    non_local = df[df.expected_type != "local"]
    ranks = pd.to_numeric(local.metric_rank, errors="coerce")
    summary = {
        "version": "api_qwen_graphrag_100",
        "api_url": API_URL,
        "total_cases": int(len(df)),
        "local_cases": int(len(local)),
        "category_cases": int(len(non_local)),
        "top_k": 5,
        "use_llm": True,
        "local_top1_accuracy": float(local.metric_top1_hit.mean()),
        "local_recall_at_5": float(local.metric_top5_hit.mean()),
        "local_mrr_at_5": float((1 / ranks).fillna(0).mean()),
        "category_recall": float(non_local.category_hit.mean()) if len(non_local) else 0.0,
        "short_exact_hit": bool(df.loc[df.id == "S02", "metric_top1_hit"].iloc[0]),
        "potato_noise_free": "马" not in str(df.loc[df.id == "S01", "predicted_metrics_top5"].iloc[0]).split(";"),
        "request_error_count": int(df.error.fillna("").ne("").sum()),
    }
    df.to_csv(DETAIL_PATH, index=False, encoding="utf-8-sig")
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("DETAIL_PATH=", DETAIL_PATH)
    print("SUMMARY_PATH=", SUMMARY_PATH)
    print(df[df.id.str.startswith("S")][["id", "query", "predicted_metrics_top5", "metric_rank"]].to_string(index=False))


def recalculate_existing():
    """只修正评估口径，不重新调用模型。"""
    df = pd.read_csv(DETAIL_PATH, encoding="utf-8-sig")
    for index, row in df.iterrows():
        expected = split(row["expected_metrics"])
        predicted = split(row["predicted_metrics_top5"])
        rank = rank_of(predicted, expected)
        df.at[index, "metric_rank"] = rank or ""
        df.at[index, "metric_top1_hit"] = rank == 1
        df.at[index, "metric_top5_hit"] = rank is not None
    local = df[df.expected_type == "local"]
    non_local = df[df.expected_type != "local"]
    ranks = pd.to_numeric(local.metric_rank, errors="coerce")
    summary = {
        "version": "api_qwen_graphrag_100_recalculated",
        "api_url": API_URL,
        "total_cases": int(len(df)), "local_cases": int(len(local)),
        "category_cases": int(len(non_local)), "top_k": 5, "use_llm": True,
        "local_top1_accuracy": float(local.metric_top1_hit.mean()),
        "local_recall_at_5": float(local.metric_top5_hit.mean()),
        "local_mrr_at_5": float((1 / ranks).fillna(0).mean()),
        "category_recall": float(non_local.category_hit.mean()) if len(non_local) else 0.0,
        "short_exact_hit": bool(df.loc[df.id == "S02", "metric_top1_hit"].iloc[0]),
        "potato_noise_free": "马" not in str(df.loc[df.id == "S01", "predicted_metrics_top5"].iloc[0]).split(";"),
        "request_error_count": int(df.error.fillna("").ne("").sum()),
    }
    df.to_csv(DETAIL_PATH, index=False, encoding="utf-8-sig")
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(df[(df.expected_type == "local") & (~df.metric_top1_hit)][["id", "query", "expected_metrics", "predicted_metrics_top5", "metric_rank"]].to_string(index=False))


if __name__ == "__main__":
    main()
