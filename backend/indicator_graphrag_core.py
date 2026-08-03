# 指标知识图谱问答完整方案
# 运行方式：按顺序执行本 Notebook 的代码单元。
# 依赖安装（首次运行时取消注释）：
# %pip install pandas numpy networkx rapidfuzz requests pyvis

import csv
import json
import os
import re
import difflib
import webbrowser
from pathlib import Path
from collections import defaultdict
from functools import lru_cache

import numpy as np
import pandas as pd
import networkx as nx
import requests

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None


# =========================
# 1. 配置
# =========================

DATA_DIR = Path(os.getenv("INDICATOR_DATA_DIR", "data")).resolve()
RUNTIME_DIR = Path(os.getenv("GRAPHRAG_RUNTIME_DIR", "runtime")).resolve()
INDICATOR_PATH = os.getenv("INDICATOR_PATH", str(DATA_DIR / "indicators.json"))
TRIPLE_CSV_PATH = os.getenv("TRIPLE_CSV_PATH", str(RUNTIME_DIR / "indicator_triples.csv"))
EMBEDDING_CACHE_PATH = os.getenv("EMBEDDING_CACHE_PATH", str(RUNTIME_DIR / "metric_embeddings.npz"))
EMBEDDING_TEXT_CACHE_PATH = os.getenv("EMBEDDING_TEXT_CACHE_PATH", str(RUNTIME_DIR / "metric_embedding_texts.json"))
VISUAL_HTML_PATH = os.getenv("VISUAL_HTML_PATH", str(RUNTIME_DIR / "kg_subgraph.html"))

SYNONYM_GROUPS_PATH = os.getenv("SYNONYM_GROUPS_PATH", str(DATA_DIR / "semantic_synonym_groups.json"))
EMBEDDING_URL = os.getenv("EMBEDDING_URL", "http://localhost:8017/v1/embeddings")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "your-embedding-model")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1").rstrip("/")
LLM_URL = os.getenv("LLM_URL", LLM_BASE_URL + "/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "your-model-name")
LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or os.getenv("QWEN_API_KEY")
    or os.getenv("DEEPSEEK_API_KEY")
    or ""
).strip()

# 原始标准是 26 个大类。当前数据中出现的“其他”按配置排除。
EXCLUDED_CATEGORIES = {"classification_standard", "categories", "其他"}
EXPECTED_CATEGORY_COUNT = 26
USE_REMOTE_EMBEDDING = os.getenv("USE_REMOTE_EMBEDDING", "false").lower() == "true"
USE_LLM_RERANK = True
USE_CROSS_ENCODER_RERANK = os.getenv("USE_CROSS_ENCODER_RERANK", "false").lower() == "true"
CROSS_ENCODER_MODEL = os.getenv(
    "CROSS_ENCODER_MODEL",
    "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
)
CROSS_ENCODER_TOP_N = int(os.getenv("CROSS_ENCODER_TOP_N", "12"))
CROSS_ENCODER_WEIGHT = float(os.getenv("CROSS_ENCODER_WEIGHT", "0.62"))
CROSS_ENCODER_URL = os.getenv("CROSS_ENCODER_URL", "").strip().rstrip("/")
CROSS_ENCODER_TIMEOUT = float(os.getenv("CROSS_ENCODER_TIMEOUT", "8"))


# =========================
# 1.1 语义骨架图配置
# =========================

SEMANTIC_NODE_CSV_PATH = str(RUNTIME_DIR / "indicator_semantic_nodes.csv")
SEMANTIC_EDGE_CSV_PATH = str(RUNTIME_DIR / "indicator_semantic_edges.csv")
SEMANTIC_METRIC_CSV_PATH = str(RUNTIME_DIR / "indicator_semantic_metrics.csv")
SEMANTIC_SUMMARY_JSON_PATH = str(RUNTIME_DIR / "indicator_semantic_graph_summary.json")

PROPERTY_SUFFIXES = [
    "公共充电桩", "服务站", "工作站数", "资金来源", "路面状况", "处理设施", "管网", "水体情况",
    "基本情况", "可支配总收入", "经营收入", "纯收入", "收益", "收入", "产量", "面积",
    "户数", "人数", "人口", "个数", "数量", "总数", "总额", "台数", "套数", "床位数",
    "人次", "次数", "名称", "类型", "状况", "情况", "规模", "库容", "水系", "来源", "方式"
]

CONDITION_WORDS = [
    "户籍", "常住", "未成年", "少数民族", "留守", "残疾", "脱贫", "本年", "当年", "年末",
    "新建", "改建", "集中", "公共", "生活", "生产", "农村", "城市", "城镇", "村内",
    "行政村", "村集体", "集体", "规模", "主要", "非主要", "林下", "有实际经营活动",
    "能正常使用", "是否", "通", "接入", "畅通", "经营", "从事", "农业", "非农业",
    "机关", "企事业单位", "新能源", "固定", "电子政务外网", "光纤宽带", "5G网络"
]

BOOLEAN_PATTERNS = ["是否", "有没有", "有无", "能否", "是否有", "是否通", "是否接入", "是否完成"]

ALIASES_BY_TERM = {
    "人口": ["人数", "人"],
    "户数": ["多少户", "户数量"],
    "人数": ["多少人", "人员数"],
    "个数": ["数量", "多少个"],
    "数量": ["个数", "多少"],
    "面积": ["占地", "面积数"],
    "产量": ["产出量", "生产量"],
    "收入": ["收益", "营收"],
    "是否": ["有没有", "有无", "是否有"],
    "常住": ["住在村里", "长期居住"],
    "户籍": ["户口", "本省户籍"],
    "留守老人": ["没人照顾的老人", "留守老年人"],
    "留守儿童": ["没人照顾的小孩", "留守小孩"],
    "生活垃圾": ["垃圾", "村里垃圾"],
    "生活污水": ["污水", "村里污水"],
    "公共厕所": ["公厕"],
    "新能源电动汽车公共充电桩": ["新能源充电桩", "公共充电桩"],
}


def load_semantic_synonym_groups(path=SYNONYM_GROUPS_PATH):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        groups = payload.get("groups", []) if isinstance(payload, dict) else payload
    except Exception:
        groups = []
    cleaned = []
    for group in groups:
        if isinstance(group, list):
            values = []
            for value in group:
                value = str(value).strip()
                if value and value not in values:
                    values.append(value)
            if len(values) >= 2:
                cleaned.append(values)
    return cleaned or [["马铃薯", "土豆", "洋芋"]]


SEMANTIC_SYNONYM_GROUPS = load_semantic_synonym_groups()

QUERY_INTENT_PATTERNS = {
    "count": ["多少", "几个", "几项", "总数", "数量", "人数", "户数", "有几"],
    "boolean": ["是否", "有没有", "有无", "能否", "做没做", "完成了吗", "是不是"],
    "source": ["从哪来", "谁出", "谁负责", "来源", "资金来源", "由谁填报"],
    "area": ["面积", "多大", "亩", "平方", "占地"],
    "rate": ["比例", "比重", "率", "增速", "占比"],
    "time": ["今年", "当年", "去年", "年末", "本期", "季度", "上半年", "下半年"],
}


BROAD_METRIC_WORDS = [
    "基本情况", "人口情况", "文化、卫生情况", "产业发展", "社会保障",
    "农田水利", "经济作物", "粮食作物", "畜禽存栏", "畜禽出栏"
]



# =========================
# 2. 解析非标准 JSON 指标文件
# =========================

def read_text(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def find_matching_bracket(text, start, opening="[", closing="]"):
    """在忽略字符串内容的前提下，找到与 start 对应的结束括号。"""
    depth = 0
    quote = None
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("未找到匹配的括号，指标文件可能被截断")


def extract_quoted_strings(text):
    """提取数组中的字符串，兼容单引号、双引号和转义符。"""
    values = []
    quote = None
    escaped = False
    buf = []
    for ch in text:
        if quote is None:
            if ch in ("'", '"'):
                quote = ch
                buf = []
        else:
            if escaped:
                buf.append(ch)
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                values.append("".join(buf))
                quote = None
            else:
                buf.append(ch)
    return values


def extract_category_blocks(text):
    """提取 key: [item1, item2]，避免定义文本中的 ] 破坏正则解析。"""
    blocks = []
    key_pattern = re.compile(r"([\"'])(.*?)\1\s*:\s*\[")
    for match in key_pattern.finditer(text):
        category = match.group(2).strip()
        array_start = match.end() - 1
        array_end = find_matching_bracket(text, array_start)
        body = text[array_start + 1:array_end]
        items = extract_quoted_strings(body)
        blocks.append((category, items))
    return blocks


def split_metric_definition(text):
    """按括号外第一个冒号拆分指标名和定义。"""
    round_depth = 0
    square_depth = 0
    quote = None
    escaped = False
    for i, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "（(":
            round_depth += 1
        elif ch in "）)" and round_depth > 0:
            round_depth -= 1
        elif ch == "[":
            square_depth += 1
        elif ch == "]" and square_depth > 0:
            square_depth -= 1
        elif ch in ":：" and round_depth == 0 and square_depth == 0:
            return text[:i].strip(), text[i + 1:].strip()
    return text.strip(), ""


def is_real_sub_metric(content):
    """区分真实子指标和填报/系统/自动生成等说明性括号。"""
    excluded = [
        "由", "填报", "点击获取", "自动生成", "省级", "市级", "县级",
        "镇级", "乡级", "部门", "系统", "平台", "台账", "数据生成",
        "即：", "即:", "社区", "村居", "村（", "居（"
    ]
    # 单字括号通常是“村（居）”“村（社）”等替代表述，不是子指标。
    return len(content) >= 2 and not any(word in content for word in excluded)


def parse_metric(item):
    result = {
        "raw_text": item,
        "metric_name": "",
        "sub_metric_name": "",
        "full_metric_name": "",
        "source": "",
        "definition": "",
        "prefix": ""
    }

    item = item.strip()
    if item.startswith("其中："):
        result["prefix"] = "其中"
        item = item[3:].strip()
    elif item.startswith("其中:"):
        result["prefix"] = "其中"
        item = item[3:].strip()

    left, definition = split_metric_definition(item)
    result["definition"] = definition

    source_match = re.search(r"[（(]由(.+?)填报[）)]", left)
    if source_match:
        result["source"] = source_match.group(1).strip()

    bracket_contents = re.findall(r"[（(](.*?)[）)]", left)
    sub_metric_name = ""
    for content in bracket_contents:
        content = content.strip()
        if is_real_sub_metric(content):
            sub_metric_name = content
            break

    metric_name = re.sub(r"[（(].*?[）)]", "", left).strip()
    metric_name = re.sub(r"^其中[：:]", "", metric_name).strip()

    result["metric_name"] = metric_name
    result["sub_metric_name"] = sub_metric_name
    result["full_metric_name"] = (
        metric_name + "-" + sub_metric_name if sub_metric_name else metric_name
    )
    return result


def parse_indicator_file(path):
    text = read_text(path)
    rows = []
    category_blocks = extract_category_blocks(text)
    for category, items in category_blocks:
        if category in EXCLUDED_CATEGORIES:
            continue
        for item in items:
            metric = parse_metric(item)
            metric["category"] = category
            rows.append(metric)

    categories = sorted({row["category"] for row in rows})
    print("共解析指标数：", len(rows))
    print("共解析大类数：", len(categories))
    if len(categories) != EXPECTED_CATEGORY_COUNT:
        print("警告：当前有效大类数量不是 26，请检查原始文件或 EXCLUDED_CATEGORIES")
    return rows, categories




# =========================
# 2.1 指标语义骨架抽取
# =========================

def remove_fill_words(text):
    text = re.sub(r"^其中[：:]?", "", str(text))
    text = text.replace("本村（居）", "本村")
    text = text.replace("村（居）", "村")
    text = text.replace("（", "").replace("）", "")
    return text.strip()


def unique_values(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def extract_property(metric_name):
    metric_name = remove_fill_words(metric_name)
    if metric_name.startswith("是否"):
        return "是否"
    for suffix in sorted(PROPERTY_SUFFIXES, key=len, reverse=True):
        if metric_name.endswith(suffix) and len(metric_name) > len(suffix):
            return suffix
    if "是否" in metric_name:
        return "是否"
    if "面积" in metric_name:
        return "面积"
    if "产量" in metric_name:
        return "产量"
    if metric_name.endswith("数"):
        return "数"
    return ""


def extract_conditions(metric_name, definition):
    text = remove_fill_words(metric_name + " " + (definition or ""))
    conditions = []
    for word in CONDITION_WORDS:
        if word in text:
            conditions.append(word)
    if any(word in text for word in BOOLEAN_PATTERNS):
        conditions.append("布尔判断")
    return unique_values(conditions)


def strip_property(metric_name, prop):
    value = remove_fill_words(metric_name)
    if prop == "是否" and value.startswith("是否有"):
        value = value[3:]
    elif prop == "是否" and value.startswith("是否"):
        value = value[2:]
    elif prop and value.endswith(prop):
        value = value[: -len(prop)]
    return value.strip(" 的")


def strip_conditions(text, conditions):
    value = text
    for word in sorted(conditions, key=len, reverse=True):
        if word in {"布尔判断", "是否"}:
            continue
        value = value.replace(word, "")
    value = re.sub(r"(的|中|内|本|年末|当年|本年)+$", "", value)
    return value.strip(" 的-")


def extract_object(metric_name, prop, conditions, category):
    base = strip_property(metric_name, prop)
    object_candidate = strip_conditions(base, conditions)
    if "老人" in metric_name:
        return "老人"
    if "儿童" in metric_name:
        return "儿童"
    if "妇女" in metric_name:
        return "妇女"
    if "人口" in metric_name:
        return "人口"
    if "户数" in metric_name or "户" in metric_name:
        return "户"
    if "垃圾" in metric_name:
        return "垃圾"
    if "污水" in metric_name:
        return "污水"
    if "耕地" in metric_name:
        return "耕地"
    if "水库" in metric_name:
        return "水库"
    if "电脑" in metric_name or "计算机" in metric_name:
        return "电脑"
    if "网络" in metric_name or "宽带" in metric_name or "5G" in metric_name:
        return "网络"
    return object_candidate or base or category


def generate_aliases(metric_name, obj, prop, conditions):
    aliases = [metric_name]
    clean = remove_fill_words(metric_name)
    if prop and clean.endswith(prop):
        aliases.append(clean[: -len(prop)])
    if obj and prop and obj != prop:
        aliases.append(f"{obj}{prop}")
        aliases.append(f"{obj}有多少" if prop not in {"是否", "类型", "情况", "状况"} else f"{obj}{prop}")
    if prop == "是否":
        no_shi = re.sub(r"^是否有?", "", clean)
        if no_shi == clean:
            no_shi = clean.replace("是否", "", 1)
        aliases.extend([f"有没有{no_shi}", f"有无{no_shi}", f"{no_shi}有没有"])
    if "产业合作社数" in clean:
        aliases.append(clean.replace("产业合作社数", "合作社数"))
        aliases.append(clean.replace("产业合作社数", "合作社数量"))
    if "林下养殖其他畜禽" in clean:
        aliases.extend(["林下养的其他畜禽", "林下养其他畜禽", "其他畜禽林下养殖"])
    if clean == "行政村类型":
        aliases.extend(["这个村是什么类型", "村是什么类型", "村类型", "村子类型"])
    for term, term_aliases in ALIASES_BY_TERM.items():
        if term in clean:
            for alias in term_aliases:
                aliases.append(clean.replace(term, alias))
    for group in SEMANTIC_SYNONYM_GROUPS:
        if any(term in clean for term in group):
            aliases.extend(group)
            for term in group:
                if term in clean:
                    aliases.extend(clean.replace(term, alias) for alias in group)
    for condition in conditions:
        if condition not in {"布尔判断", "是否"} and obj:
            aliases.append(f"{condition}{obj}")

    cleaned_aliases = []
    for alias in aliases:
        alias = alias.replace("有没有有", "有没有")
        alias = alias.replace("有无有", "有无")
        alias = alias.replace("是否有有", "是否有")
        alias = alias.replace("是否是否", "是否")
        cleaned_aliases.append(alias)
    return unique_values(cleaned_aliases)


def semantic_enrich_metric(row):
    metric = row["full_metric_name"]
    prop = extract_property(metric)
    conditions = extract_conditions(metric, row.get("definition", ""))
    obj = extract_object(metric, prop, conditions, row["category"])
    aliases = generate_aliases(metric, obj, prop, conditions)
    is_broad = any(word == metric or word in metric for word in BROAD_METRIC_WORDS)
    return {
        **row,
        "object": obj,
        "property": prop,
        "conditions": conditions,
        "aliases": aliases,
        "is_boolean": prop == "是否" or "布尔判断" in conditions,
        "is_broad_metric": is_broad,
    }


def semantic_node_label(node_type, label):
    return f"{node_type}：{label}"


def semantic_plain_label(value):
    return str(value).split("：", 1)[1] if "：" in str(value) else value


def export_semantic_tables(rows, G):
    metric_rows = []
    node_rows = []
    edge_rows = []
    seen_nodes = set()

    def add_node(node_type, label, **props):
        node_id = semantic_node_label(node_type, label) if node_type != "Metric" else label
        if node_id in seen_nodes:
            return node_id
        seen_nodes.add(node_id)
        node_rows.append({
            "id": node_id,
            "type": node_type,
            "label": label,
            "category": props.get("category", ""),
            "is_boolean": props.get("is_boolean", ""),
            "is_broad_metric": props.get("is_broad_metric", ""),
            "full_text": props.get("full_text", ""),
        })
        return node_id

    for row in rows:
        metric = row["full_metric_name"]
        add_node("Category", row["category"])
        add_node("Metric", metric, category=row["category"], is_boolean=row["is_boolean"], is_broad_metric=row["is_broad_metric"])
        if row.get("object"):
            add_node("Object", row["object"])
        if row.get("property"):
            add_node("Property", row["property"])
        for condition in row.get("conditions", []):
            add_node("Condition", condition)
        for alias in row.get("aliases", []):
            if alias != metric:
                add_node("Alias", alias)
        if row.get("definition"):
            add_node("Definition", row["definition"][:180], full_text=row["definition"])
        if row.get("source"):
            add_node("Source", row["source"])

        metric_rows.append({
            "category": row["category"],
            "metric": metric,
            "metric_name": row["metric_name"],
            "sub_metric_name": row["sub_metric_name"],
            "object": row.get("object", ""),
            "property": row.get("property", ""),
            "conditions": ";".join(row.get("conditions", [])),
            "aliases": ";".join(row.get("aliases", [])),
            "is_boolean": row.get("is_boolean", False),
            "is_broad_metric": row.get("is_broad_metric", False),
            "source": row.get("source", ""),
            "definition": row.get("definition", ""),
            "raw_text": row.get("raw_text", ""),
        })

    for head, tail, data in G.edges(data=True):
        relation = data.get("relation", "")
        if relation in {
            "HAS_METRIC", "MEASURES_OBJECT", "HAS_PROPERTY", "HAS_CONDITION", "HAS_ALIAS", "ALIAS_OF",
            "HAS_DEFINITION", "HAS_SOURCE", "HAS_SUB_METRIC", "BROADER_THAN", "NARROWER_THAN",
            "SAME_OBJECT_AS", "SAME_PROPERTY_AS"
        }:
            edge_rows.append({
                "head_id": head,
                "relation": relation,
                "tail_id": tail,
                "weight": data.get("weight", 1.0),
                "evidence": data.get("evidence", ""),
            })

    def write_csv(path, fieldnames, data):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

    write_csv(SEMANTIC_METRIC_CSV_PATH, [
        "category", "metric", "metric_name", "sub_metric_name", "object", "property",
        "conditions", "aliases", "is_boolean", "is_broad_metric", "source", "definition", "raw_text"
    ], metric_rows)
    write_csv(SEMANTIC_NODE_CSV_PATH, [
        "id", "type", "label", "category", "is_boolean", "is_broad_metric", "full_text"
    ], node_rows)
    write_csv(SEMANTIC_EDGE_CSV_PATH, [
        "head_id", "relation", "tail_id", "weight", "evidence"
    ], edge_rows)

    summary = {
        "metric_count": len(metric_rows),
        "category_count": len({row["category"] for row in rows}),
        "node_count": len(node_rows),
        "edge_count": len(edge_rows),
        "outputs": {
            "metrics": SEMANTIC_METRIC_CSV_PATH,
            "nodes": SEMANTIC_NODE_CSV_PATH,
            "edges": SEMANTIC_EDGE_CSV_PATH,
        }
    }
    Path(SEMANTIC_SUMMARY_JSON_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SEMANTIC_SUMMARY_JSON_PATH).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("语义骨架图已导出：", json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if Path(INDICATOR_PATH).exists():
    rows, categories = parse_indicator_file(INDICATOR_PATH)
else:
    # The public repository contains code only. Mount approved indicator data
    # at runtime and set INDICATOR_PATH before starting the API.
    rows, categories = [], {}
rows = [semantic_enrich_metric(row) for row in rows]
print("大类：", categories)
print("示例：")
for row in rows[:5]:
    print(row)


# =========================
# 3. 构建三元组和 NetworkX 图谱
# =========================

def build_triples(rows):
    triples = []
    seen = set()

    def add(candidates, head, relation, tail, weight=1.0, evidence=""):
        if head and tail:
            candidates.append((head, relation, tail, weight, evidence))

    for row in rows:
        category = row["category"]
        full_metric = row["full_metric_name"]
        metric_name = row["metric_name"]
        candidates = []

        add(candidates, category, "HAS_METRIC", full_metric, 1.0, row["raw_text"])
        if full_metric != metric_name:
            add(candidates, full_metric, "PARENT_METRIC", metric_name, 1.0, row["raw_text"])
            add(candidates, metric_name, "HAS_SUB_METRIC", full_metric, 1.0, row["raw_text"])
            add(candidates, metric_name, "BROADER_THAN", full_metric, 0.9, "括号子指标")
            add(candidates, full_metric, "NARROWER_THAN", metric_name, 0.9, "括号子指标")
        if row["definition"]:
            add(candidates, full_metric, "HAS_DEFINITION", row["definition"], 1.0, row["raw_text"])
        if row["source"]:
            add(candidates, full_metric, "HAS_SOURCE", row["source"], 1.0, row["raw_text"])
        if row["prefix"]:
            add(candidates, full_metric, "HAS_PREFIX", row["prefix"], 1.0, row["raw_text"])

        if row.get("object"):
            add(candidates, full_metric, "MEASURES_OBJECT", semantic_node_label("Object", row["object"]), 1.0, full_metric)
        if row.get("property"):
            add(candidates, full_metric, "HAS_PROPERTY", semantic_node_label("Property", row["property"]), 1.0, full_metric)
        for condition in row.get("conditions", []):
            add(candidates, full_metric, "HAS_CONDITION", semantic_node_label("Condition", condition), 0.9, full_metric)
        for alias in row.get("aliases", []):
            if alias != full_metric:
                alias_node = semantic_node_label("Alias", alias)
                add(candidates, full_metric, "HAS_ALIAS", alias_node, 0.85, full_metric)
                add(candidates, alias_node, "ALIAS_OF", full_metric, 0.85, full_metric)

        for triple in candidates:
            key = triple[:3]
            if key not in seen:
                triples.append(triple)
                seen.add(key)

    grouped_object = defaultdict(list)
    grouped_property = defaultdict(list)
    for row in rows:
        if row.get("object"):
            grouped_object[(row["category"], row["object"])].append(row["full_metric_name"])
        if row.get("property"):
            grouped_property[(row["category"], row["property"])].append(row["full_metric_name"])

    for (category, obj), metrics in grouped_object.items():
        metrics = unique_values(metrics)
        for i, metric_a in enumerate(metrics[:50]):
            for metric_b in metrics[i + 1:min(i + 6, len(metrics))]:
                key = (metric_a, "SAME_OBJECT_AS", metric_b)
                if key not in seen:
                    triples.append((metric_a, "SAME_OBJECT_AS", metric_b, 0.55, f"同大类 {category}，同对象 {obj}"))
                    seen.add(key)

    for (category, prop), metrics in grouped_property.items():
        metrics = unique_values(metrics)
        for i, metric_a in enumerate(metrics[:50]):
            for metric_b in metrics[i + 1:min(i + 4, len(metrics))]:
                key = (metric_a, "SAME_PROPERTY_AS", metric_b)
                if key not in seen:
                    triples.append((metric_a, "SAME_PROPERTY_AS", metric_b, 0.45, f"同大类 {category}，同属性 {prop}"))
                    seen.add(key)

    return triples


def export_triples(triples, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["head", "relation", "tail", "weight", "evidence"])
        writer.writerows(triples)
    print("已导出三元组：", path)


def build_graph(triples):
    graph = nx.MultiDiGraph()
    for triple in triples:
        if len(triple) == 3:
            head, relation, tail = triple
            weight, evidence = 1.0, ""
        else:
            head, relation, tail, weight, evidence = triple
        graph.add_node(head)
        graph.add_node(tail)
        graph.add_edge(head, tail, relation=relation, weight=weight, evidence=evidence)
    return graph


triples = build_triples(rows)
export_triples(triples, TRIPLE_CSV_PATH)
G = build_graph(triples)
print("节点数：", G.number_of_nodes())
print("边数：", G.number_of_edges())
semantic_summary = export_semantic_tables(rows, G)


# =========================
# 4. 图谱详情和基础检索
# =========================

def unique_append(values, value):
    if value not in values:
        values.append(value)


def get_metric_detail(G, metric_name):
    detail = {
        "metric": metric_name,
        "categories": [],
        "definitions": [],
        "sources": [],
        "parent_metrics": [],
        "sub_metrics": [],
        "prefixes": [],
        "objects": [],
        "properties": [],
        "conditions": [],
        "aliases": [],
        "same_object_metrics": [],
        "same_property_metrics": []
    }
    if metric_name not in G:
        return detail

    for source, target, data in G.in_edges(metric_name, data=True):
        relation = data.get("relation")
        if relation == "HAS_METRIC":
            unique_append(detail["categories"], source)
        elif relation == "HAS_SUB_METRIC":
            unique_append(detail["parent_metrics"], source)
        elif relation == "ALIAS_OF":
            unique_append(detail["aliases"], semantic_plain_label(source))
        elif relation == "SAME_OBJECT_AS":
            unique_append(detail["same_object_metrics"], source)
        elif relation == "SAME_PROPERTY_AS":
            unique_append(detail["same_property_metrics"], source)

    for source, target, data in G.out_edges(metric_name, data=True):
        relation = data.get("relation")
        if relation == "HAS_DEFINITION":
            unique_append(detail["definitions"], target)
        elif relation == "HAS_SOURCE":
            unique_append(detail["sources"], target)
        elif relation == "PARENT_METRIC":
            unique_append(detail["parent_metrics"], target)
        elif relation == "HAS_SUB_METRIC":
            unique_append(detail["sub_metrics"], target)
        elif relation == "HAS_PREFIX":
            unique_append(detail["prefixes"], target)
        elif relation == "MEASURES_OBJECT":
            unique_append(detail["objects"], semantic_plain_label(target))
        elif relation == "HAS_PROPERTY":
            unique_append(detail["properties"], semantic_plain_label(target))
        elif relation == "HAS_CONDITION":
            unique_append(detail["conditions"], semantic_plain_label(target))
        elif relation == "HAS_ALIAS":
            unique_append(detail["aliases"], semantic_plain_label(target))
        elif relation == "SAME_OBJECT_AS":
            unique_append(detail["same_object_metrics"], target)
        elif relation == "SAME_PROPERTY_AS":
            unique_append(detail["same_property_metrics"], target)
    return detail

    for source, target, data in G.in_edges(metric_name, data=True):
        relation = data.get("relation")
        if relation == "HAS_METRIC":
            unique_append(detail["categories"], source)
        elif relation == "HAS_SUB_METRIC":
            unique_append(detail["parent_metrics"], source)

    for source, target, data in G.out_edges(metric_name, data=True):
        relation = data.get("relation")
        if relation == "HAS_DEFINITION":
            unique_append(detail["definitions"], target)
        elif relation == "HAS_SOURCE":
            unique_append(detail["sources"], target)
        elif relation == "PARENT_METRIC":
            unique_append(detail["parent_metrics"], target)
        elif relation == "HAS_SUB_METRIC":
            unique_append(detail["sub_metrics"], target)
        elif relation == "HAS_PREFIX":
            unique_append(detail["prefixes"], target)
    return detail


def get_all_metrics(G):
    metrics = set()
    for source, target, data in G.edges(data=True):
        if data.get("relation") == "HAS_METRIC" and source in categories:
            metrics.add(target)
    return sorted(metrics)


def build_metric_text(G, metric_name):
    detail = get_metric_detail(G, metric_name)
    parts = ["指标名称：" + metric_name]
    if detail["aliases"]:
        parts.append("常见别名：" + "、".join(detail["aliases"][:12]))
    if detail["categories"]:
        parts.append("所属大类：" + "、".join(detail["categories"]))
    if detail["objects"]:
        parts.append("统计对象：" + "、".join(detail["objects"]))
    if detail["properties"]:
        parts.append("统计属性：" + "、".join(detail["properties"]))
    if detail["conditions"]:
        parts.append("限定条件：" + "、".join(detail["conditions"]))
    if detail["definitions"]:
        parts.append("指标定义：" + "；".join(detail["definitions"]))
    if detail["sources"]:
        parts.append("填报来源：" + "、".join(detail["sources"]))
    if detail["parent_metrics"]:
        parts.append("父指标：" + "、".join(detail["parent_metrics"]))
    if detail["sub_metrics"]:
        parts.append("子指标：" + "、".join(detail["sub_metrics"]))
    return "\n".join(parts)


def fuzzy_score(query, text):
    if not query or not text:
        return 0.0
    query = normalize_semantic_synonyms(query)
    text = normalize_semantic_synonyms(text)
    if fuzz is not None:
        values = [
            fuzz.ratio(query, text),
            fuzz.partial_ratio(query, text),
            fuzz.token_set_ratio(query, text)
        ]
        score = float(max(values))
    else:
        score = difflib.SequenceMatcher(None, query, text).ratio() * 100
    if query == text:
        score = 100.0
    elif text in query:
        score = max(score, 96.0)
    elif query in text:
        score = max(score, 92.0)
    return score


def semantic_match_score(query, detail):
    """语义骨架加分：用于重排，不用于短词强召回。"""
    score = 0.0
    query = str(query)

    for alias in detail.get("aliases", []):
        if len(alias) >= 3 and (alias in query or query in alias):
            score = max(score, 0.35)

    for obj in detail.get("objects", []):
        if len(obj) >= 2 and obj in query:
            score += 0.12

    for condition in detail.get("conditions", []):
        if condition in {"布尔判断", "是否"}:
            continue
        if len(condition) >= 2 and condition in query:
            score += 0.12

    for prop in detail.get("properties", []):
        if prop == "是否" and any(word in query for word in ["是否", "有没有", "有无", "能否", "做了没有"]):
            score += 0.18
        elif len(prop) >= 2 and prop in query:
            score += 0.08

    if any(word in query for word in ["是否", "有没有", "有无", "能否", "做了没有"]) and "是否" in detail.get("properties", []):
        score += 0.12

    broad_names = ["基本情况", "人口情况", "数量", "人数", "情况", "利用情况"]
    metric_name = detail.get("metric", "")
    if metric_name in broad_names or metric_name.endswith("情况"):
        if metric_name not in query:
            score -= 0.18

    return max(0.0, min(score, 0.55))


QUERY_STOP_WORDS = [
    "我想看", "查询", "村里的", "村里", "本村", "有多少", "是多少", "多少", "有哪些",
    "包括哪些", "相关指标", "指标", "情况", "分别", "方面", "的"
]

BROAD_METRIC_NAMES = {
    "人数", "数量", "个数", "户数", "面积", "情况", "基本情况", "人口情况", "利用情况",
    "收益总额", "经营收入", "从业人员", "从业人员数"
}

# Domain synonym groups. All terms in one group represent the same concept.
# Keep the canonical term stable so query and metric text normalize identically.
def load_semantic_synonym_groups(path=SYNONYM_GROUPS_PATH):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        groups = payload.get("groups", []) if isinstance(payload, dict) else payload
    except Exception:
        groups = []
    cleaned = []
    for group in groups:
        if isinstance(group, list):
            values = []
            for value in group:
                value = str(value).strip()
                if value and value not in values:
                    values.append(value)
            if len(values) >= 2:
                cleaned.append(values)
    return cleaned or [["马铃薯", "土豆", "洋芋"]]


SEMANTIC_SYNONYM_GROUPS = load_semantic_synonym_groups()
SEMANTIC_TERM_TO_CANONICAL = {
    term: group[0]
    for group in SEMANTIC_SYNONYM_GROUPS
    for term in group
}


def normalize_semantic_synonyms(text):
    text = str(text or "")
    for term in sorted(SEMANTIC_TERM_TO_CANONICAL, key=len, reverse=True):
        text = text.replace(term, SEMANTIC_TERM_TO_CANONICAL[term])
    return text


def normalize_for_match(text):
    text = normalize_semantic_synonyms(text)
    for ch in [" ", "\t", "\n", "\r", "（", "）", "(", ")", "，", ",", "：", ":", "、", "-", "_"]:
        text = text.replace(ch, "")
    return text.strip()


def query_core_text(query):
    core = normalize_for_match(query)
    for word in sorted(QUERY_STOP_WORDS, key=len, reverse=True):
        core = core.replace(normalize_for_match(word), "")
    return core.strip()


def char_coverage_score(query, metric):
    """指标名关键字符被 query 覆盖的比例，用于保护完整指标名命中。"""
    q = normalize_for_match(query)
    m = normalize_for_match(metric)
    core = query_core_text(query)
    if not m:
        return 0.0
    if m in q or (core and core == m):
        return 1.0
    if core and (core in m or m in core):
        return 0.92
    matched = sum(1 for ch in m if ch in q)
    return matched / max(len(m), 1)


def token_coverage_score(query, metric):
    """用连续中文片段做覆盖判断，弥补纯字符覆盖对长指标的偏宽问题。"""
    q = normalize_for_match(query)
    m = normalize_for_match(metric)
    if not m:
        return 0.0
    chunks = []
    buf = ""
    for ch in m:
        buf += ch
        if len(buf) >= 2:
            chunks.append(buf)
            buf = ""
    if buf and chunks:
        chunks[-1] += buf
    elif buf:
        chunks.append(buf)
    if not chunks:
        return 0.0
    return sum(1 for chunk in chunks if chunk in q) / len(chunks)


def coverage_score(query, metric):
    char_score = char_coverage_score(query, metric)
    token_score = token_coverage_score(query, metric)
    return 0.65 * char_score + 0.35 * token_score


def broad_metric_penalty(query, metric, detail):
    normalized_metric = normalize_for_match(metric)
    normalized_query = normalize_for_match(query)
    if normalized_metric in normalized_query:
        return 0.0
    if metric in BROAD_METRIC_NAMES:
        return 0.22
    if len(normalized_metric) <= 3 and any(prop in metric for prop in ["数", "量", "人", "户"]):
        return 0.18
    if detail.get("is_broad_metric") in {True, "True", "true"}:
        return 0.12
    if metric.endswith("情况") and metric not in query:
        return 0.12
    if any(word in query for word in ["是否", "有没有", "有无", "能否", "做了没有"]):
        if "是否" not in detail.get("properties", []):
            return 0.10
    return 0.0


def query_intent_score(query, detail):
    """Match question actions to metric properties without requiring exact names."""
    query_text = normalize_semantic_synonyms(str(query or ""))
    properties = " ".join(detail.get("properties", []))
    definitions = " ".join(detail.get("definitions", []))
    searchable = properties + " " + definitions
    score = 0.0
    if any(term in query_text for term in QUERY_INTENT_PATTERNS["count"]):
        if any(term in searchable for term in ["人数", "户数", "数量", "个数", "总数", "面积"]):
            score += 0.18
    if any(term in query_text for term in QUERY_INTENT_PATTERNS["boolean"]):
        if "是否" in properties or "是否" in definitions:
            score += 0.24
        else:
            score -= 0.12
    if any(term in query_text for term in QUERY_INTENT_PATTERNS["source"]):
        if any(term in searchable for term in ["来源", "资金", "填报", "负责"]):
            score += 0.22
        else:
            score -= 0.08
    if any(term in query_text for term in QUERY_INTENT_PATTERNS["area"]):
        if any(term in searchable for term in ["面积", "亩", "平方"]):
            score += 0.18
    if any(term in query_text for term in QUERY_INTENT_PATTERNS["rate"]):
        if any(term in searchable for term in ["比例", "比重", "率", "增速"]):
            score += 0.18
    return max(-0.20, min(score, 0.45))


def has_strong_synonym_anchor(query, detail, metric):
    """Reject candidates that only share one character with a synonym query."""
    query_text = str(query or "")
    searchable = " ".join([
        str(metric or ""),
        " ".join(detail.get("aliases", [])),
        " ".join(detail.get("objects", [])),
        " ".join(detail.get("conditions", [])),
        " ".join(detail.get("definitions", [])),
    ])
    normalized_searchable = normalize_semantic_synonyms(searchable)
    for group in SEMANTIC_SYNONYM_GROUPS:
        if any(term in query_text for term in group):
            canonical = group[0]
            if canonical not in normalize_semantic_synonyms(normalized_searchable):
                return False
    return True


def _char_bigrams(text):
    text = normalize_for_match(text)
    return {text[i:i + 2] for i in range(len(text) - 1) if text[i:i + 2]}


def candidate_relevance_gate(query, metric, detail, vector_score=0.0):
    """Generic precision gate against accidental single-character matches."""
    query_norm = normalize_for_match(query_core_text(query))
    metric_norm = normalize_for_match(metric)
    if not query_norm or not metric_norm:
        return False

    # 单字指标只有在用户精确搜索该单字时才允许命中，不能从长词中拆出。
    if query_norm == metric_norm:
        return True

    searchable = [metric]
    searchable.extend(detail.get("aliases", []))
    searchable.extend(detail.get("objects", []))
    searchable.extend(detail.get("properties", []))
    searchable.extend(detail.get("conditions", []))
    searchable.extend(detail.get("definitions", []))
    searchable_norm = [normalize_for_match(value) for value in searchable if value]

    # Exact phrase or multi-character alias evidence is sufficient.
    if any(len(value) >= 2 and (value in query_norm or query_norm in value) for value in searchable_norm):
        return True

    # Require at least one shared two-character phrase for lexical candidates.
    query_bigrams = _char_bigrams(query_norm)
    candidate_bigrams = set()
    for value in searchable_norm:
        candidate_bigrams.update(_char_bigrams(value))
    if query_bigrams & candidate_bigrams:
        return True

    # Allow a purely semantic vector hit only above a conservative threshold.
    if float(vector_score or 0.0) >= 0.78:
        return True

    # A one-character or very short candidate without exact evidence is noise.
    return False


def category_route_bonus(detail, route_categories):
    categories = set(detail.get("categories", []))
    route_categories = set(route_categories or [])
    if not categories or not route_categories:
        return 0.0
    if categories & route_categories:
        return 0.10
    return -0.10


def fuzzy_search_metrics(G, query, top_k=20, threshold=35):
    results = []
    for metric in get_all_metrics(G):
        detail = get_metric_detail(G, metric)
        if not has_strong_synonym_anchor(query, detail, metric):
            continue
        if not candidate_relevance_gate(query, metric, detail):
            continue
        semantic_texts = [metric]
        # 别名可以参与字面召回；对象/属性/条件只参与后续加权，避免“人/数/数量”等短词把泛指标顶到前面。
        semantic_texts.extend(alias for alias in detail.get("aliases", []) if len(alias) >= 2)
        score = max(fuzzy_score(query, text) for text in semantic_texts if text)
        if score >= threshold:
            results.append({
                "metric": metric,
                "fuzzy_score": score / 100.0,
                "detail": detail
            })
    return sorted(results, key=lambda x: x["fuzzy_score"], reverse=True)[:top_k]


def exact_core_search_metrics(G, query, top_k=20):
    """强召回：query 去掉问法词后，完整包含指标名或别名时必须进入候选。"""
    core = query_core_text(query)
    query_norm = normalize_for_match(query)
    results = []
    if not core:
        return results
    for metric in get_all_metrics(G):
        detail = get_metric_detail(G, metric)
        if not has_strong_synonym_anchor(query, detail, metric):
            continue
        if not candidate_relevance_gate(query, metric, detail):
            continue
        metric_norm = normalize_for_match(metric)
        alias_norms = [
            normalize_for_match(alias)
            for alias in detail.get("aliases", [])
            if len(normalize_for_match(alias)) >= 3
        ]
        searchable_norms = [metric_norm] + alias_norms
        if not metric_norm or len(metric_norm) < 3:
            continue
        if any(name in query_norm or name in core or core in name for name in searchable_norms):
            results.append({
                "metric": metric,
                "fuzzy_score": 1.0,
                "vector_score": 0.0,
                "detail": detail
            })
    return sorted(results, key=lambda x: coverage_score(query, x["metric"]), reverse=True)[:top_k]


# =========================
# 5. 远程向量检索
# =========================

def embedding_from_response(data):
    values = data.get("data", data)
    if isinstance(values, dict):
        values = [values]
    if not values:
        raise ValueError("embedding 服务返回为空")
    first = values[0]
    if isinstance(first, dict):
        first = first.get("embedding")
    if not isinstance(first, list):
        raise ValueError("embedding 服务返回中没有 embedding 数组")
    return np.asarray(first, dtype=np.float32)


def embeddings_from_response(data):
    values = data.get("data", data)
    if isinstance(values, dict):
        values = [values]
    if not values:
        raise ValueError("embedding 服务返回为空")
    vectors = []
    for item in values:
        embedding = item.get("embedding") if isinstance(item, dict) else item
        if not isinstance(embedding, list):
            raise ValueError("embedding 服务返回中没有 embedding 数组")
        vectors.append(np.asarray(embedding, dtype=np.float32))
    return vectors


def get_embedding(text):
    payload = {"model": EMBEDDING_MODEL, "input": [text]}
    response = requests.post(
        EMBEDDING_URL,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=120
    )
    response.raise_for_status()
    return embedding_from_response(response.json())


def get_embeddings_batch(texts, batch_size=64):
    vectors = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        payload = {"model": EMBEDDING_MODEL, "input": batch}
        response = requests.post(
            EMBEDDING_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        vectors.extend(embeddings_from_response(response.json()))
        print(f"已生成向量：{min(start + len(batch), len(texts))}/{len(texts)}")
    return vectors


def normalize_matrix(matrix):
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-12)


def build_or_load_embedding_index(G, cache_path=EMBEDDING_CACHE_PATH):
    metrics = get_all_metrics(G)
    texts = [build_metric_text(G, metric) for metric in metrics]
    cache_path = Path(cache_path)
    text_cache_path = Path(EMBEDDING_TEXT_CACHE_PATH)

    if cache_path.exists() and text_cache_path.exists():
        try:
            cached_texts = json.loads(text_cache_path.read_text(encoding="utf-8"))
            if cached_texts == texts:
                matrix = np.load(cache_path)["embeddings"]
                return metrics, normalize_matrix(matrix)
        except Exception as exc:
            print("缓存读取失败，将重新生成：", exc)

    vectors = get_embeddings_batch(texts, batch_size=8)
    matrix = normalize_matrix(np.vstack(vectors))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, embeddings=matrix)
    text_cache_path.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    return metrics, matrix


all_metrics = get_all_metrics(G)
metric_embeddings = None
if USE_REMOTE_EMBEDDING:
    try:
        all_metrics, metric_embeddings = build_or_load_embedding_index(G)
        print("向量索引已准备：", len(all_metrics))
    except Exception as exc:
        print("向量服务不可用，当前自动降级为字面检索：", exc)


def vector_search_metrics(query, top_k=20):
    if metric_embeddings is None:
        return []
    query_vector = get_embedding(query).reshape(1, -1)
    query_vector = normalize_matrix(query_vector)[0]
    scores = np.dot(metric_embeddings, query_vector)
    indices = np.argsort(scores)[::-1][:top_k]
    return [
        {
            "metric": all_metrics[i],
            "vector_score": float(scores[i]),
            "detail": get_metric_detail(G, all_metrics[i])
        }
        for i in indices
    ]


def hybrid_search_metrics(G, query, top_k=20, fuzzy_top_k=30, vector_top_k=30):
    merged = {}
    for item in exact_core_search_metrics(G, query, top_k=20):
        merged.setdefault(item["metric"], {
            "metric": item["metric"], "fuzzy_score": 0.0,
            "vector_score": 0.0, "detail": item["detail"]
        })
        merged[item["metric"]]["fuzzy_score"] = max(merged[item["metric"]]["fuzzy_score"], item["fuzzy_score"])

    for item in fuzzy_search_metrics(G, query, fuzzy_top_k):
        merged.setdefault(item["metric"], {
            "metric": item["metric"], "fuzzy_score": 0.0,
            "vector_score": 0.0, "detail": item["detail"]
        })
        merged[item["metric"]]["fuzzy_score"] = max(merged[item["metric"]]["fuzzy_score"], item["fuzzy_score"])

    if metric_embeddings is not None:
        try:
            vector_results = vector_search_metrics(query, vector_top_k)
            for item in vector_results:
                merged.setdefault(item["metric"], {
                    "metric": item["metric"], "fuzzy_score": 0.0,
                    "vector_score": 0.0, "detail": item["detail"]
                })
                merged[item["metric"]]["vector_score"] = item["vector_score"]
        except Exception as exc:
            print("本次查询向量服务失败，使用字面检索结果：", exc)

    results = []
    for item in merged.values():
        if not candidate_relevance_gate(
            query,
            item["metric"],
            item.get("detail", {}),
            item.get("vector_score", 0.0),
        ):
            continue
        detail = item.get("detail", {})
        coverage = coverage_score(query, item["metric"])
        semantic = semantic_match_score(query, detail) / 0.55
        intent = query_intent_score(query, detail)
        penalty = broad_metric_penalty(query, item["metric"], detail)
        if metric_embeddings is None:
            # Offline/rule mode: redistribute vector weight to observable signals.
            item["score"] = (
                0.34 * item["fuzzy_score"]
                + 0.30 * coverage
                + 0.21 * semantic
                + 0.15 * intent
                - penalty
            )
        else:
            # Remote embedding mode: combine vector and structured evidence.
            item["score"] = (
                0.27 * item["fuzzy_score"]
                + 0.22 * coverage
                + 0.13 * semantic
                + 0.10 * intent
                + 0.30 * item["vector_score"]
                - penalty
            )
        item["coverage_score"] = coverage
        item["semantic_score"] = semantic
        item["intent_score"] = intent
        item["penalty_score"] = penalty
        results.append(item)
    return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]


# =========================
# 6. LLM 重排和结果解释
# =========================

def build_candidate_text(candidates):
    lines = []
    for i, item in enumerate(candidates, start=1):
        detail = item.get("detail", {})
        lines.append(
            f"候选{i}\n"
            f"指标名称：{item.get('metric', '')}\n"
            f"综合分数：{item.get('score', 0):.4f}\n"
            f"字面分数：{item.get('fuzzy_score', 0):.4f}\n"
            f"语义分数：{item.get('vector_score', 0):.4f}\n"
            f"所属大类：{'、'.join(detail.get('categories', []))}\n"
            f"定义：{'；'.join(detail.get('definitions', []))}\n"
            f"来源：{'、'.join(detail.get('sources', []))}\n"
            f"父指标：{'、'.join(detail.get('parent_metrics', []))}\n"
            f"子指标：{'、'.join(detail.get('sub_metrics', []))}"
        )
    return "\n\n".join(lines)


def call_llm(prompt):
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是严谨的指标匹配助手，只能选择候选指标。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = "Bearer " + LLM_API_KEY
    response = requests.post(LLM_URL, headers=headers, json=payload, timeout=120)
    # 部分 OpenAI 兼容服务不支持 response_format；失败时降级重试。
    if response.status_code in (400, 404, 422):
        retry_payload = dict(payload)
        retry_payload.pop("response_format", None)
        response = requests.post(
            LLM_URL,
            headers=headers,
            json=retry_payload,
            timeout=120
        )
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in content)
    return content


def extract_json(text):
    text = re.sub(r"^```json\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"^```\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        text = match.group(0)
    return json.loads(text)


def rerank_metrics_with_llm(query, candidates, top_k=5):
    if not candidates:
        return {"ranked_metrics": [], "need_clarification": True, "clarification_question": "没有找到候选指标。"}

    candidate_text = build_candidate_text(candidates)
    prompt = f"""
你是指标匹配助手。根据用户问题，从候选指标中选出最相关的指标。
规则：只能选择候选中的指标名称，不得创造名称；最多返回 {top_k} 个；score 为 0 到 1；输出合法 JSON。
请先判断每个候选是否 relevant：如果候选只与问题共享一个字、短词或数量属性，但对象、属性、条件、别名和定义都不一致，必须标记为 false 并删除。
如果问题与候选都不充分相关，ranked_metrics 返回空列表并提出澄清问题。

用户问题：{query}

候选指标：
{candidate_text}

输出格式：
{{
  "ranked_metrics": [
    {{"metric": "候选中的指标名称", "relevant": true, "score": 0.95, "reason": "匹配原因"}}
  ],
  "need_clarification": false,
  "clarification_question": ""
}}
"""
    try:
        result = extract_json(call_llm(prompt))
    except Exception as exc:
        return {
            "ranked_metrics": [],
            "need_clarification": True,
            "clarification_question": "LLM 重排失败，已保留混合检索结果。",
            "error": str(exc)
        }

    candidate_names = {x["metric"] for x in candidates}
    ranked = []
    for item in result.get("ranked_metrics", []):
        if item.get("metric") in candidate_names and item.get("relevant", True) is not False:
            item["score"] = min(max(float(item.get("score", 0)), 0.0), 1.0)
            ranked.append(item)
    # 保留强证据候选：LLM 负责近邻排序，但不能误删完整指标名或明确别名命中。
    # 这能避免模型过度过滤导致 Recall@K 下降，同时仍让模型决定普通候选的顺序。
    ranked_names = {item["metric"] for item in ranked}
    protected = []
    for candidate in candidates:
        metric = candidate["metric"]
        detail = candidate.get("detail", {})
        query_norm = normalize_for_match(query_core_text(query))
        # 定义中的明确短语也算强证据，例如“规划管控覆盖”对应“是否有合法村庄规划”。
        evidence = [metric] + detail.get("aliases", []) + detail.get("definitions", [])
        has_exact_evidence = any(
            len(normalize_for_match(value)) >= 3
            and (
                normalize_for_match(value) in query_norm
                or normalize_for_match(value) in normalize_for_match(query)
            )
            for value in evidence
            if value
        )
        metric_norm = normalize_for_match(metric)
        # 别名可能来自父指标，例如“马铃薯”会出现在“马铃薯藤”的别名中。
        # 同义指标可以保底，但不能把带额外后缀的子指标当成精确命中。
        for alias in detail.get("aliases", []):
            alias_norm = normalize_for_match(alias)
            if alias_norm and alias_norm in query_norm and alias_norm in metric_norm and metric_norm != alias_norm:
                has_exact_evidence = False
        if has_exact_evidence and metric not in ranked_names:
            protected.append({
                "metric": metric,
                "relevant": True,
                "score": min(max(float(candidate.get("score", 0.0)), 0.0), 1.0),
                "reason": "完整指标名或明确别名命中，作为保底候选保留"
            })
    result["ranked_metrics"] = (protected[:2] + ranked)[:top_k]
    return result


@lru_cache(maxsize=256)
def plan_query_with_llm(query):
    """先把自然语言问题拆成检索意图，不直接把模型生成内容当作指标答案。"""
    prompt = f"""
你是统计指标检索规划器。请分析用户问题，生成用于检索指标库的结构化线索。
只输出合法 JSON，不要解释，不要编造具体统计数据。
字段要求：
- objects：统计对象，最多 5 个
- properties：统计属性，如数量、面积、是否、来源、收入，最多 5 个
- conditions：限定条件，如生活、当年、户籍、公共，最多 8 个
- intent：count、boolean、area、source、rate、trend、list 或 unknown
- categories：可能涉及的大类，最多 3 个
- candidate_phrases：可能的指标表达，最多 8 个，只作为召回线索，不是最终答案
- synonyms：问题中的口语或同义表达，最多 8 个

用户问题：{query}

输出格式：
{{
  "objects": [], "properties": [], "conditions": [], "intent": "unknown",
  "categories": [], "candidate_phrases": [], "synonyms": []
}}
"""
    try:
        result = extract_json(call_llm(prompt))
    except Exception:
        return {}
    if not isinstance(result, dict):
        return {}
    list_fields = ["objects", "properties", "conditions", "categories", "candidate_phrases", "synonyms"]
    for field in list_fields:
        values = result.get(field, [])
        if isinstance(values, str):
            values = [values]
        result[field] = [str(value).strip() for value in values if str(value).strip()][:8]
    result["intent"] = str(result.get("intent", "unknown")).strip().lower()
    return result


def query_plan_match_score(plan, detail, metric):
    if not plan:
        return 0.0
    searchable = [metric]
    for key in ["aliases", "objects", "properties", "conditions", "definitions"]:
        searchable.extend(detail.get(key, []))
    searchable_text = normalize_semantic_synonyms(" ".join(str(x) for x in searchable))
    score = 0.0
    for key, weight in [("objects", 0.16), ("properties", 0.12), ("conditions", 0.08), ("categories", 0.06)]:
        for value in plan.get(key, []):
            if normalize_semantic_synonyms(value) in searchable_text:
                score += weight
                break
    for phrase in plan.get("candidate_phrases", []):
        phrase_norm = normalize_for_match(phrase)
        if len(phrase_norm) >= 3 and phrase_norm in normalize_for_match(" ".join(searchable)):
            score += 0.18
            break
    return min(score, 0.50)


@lru_cache(maxsize=1)
def _load_cross_encoder():
    """Load the optional second-stage reranker only when explicitly enabled."""
    if not USE_CROSS_ENCODER_RERANK:
        return None
    try:
        from sentence_transformers import CrossEncoder
        return ("cross", CrossEncoder(CROSS_ENCODER_MODEL, max_length=512, local_files_only=True))
    except Exception:
        # Offline-friendly fallback: use the already cached multilingual encoder
        # as a deterministic second-stage semantic scorer.
        try:
            from sentence_transformers import SentenceTransformer
            cache_root = Path.home() / ".cache" / "huggingface" / "hub"
            model_root = cache_root / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2" / "snapshots"
            snapshots = sorted(model_root.glob("*"))
            if snapshots:
                return ("bi", SentenceTransformer(str(snapshots[0])))
        except Exception:
            pass
        return None


def _metric_rerank_text(metric, detail):
    """Create a stable structured representation for pairwise reranking."""
    fields = [
        ("metric", metric),
        ("category", " ".join(detail.get("categories", []))),
        ("object", " ".join(detail.get("objects", []))),
        ("property", " ".join(detail.get("properties", []))),
        ("condition", " ".join(detail.get("conditions", []))),
        ("alias", " ".join(detail.get("aliases", []))),
        ("definition", " ".join(detail.get("definitions", []))),
    ]
    return "\n".join(f"{key}: {value}" for key, value in fields if value)


@lru_cache(maxsize=4096)
def _encode_cached(model, text):
    return tuple(model.encode([text], normalize_embeddings=True)[0])


def _remote_rerank_scores(query_text, documents):
    if not CROSS_ENCODER_URL:
        return None
    try:
        response = requests.post(
            CROSS_ENCODER_URL,
            json={
                "model": CROSS_ENCODER_MODEL,
                "query": query_text,
                "documents": documents,
                "top_n": len(documents),
            },
            timeout=CROSS_ENCODER_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            scores = [0.0] * len(documents)
            for item in payload["results"]:
                index = int(item.get("index", -1))
                if 0 <= index < len(scores):
                    scores[index] = float(item.get("relevance_score", item.get("score", 0.0)))
            return np.asarray(scores, dtype=float)
    except Exception:
        return None
    return None


def cross_encoder_rerank(query, candidates, top_k=20):
    """Rerank candidates with a Cross-Encoder while preserving exact-match guards."""
    if not candidates or not USE_CROSS_ENCODER_RERANK:
        return candidates
    model = None if CROSS_ENCODER_URL else _load_cross_encoder()
    if model is None and not CROSS_ENCODER_URL:
        return candidates

    raw_query_text = str(query).strip()
    query_text = query_core_text(query)
    pool = candidates[:max(top_k, CROSS_ENCODER_TOP_N)]
    pairs = [(query_text, _metric_rerank_text(item["metric"], item.get("detail", {}))) for item in pool]
    try:
        documents = [pair[1] for pair in pairs]
        raw_scores = _remote_rerank_scores(query_text, documents)
        if raw_scores is None:
            model_type, model = model
            if model_type == "cross":
                raw_scores = model.predict(pairs, show_progress_bar=False)
            else:
                query_embedding = np.asarray(_encode_cached(model, query_text), dtype=float)
                metric_embeddings_local = np.asarray(
                    [_encode_cached(model, pair[1]) for pair in pairs], dtype=float
                )
                raw_scores = np.dot(metric_embeddings_local, query_embedding)
        raw_scores = np.asarray(raw_scores, dtype=float).reshape(-1)
    except Exception:
        return candidates

    if len(raw_scores) != len(pool):
        return candidates
    low, high = float(raw_scores.min()), float(raw_scores.max())
    if high > low:
        normalized = (raw_scores - low) / (high - low)
    else:
        normalized = np.full(len(raw_scores), 0.5)

    reranked = []
    for item, ce_score in zip(pool, normalized):
        item = dict(item)
        item["cross_encoder_score"] = float(ce_score)
        item["pre_rerank_score"] = float(item.get("score", 0.0))
        item["score"] = (
            CROSS_ENCODER_WEIGHT * float(ce_score)
            + (1.0 - CROSS_ENCODER_WEIGHT) * float(item.get("score", 0.0))
        )
        item["match_reason"] = (
            item.get("match_reason", "")
            + f"; cross_encoder={float(ce_score):.3f}"
        )
        reranked.append(item)

    # Exact metric names and explicit aliases remain protected from model drift.
    query_norm = normalize_for_match(query_text)
    # Keep the user's literal spelling ahead of semantic aliases. This is
    # important when a synonym group contains both "马铃薯" and "土豆".
    literal_query_norm = re.sub(r"[ \t\n\r（）(),，,：:、\-_]", "", raw_query_text).strip()
    literal_exact = []
    semantic_exact = []
    rest = []
    for item in reranked:
        metric_norm = normalize_for_match(item["metric"])
        literal_metric_norm = re.sub(r"[ \t\n\r（）(),，,：:、\-_]", "", str(item["metric"])).strip()
        aliases = [normalize_for_match(x) for x in item.get("detail", {}).get("aliases", [])]
        is_literal_exact = literal_metric_norm == literal_query_norm
        is_exact = metric_norm == query_norm or query_norm in aliases
        if is_literal_exact:
            literal_exact.append(item)
        elif is_exact:
            semantic_exact.append(item)
        else:
            rest.append(item)
    return sorted(literal_exact, key=lambda x: x["score"], reverse=True) + sorted(
        semantic_exact, key=lambda x: x["score"], reverse=True
    ) + sorted(
        rest, key=lambda x: x["score"], reverse=True
    )


def build_final_answer(G, query, candidates, llm_result=None):
    # Keep graph expansion for one-character entity queries. LLM selection is
    # intentionally bypassed here because it tends to collapse the result to
    # the exact entity and discard related category metrics.
    if len(normalize_for_match(str(query or "").strip())) == 1:
        llm_result = None
    if USE_CROSS_ENCODER_RERANK:
        # The generative LLM may explain candidates, but the calibrated
        # second-stage scorer owns the final order when enabled.
        llm_by_metric = {
            item.get("metric"): item
            for item in (llm_result or {}).get("ranked_metrics", [])
            if item.get("metric")
        }
        selected = []
        for candidate in candidates[:5]:
            metric = candidate["metric"]
            explanation = llm_by_metric.get(metric, {})
            selected.append({
                "metric": metric,
                "score": candidate.get("score", 0.0),
                "reason": explanation.get("reason") or candidate.get("match_reason", "二阶段重排结果"),
            })
    elif llm_result and llm_result.get("ranked_metrics"):
        selected = llm_result["ranked_metrics"]
    else:
        selected = [
            {
                "metric": item["metric"],
                "score": item["score"],
                "reason": "混合检索结果（LLM 未重排或不可用）"
            }
            for item in candidates[:5]
        ]

    output = {
        "query": query,
        "need_clarification": bool(llm_result and llm_result.get("need_clarification", False)),
        "clarification_question": (llm_result or {}).get("clarification_question", ""),
        "matched_metrics": []
    }
    for item in selected:
        metric = item["metric"]
        detail = get_metric_detail(G, metric)
        paths = []
        for category in detail["categories"]:
            paths.append(f"{category} - HAS_METRIC -> {metric}")
        for parent in detail["parent_metrics"]:
            paths.append(f"{metric} - PARENT_METRIC -> {parent}")
        for child in detail["sub_metrics"]:
            paths.append(f"{metric} - HAS_SUB_METRIC -> {child}")
        output["matched_metrics"].append({
            "metric": metric,
            "score": float(item.get("score", 0)),
            "reason": item.get("reason", ""),
            "categories": detail["categories"],
            "definitions": detail["definitions"],
            "sources": detail["sources"],
            "parent_metrics": detail["parent_metrics"],
            "sub_metrics": detail["sub_metrics"],
            "matched_paths": paths
        })
    return output


def ask_metric(query, use_llm=USE_LLM_RERANK):
    candidates = hybrid_search_metrics(G, query, top_k=20)
    llm_result = rerank_metrics_with_llm(query, candidates, top_k=5) if use_llm else None
    return build_final_answer(G, query, candidates, llm_result)


def print_final_answer(answer):
    print("用户问题：", answer["query"])
    print("是否需要澄清：", answer["need_clarification"])
    if answer["clarification_question"]:
        print("澄清问题：", answer["clarification_question"])
    for item in answer["matched_metrics"]:
        print("=" * 70)
        print("指标：", item["metric"])
        print("分数：", round(item["score"], 4))
        print("原因：", item["reason"])
        print("所属大类：", item["categories"])
        print("定义：", item["definitions"])
        print("来源：", item["sources"])
        print("图谱路径：", item["matched_paths"])


# 示例查询
answer = ask_metric("村里没人照顾的老人有多少", use_llm=USE_LLM_RERANK)
print_final_answer(answer)


# =========================
# 7. 可视化
# =========================

def visualize_interactive_subgraph(G, center_node, depth=1, output_file=VISUAL_HTML_PATH):
    from pyvis.network import Network

    if center_node not in G:
        raise ValueError("节点不存在：" + str(center_node))
    nodes = {center_node}
    layer = {center_node}
    for _ in range(depth):
        next_layer = set()
        for node in layer:
            next_layer.update(G.successors(node))
            next_layer.update(G.predecessors(node))
        nodes.update(next_layer)
        layer = next_layer

    sub_graph = G.subgraph(nodes).copy()
    net = Network(height="750px", width="100%", directed=True,
                  notebook=False, bgcolor="#ffffff", font_color="#333333",
                  cdn_resources="in_line")
    net.barnes_hut()
    for node in sub_graph.nodes:
        net.add_node(str(node), label=str(node), title=str(node),
                     color="#ff6b6b" if node == center_node else "#74b9ff")
    for source, target, data in sub_graph.edges(data=True):
        relation = data.get("relation", "")
        net.add_edge(str(source), str(target), label=relation, title=relation)
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    html = net.generate_html(notebook=False)
    output_file.write_text(html, encoding="utf-8")
    print("可视化文件：", output_file)
    return str(output_file)


# 使用示例：
# visualize_interactive_subgraph(G, "人口状况", depth=1)


# =========================
# 8. 效果评估
# =========================

eval_cases = [
    {"query": "村里没人照顾的老人有多少", "expected_metrics": ["留守老人"]},
    {"query": "村里的户籍人口是多少", "expected_metrics": ["户籍人口"]},
    {"query": "常住在村里的人口数", "expected_metrics": ["常住人口"]},
    {"query": "村里有多少未成年人", "expected_metrics": ["未成年人口"]},
    {"query": "村里残疾人数量", "expected_metrics": ["残疾人口数"]}
]


def normalized_name(name):
    name = str(name).strip()
    name = re.sub(r"[-_](点击获取.*|由.*填报)$", "", name)
    return name


def is_metric_hit(predicted, expected_metrics):
    predicted = normalized_name(predicted)
    return any(
        predicted == normalized_name(expected)
        or normalized_name(expected) in predicted
        or predicted in normalized_name(expected)
        for expected in expected_metrics
    )


def evaluate_retrieval(eval_cases, top_k=5):
    details = []
    top1 = 0
    topk = 0
    reciprocal_rank_sum = 0.0
    for case in eval_cases:
        results = hybrid_search_metrics(G, case["query"], top_k=top_k)
        predicted = [item["metric"] for item in results]
        rank = next((i + 1 for i, name in enumerate(predicted) if is_metric_hit(name, case["expected_metrics"])), None)
        hit1 = rank == 1
        hitk = rank is not None
        top1 += int(hit1)
        topk += int(hitk)
        reciprocal_rank_sum += 1.0 / rank if rank else 0.0
        details.append({
            "query": case["query"],
            "expected": case["expected_metrics"],
            "predicted": predicted,
            "rank": rank,
            "top1_hit": hit1,
            "topk_hit": hitk
        })
    total = len(eval_cases)
    return {
        "total": total,
        "top1_accuracy": top1 / total if total else 0.0,
        "recall_at_k": topk / total if total else 0.0,
        "mrr": reciprocal_rank_sum / total if total else 0.0,
        "details": details
    }


def evaluate_end_to_end(eval_cases, top_k=5, use_llm=False):
    details = []
    top1 = 0
    topk = 0
    reciprocal_rank_sum = 0.0
    for case in eval_cases:
        answer = ask_metric(case["query"], use_llm=use_llm)
        predicted = [item["metric"] for item in answer["matched_metrics"][:top_k]]
        rank = next((i + 1 for i, name in enumerate(predicted) if is_metric_hit(name, case["expected_metrics"])), None)
        top1 += int(rank == 1)
        topk += int(rank is not None)
        reciprocal_rank_sum += 1.0 / rank if rank else 0.0
        details.append({
            "query": case["query"],
            "expected": case["expected_metrics"],
            "predicted": predicted,
            "rank": rank,
            "top1_hit": rank == 1,
            "topk_hit": rank is not None
        })
    total = len(eval_cases)
    return {
        "total": total,
        "top1_accuracy": top1 / total if total else 0.0,
        "recall_at_k": topk / total if total else 0.0,
        "mrr": reciprocal_rank_sum / total if total else 0.0,
        "details": details
    }


retrieval_summary = evaluate_retrieval(eval_cases, top_k=5)
print(json.dumps(retrieval_summary, ensure_ascii=False, indent=2))

# 远程 LLM 可用时再打开；否则保留混合检索评估。
# end_to_end_summary = evaluate_end_to_end(eval_cases, top_k=5, use_llm=True)
# print(json.dumps(end_to_end_summary, ensure_ascii=False, indent=2))


def save_evaluation(summary, path=None):
    path = path or str(RUNTIME_DIR / "evaluation_summary.json")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("评估结果已保存：", path)


if os.getenv("RUN_OFFLINE_EVAL", "false").lower() == "true":
    save_evaluation(retrieval_summary)


# ============================================================
# 9. GraphRAG 升级：覆盖全部有效大类
# ============================================================
# 这里的社区不是只针对“人口状况”，而是由当前指标库中的全部有效大类动态生成。
# “其他”已在前面的解析阶段排除，“其他主要畜禽”等合法大类会正常保留。

from collections import defaultdict


def unique_values(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def build_graphrag_store(rows, G):
    """将图谱转换成 GraphRAG 所需的 text units、communities 和 reports。"""
    text_units = []
    category_metrics = defaultdict(list)
    aliases = defaultdict(list)

    for index, row in enumerate(rows, start=1):
        metric = row["full_metric_name"]
        category = row["category"]
        category_metrics[category].append(metric)
        text_units.append({
            "id": f"tu_{index:05d}",
            "metric": metric,
            "category": category,
            "text": build_metric_text(G, metric),
            "raw_text": row["raw_text"],
            "definition": row["definition"],
            "source": row["source"]
        })

        # 生成稳定别名：来自语义骨架图，同时保留少量通用后缀规则。
        detail = get_metric_detail(G, metric)
        alias_candidates = [metric]
        alias_candidates.extend(detail.get("aliases", []))
        for suffix in ["数量", "数", "总数"]:
            if metric.endswith(suffix) and len(metric) > len(suffix) + 1:
                alias_candidates.append(metric[:-len(suffix)])
        if "人口" in metric:
            alias_candidates.append(metric.replace("人口", "人群"))
        aliases[metric] = unique_values(alias_candidates)

    community_reports = {}
    for category in sorted(category_metrics):
        metrics = unique_values(category_metrics[category])
        preview = "、".join(metrics[:20])
        if len(metrics) > 20:
            preview += "等"
        community_reports[category] = {
            "community_id": "community_" + str(len(community_reports) + 1).zfill(3),
            "category": category,
            "metric_count": len(metrics),
            "metrics": metrics,
            "summary": f"{category}大类共包含{len(metrics)}个指标，主要包括：{preview}。"
        }

    return {
        "text_units": text_units,
        "category_metrics": {k: unique_values(v) for k, v in category_metrics.items()},
        "community_reports": community_reports,
        "aliases": dict(aliases)
    }


GRAPHRAG_STORE = build_graphrag_store(rows, G)
print("GraphRAG 社区数：", len(GRAPHRAG_STORE["community_reports"]))
print("GraphRAG 文本单元数：", len(GRAPHRAG_STORE["text_units"]))


CATEGORY_ALIASES = {
    "基本情况": ["基础信息", "基本信息", "村子概况", "村庄概况", "行政属性", "最基础的信息", "基础情况"],
    "村庄建设": ["硬件建设", "基础设施", "道路", "主路", "路面", "公厕", "公共厕所", "村内建设", "路啊厕所"],
    "人口状况": ["人口", "人多不多", "住了多少人", "户籍", "常住人口", "人口户数", "户数人口"],
    "房屋建筑": ["房子", "住房", "住宅", "村民住房", "卫生厕所", "公共卫生厕所", "住建"],
    "耕地面积": ["土地", "耕地", "耕地变化", "耕地增减", "新增耕地", "减少耕地", "退耕还林"],
    "农田水利": ["农田", "水利", "灌溉", "水源", "机电井", "农田灌溉"],
    "垃圾处理": ["垃圾", "生活垃圾", "垃圾收集", "垃圾分类", "收运处理", "垃圾治理"],
    "污水处理": ["污水", "生活污水", "排水", "雨水排放", "污水治理", "污水管控"],
    "巩固脱贫攻坚成效": ["脱贫", "脱贫成果", "脱贫巩固", "三变改革", "资源变资产", "资金变股金", "农民变股东"],
    "经济发展": ["农业经营", "经营规模户", "规模户", "休闲农业", "乡村旅游", "产业经营"],
    "粮食作物": ["种粮", "粮食", "谷物", "稻谷", "小麦", "玉米"],
    "经济作物": ["油料", "油菜籽", "胡麻籽", "棉花", "蔬菜", "经济作物"],
    "畜牧业": ["畜牧", "畜禽", "存栏", "牛羊猪", "猪牛羊", "奶牛", "山羊"],
    "主要畜禽": ["主要畜禽", "鸡鸭", "蛋鸡", "肉鸡", "鸡的情况", "鸡产业合作社"],
    "非主要畜禽": ["非主要畜禽", "其他畜禽", "不是主要畜禽", "林下养殖其他畜禽"],
    "渔业": ["渔业", "水产", "水产养殖", "苗种繁育", "渔业人员"],
    "产业发展": ["合作社", "专业合作社", "农民专业合作社", "农业企业", "产业发展"],
    "集体经济": ["集体经济", "村集体", "集体收入", "分红", "纯收入", "经营收入"],
    "林下经济": ["林下经济", "林下种养", "林下产业", "林下经营", "树林下面"],
    "林下种植": ["林下种植", "林下种菜", "林下种药材", "中药材", "林下作物"],
    "林下养殖": ["林下养殖", "林下养鸡", "林下养畜", "树林下面搞养殖"],
    "社会发展": ["社会发展", "社会服务", "公共服务", "文化卫生保障教育", "社会类"],
    "社会保障": ["社会保障", "社保", "低保", "养老保险", "保障"],
    "教育状况": ["教育", "学校", "小学", "老师", "教师", "学生"],
    "文化卫生": ["文化卫生", "图书室", "健身场所", "公共文化", "卫生室", "文化设施"],
    "电脑配置暨网络畅通情况": ["电脑", "网络", "宽带", "光纤", "5G", "上网", "网络畅通", "电子政务外网"],
}

CROSS_CATEGORY_WORDS = ["和", "与", "及", "以及", "加", "同时", "一起", "分别", "都要", "对比", "两个方向", "两块", "这俩"]


def category_alias_hits(query):
    hits = []
    for category in categories:
        terms = [category] + CATEGORY_ALIASES.get(category, [])
        if any(term and term in query for term in terms):
            hits.append(category)
    return unique_values(hits)


def append_parent_categories(category_list):
    result = unique_values(category_list)
    result_set = set(result)
    if {"林下种植", "林下养殖"} & result_set and "林下经济" not in result_set:
        result.insert(0, "林下经济")
    if {"畜牧业", "主要畜禽", "非主要畜禽"} & result_set and "畜牧业" not in result_set:
        result.insert(0, "畜牧业")
    return unique_values(result)


def save_graphrag_artifacts(store, output_dir=None):
    """导出 GraphRAG 索引，便于后续接入服务或数据库。"""
    output_dir = Path(output_dir or (RUNTIME_DIR / "graphrag_index"))
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(output_dir / "text_units.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "metric", "category", "text", "raw_text", "definition", "source"])
        writer.writeheader()
        writer.writerows(store["text_units"])

    with open(output_dir / "communities.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["community_id", "category", "metric_count", "metrics", "summary"])
        writer.writeheader()
        for report in store["community_reports"].values():
            row = dict(report)
            row["metrics"] = "、".join(row["metrics"])
            writer.writerow(row)

    (output_dir / "community_reports.json").write_text(
        json.dumps(store["community_reports"], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    (output_dir / "aliases.json").write_text(
        json.dumps(store["aliases"], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print("GraphRAG 索引已导出：", output_dir)


save_graphrag_artifacts(GRAPHRAG_STORE)


def rank_communities(query, top_k=5):
    """对全部大类社区排序，不写死任何具体大类。"""
    results = []
    for category, report in GRAPHRAG_STORE["community_reports"].items():
        searchable_text = category + " " + report["summary"] + " " + " ".join(report["metrics"][:30])
        score = fuzzy_score(query, searchable_text) / 100.0
        if category in query:
            score = max(score, 0.98)
        alias_matches = [alias for alias in CATEGORY_ALIASES.get(category, []) if alias in query]
        if alias_matches:
            score = max(score, 0.90 + min(len(alias_matches), 3) * 0.025)
        results.append({
            "category": category,
            "score": score,
            "summary": report["summary"],
            "metric_count": report["metric_count"],
            "metrics": report["metrics"]
        })
    return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]


def route_graphrag_query(query):
    """判断 local、global 或 cross_category 查询。"""
    global_words = [
        "哪些", "有哪些", "包括", "包含", "方面", "分类", "类别", "相关指标", "指标有",
        "指标给我列", "列下", "列一下", "有什么可查", "可查的", "都有什么字段", "都有哪些"
    ]
    local_words = [
        "是否", "有没有", "有无", "能否", "做了没有", "做没做", "有没有做", "完成了吗",
        "是不是", "我想看", "查询", "多少", "有多少", "是多少"
    ]
    compare_words = ["比较", "对比", "区别", "差异", "分别", "两个方向", "两块", "这俩"]
    exact_categories = [category for category in categories if category in query]
    mentioned_categories = category_alias_hits(query)
    has_local_signal = any(word in query for word in local_words)
    has_cross_word = any(word in query for word in CROSS_CATEGORY_WORDS if word != "和")
    has_cross_word = has_cross_word or ("和" in query and not has_local_signal)

    if len(exact_categories) >= 2 or (
        len(mentioned_categories) >= 2 and (has_cross_word or any(word in query for word in compare_words))
    ):
        query_type = "cross_category"
    elif has_cross_word and any(word in query for word in global_words + ["看看", "查查", "找", "分析"]):
        query_type = "cross_category"
    elif has_local_signal:
        query_type = "local"
    elif any(word in query for word in global_words) and not any(word in query for word in ["多少", "数量", "数"]):
        query_type = "global"
    else:
        query_type = "local"

    if mentioned_categories:
        selected_categories = append_parent_categories(mentioned_categories)
    else:
        selected_categories = [item["category"] for item in rank_communities(query, top_k=5)]
        selected_categories = append_parent_categories(selected_categories)

    return {
        "query": query,
        "query_type": query_type,
        "categories": selected_categories,
        "reason": "命中大类名称或口语别名" if mentioned_categories else "根据大类摘要和指标名称推断"
    }


def local_graphrag_search(query, top_k=20, route_categories=None, query_plan=None):
    """局部 GraphRAG：候选指标召回后扩展父子指标和同大类邻居。"""
    # 单字查询必须先锁定精确实体，再沿实体所属大类扩展聚合指标。
    # 不能把单字直接当作普通子串检索，否则“马”会误命中“马铃薯”等无关指标。
    short_query = normalize_for_match(query_core_text(query))
    if len(short_query) == 1:
        exact_short = []
        for metric in get_all_metrics(G):
            if normalize_for_match(metric) != short_query:
                continue
            detail = get_metric_detail(G, metric)
            exact_short.append({
                "metric": metric,
                "fuzzy_score": 1.0,
                "vector_score": 0.0,
                "graph_score": 1.0,
                "semantic_score": 1.0,
                "coverage_score": 1.0,
                "intent_score": query_intent_score(query, detail),
                "route_score": 0.0,
                "penalty_score": 0.0,
                "graph_relation": "单字精确命中",
                "detail": detail,
                "score": 1.0,
                "match_reason": "单字指标精确命中，未扩展相邻指标"
            })
        if not exact_short:
            return []

        # 以精确实体所属大类为边界，补充该领域常用的汇总、存量、流量和组织类指标。
        # 这些词是结构关系过滤器，不是对用户场景的硬编码；适用于畜牧、种植、渔业等大类。
        aggregate_terms = (
            "总", "数量", "人数", "面积", "产量", "产值", "存栏", "出栏", "产出",
            "养殖", "种植", "经营", "合作社", "牲畜", "畜禽", "产品", "其他"
        )
        expanded = list(exact_short)
        expanded_metrics = {item["metric"] for item in expanded}
        for anchor in exact_short:
            anchor_detail = anchor["detail"]
            for category in anchor_detail.get("categories", []):
                for metric in GRAPHRAG_STORE["category_metrics"].get(category, []):
                    if metric in expanded_metrics or metric not in get_all_metrics(G):
                        continue
                    detail = get_metric_detail(G, metric)
                    metric_text = " ".join([
                        str(metric),
                        " ".join(detail.get("aliases", [])),
                        " ".join(detail.get("properties", [])),
                    ])
                    # 单字只允许通过图谱关系进入扩展；二次过滤要求指标具有领域聚合含义。
                    if not any(term in metric_text for term in aggregate_terms):
                        continue
                    expanded.append({
                        "metric": metric,
                        "fuzzy_score": 0.0,
                        "vector_score": 0.0,
                        "graph_score": 0.55,
                        "semantic_score": 0.45,
                        "coverage_score": 0.0,
                        "intent_score": query_intent_score(query, detail),
                        "route_score": 0.0,
                        "penalty_score": broad_metric_penalty(query, metric, detail),
                        "graph_relation": f"同大类扩展：{category}",
                        "detail": detail,
                        "score": 0.30,
                        "match_reason": f"精确实体“{anchor['metric']}”所属大类“{category}”的结构化关联指标"
                    })
                    expanded_metrics.add(metric)

        return expanded[:top_k]

    exact_results = exact_core_search_metrics(G, query, top_k=50)
    hybrid_results = hybrid_search_metrics(G, query, top_k=30, fuzzy_top_k=40, vector_top_k=40)
    planned_results = []
    if query_plan:
        plan_terms = query_plan.get("candidate_phrases", []) + query_plan.get("objects", [])
        for term in plan_terms[:12]:
            if len(normalize_for_match(term)) >= 2:
                planned_results.extend(exact_core_search_metrics(G, term, top_k=10))
    base_results = []
    seen_base = set()
    for item in exact_results + planned_results + hybrid_results:
        if item["metric"] not in seen_base:
            base_results.append(item)
            seen_base.add(item["metric"])
    base_by_metric = {item["metric"]: item for item in base_results}
    candidates = {}

    def add_candidate(metric, graph_score, relation):
        if metric not in get_all_metrics(G):
            return
        detail = get_metric_detail(G, metric)
        base = base_by_metric.get(metric, {})
        fuzzy_value = base.get("fuzzy_score", fuzzy_score(query, metric) / 100.0)
        vector_value = base.get("vector_score", 0.0)
        if not candidate_relevance_gate(query, metric, detail, vector_value):
            return
        coverage_value = coverage_score(query, metric)
        intent_value = query_intent_score(query, detail)
        plan_value = query_plan_match_score(query_plan, detail, metric)
        route_value = category_route_bonus(detail, route_categories)
        penalty_value = broad_metric_penalty(query, metric, detail)
        candidates[metric] = {
            "metric": metric,
            "fuzzy_score": float(fuzzy_value),
            "vector_score": float(vector_value),
            "graph_score": max(graph_score, candidates.get(metric, {}).get("graph_score", 0.0)),
            "semantic_score": semantic_match_score(query, detail),
            "coverage_score": float(coverage_value),
            "intent_score": float(intent_value),
            "plan_score": float(plan_value),
            "route_score": float(route_value),
            "penalty_score": float(penalty_value),
            "graph_relation": relation,
            "detail": detail
        }

    for item in base_results[:15]:
        add_candidate(item["metric"], 1.0, "直接召回")
        detail = item["detail"]
        for parent in detail.get("parent_metrics", []):
            add_candidate(parent, 0.85, "父指标扩展")
        for child in detail.get("sub_metrics", []):
            add_candidate(child, 0.85, "子指标扩展")
        for sibling in detail.get("same_object_metrics", [])[:20]:
            add_candidate(sibling, 0.55, "同对象扩展")
        for sibling in detail.get("same_property_metrics", [])[:20]:
            add_candidate(sibling, 0.45, "同属性扩展")
        for category in detail.get("categories", []):
            for sibling in GRAPHRAG_STORE["category_metrics"].get(category, [])[:50]:
                add_candidate(sibling, 0.35, "同大类扩展")

    for item in candidates.values():
        if metric_embeddings is not None:
            item["score"] = (
                0.20 * item["fuzzy_score"]
                + 0.25 * item["coverage_score"]
                + 0.25 * item["vector_score"]
                + 0.15 * item["graph_score"]
                + 0.10 * item["semantic_score"]
                + 0.08 * item["intent_score"]
                + 0.10 * item["plan_score"]
                + item["route_score"]
                - item["penalty_score"]
            )
        else:
            item["score"] = (
                0.35 * item["fuzzy_score"]
                + 0.30 * item["coverage_score"]
                + 0.16 * item["graph_score"]
                + 0.09 * item["semantic_score"]
                + 0.08 * item["intent_score"]
                + 0.10 * item["plan_score"]
                + item["route_score"]
                - item["penalty_score"]
            )

        # Reward strong coverage, but avoid allowing a short generic metric
        # to dominate a more specific candidate solely by substring overlap.
        metric_length = len(normalize_for_match(item["metric"]))
        query_length = max(len(normalize_for_match(query_core_text(query))), 1)
        if item["coverage_score"] >= 0.92 and metric_length >= max(2, query_length * 0.45):
            item["score"] += 0.10
        elif item["coverage_score"] >= 0.80 and metric_length >= 3:
            item["score"] += 0.05

        item["match_reason"] = (
            f"字面={item['fuzzy_score']:.2f}；"
            f"覆盖={item['coverage_score']:.2f}；"
            f"语义={item['vector_score']:.2f}；"
            f"骨架={item['semantic_score']:.2f}；"
            f"规划={item['plan_score']:.2f}；"
            f"路由={item['route_score']:.2f}；"
            f"惩罚={item['penalty_score']:.2f}；"
            f"图谱关系={item['graph_relation']}"
        )

    ranked_candidates = sorted(candidates.values(), key=lambda x: x["score"], reverse=True)

    # Literal metric names outrank semantic aliases in the base ranker too.
    # Otherwise "马铃薯" can incorrectly place the alias "土豆" first when
    # the experimental second-stage reranker is disabled.
    literal_query = re.sub(r"[ \t\n\r（）(),，,：:、\-_]", "", str(query)).strip()
    literal_hits = []
    non_literal = []
    for item in ranked_candidates:
        literal_metric = re.sub(
            r"[ \t\n\r（）(),，,：:、\-_]", "", str(item["metric"])
        ).strip()
        if literal_query and literal_metric == literal_query:
            literal_hits.append(item)
        else:
            non_literal.append(item)
    return (literal_hits + non_literal)[:top_k]


def global_graphrag_search(query, top_k=3):
    """全局 GraphRAG：从全部 26 个社区报告中选择相关大类。"""
    return rank_communities(query, top_k=top_k)


def merge_route_and_ranked_communities(query, route_categories, top_k=5):
    ranked = rank_communities(query, top_k=max(top_k, 8))
    ranked_by_category = {item["category"]: item for item in ranked}
    merged = []

    for category in append_parent_categories(route_categories or []):
        report = GRAPHRAG_STORE["community_reports"].get(category)
        if not report:
            continue
        base = ranked_by_category.get(category, {})
        merged.append({
            "category": category,
            "score": max(float(base.get("score", 0.0)), 0.96),
            "summary": report["summary"],
            "metric_count": report["metric_count"],
            "metrics": report["metrics"],
        })

    for item in ranked:
        if item["category"] not in {x["category"] for x in merged}:
            merged.append(item)
        if len(merged) >= top_k:
            break

    return merged[:top_k]


def build_global_answer(query, community_results):
    matched_metrics = []
    for community in community_results:
        for metric in community["metrics"][:10]:
            detail = get_metric_detail(G, metric)
            matched_metrics.append({
                "metric": metric,
                "score": community["score"],
                "reason": "命中大类社区：" + community["category"],
                "categories": detail["categories"],
                "definitions": detail["definitions"],
                "sources": detail["sources"],
                "parent_metrics": detail["parent_metrics"],
                "sub_metrics": detail["sub_metrics"],
                "matched_paths": [f"{community['category']} - HAS_METRIC -> {metric}"]
            })
    return {
        "query": query,
        "retrieval_mode": "global",
        "matched_categories": community_results,
        "matched_metrics": matched_metrics,
        "need_clarification": False,
        "clarification_question": ""
    }


def graphrag_search(query, top_k=5, use_llm=USE_LLM_RERANK):
    """统一入口：自动选择局部、全局或跨大类检索。"""
    route = route_graphrag_query(query)
    if route["query_type"] == "local":
        # 大类别名主要服务 global/cross 路由；local 排序若强吃别名，会把“畜禽养殖规模户”等跨业务词带偏。
        query_plan = plan_query_with_llm(query) if use_llm else {}
        candidates = local_graphrag_search(query, top_k=30, route_categories=[], query_plan=query_plan)
        candidates = cross_encoder_rerank(query, candidates, top_k=30)
        # Single-character entity queries use protected graph expansion. The LLM
        # reranker may keep only the exact entity and accidentally drop its
        # same-category aggregate metrics.
        is_single_entity = len(normalize_for_match(str(query or "").strip())) == 1
        llm_result = (
            None
            if is_single_entity
            else (rerank_metrics_with_llm(query, candidates, top_k=top_k) if use_llm else None)
        )
        answer = build_final_answer(G, query, candidates, llm_result)
        answer["retrieval_mode"] = "local"
        answer["route"] = route
        answer["query_plan"] = query_plan
        return answer

    community_results = merge_route_and_ranked_communities(query, route.get("categories", []), top_k=5)
    answer = build_global_answer(query, community_results)
    answer["retrieval_mode"] = route["query_type"]
    answer["route"] = route
    return answer


# PUBLIC_API_STOP
def print_graphrag_answer(answer):
    print("问题：", answer["query"])
    print("检索模式：", answer["retrieval_mode"])
    print("路由：", answer.get("route", {}))
    if answer.get("matched_categories"):
        print("命中社区：")
        for item in answer["matched_categories"]:
            print("  ", item["category"], round(item["score"], 4), item["summary"])
    print("匹配指标：")
    for item in answer.get("matched_metrics", [])[:10]:
        print("  ", item["metric"], round(item["score"], 4), item["reason"])


# 覆盖不同大类的示例，不只测试人口状况。
graphrag_examples = [
    "村里没人照顾的老人有多少",
    "村里的耕地面积有哪些指标",
    "农村水利设施包括哪些指标",
    "村庄文化卫生方面有哪些指标",
    "产业发展和经济发展有哪些相关指标"
]

for example_query in graphrag_examples:
    print("=" * 80)
    print_graphrag_answer(graphrag_search(example_query, top_k=5, use_llm=False))


# =========================
# 10. GraphRAG 多大类评估
# =========================

graphrag_eval_cases = [
    {"query": "村里没人照顾的老人有多少", "type": "local", "expected_metrics": ["留守老人"]},
    {"query": "村里的户籍人口是多少", "type": "local", "expected_metrics": ["户籍人口"]},
    {"query": "村里的耕地面积有哪些指标", "type": "global", "expected_categories": ["耕地面积"]},
    {"query": "农村水利设施包括哪些指标", "type": "global", "expected_categories": ["农田水利"]},
    {"query": "村庄文化卫生方面有哪些指标", "type": "global", "expected_categories": ["文化卫生"]},
    {"query": "产业发展和经济发展有哪些相关指标", "type": "cross_category", "expected_categories": ["产业发展", "经济发展"]}
]


def evaluate_graphrag(cases):
    details = []
    category_hits = 0
    metric_hits = 0
    total = len(cases)
    for case in cases:
        answer = graphrag_search(case["query"], top_k=5, use_llm=False)
        predicted_categories = [x["category"] for x in answer.get("matched_categories", [])]
        predicted_metrics = [x["metric"] for x in answer.get("matched_metrics", [])]
        if case["type"] == "local":
            hit = any(is_metric_hit(name, case["expected_metrics"]) for name in predicted_metrics[:5])
            metric_hits += int(hit)
            details.append({
                "query": case["query"], "type": case["type"],
                "expected": case["expected_metrics"], "predicted": predicted_metrics[:5],
                "hit": hit
            })
        else:
            hit = any(category in case["expected_categories"] for category in predicted_categories)
            category_hits += int(hit)
            details.append({
                "query": case["query"], "type": case["type"],
                "expected": case["expected_categories"], "predicted": predicted_categories,
                "hit": hit
            })

    local_cases = sum(1 for case in cases if case["type"] == "local")
    global_cases = total - local_cases
    return {
        "total": total,
        "local_metric_recall_at_5": metric_hits / local_cases if local_cases else 0.0,
        "global_category_recall": category_hits / global_cases if global_cases else 0.0,
        "details": details
    }


graphrag_summary = evaluate_graphrag(graphrag_eval_cases)
print("GraphRAG 评估：")
print(json.dumps(graphrag_summary, ensure_ascii=False, indent=2))
if os.getenv("RUN_OFFLINE_EVAL", "false").lower() == "true":
    save_evaluation(graphrag_summary, str(RUNTIME_DIR / "graphrag_evaluation_summary.json"))
