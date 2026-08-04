"""Metric-library constrained query normalization.

This module generates correction candidates without replacing the user's
original query. It is intentionally conservative: a correction is accepted
only when it maps to an existing metric or alias.
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import json
import re
from typing import Iterable

try:
    from pypinyin import lazy_pinyin
except ImportError:  # Optional dependency; exact search still works without it.
    lazy_pinyin = None

try:
    from rapidfuzz.fuzz import ratio as fuzzy_ratio
except ImportError:
    def fuzzy_ratio(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio() * 100


_NOISE_RE = re.compile(r"[，。！？、；：,.!?;:'\"（）()\[\]{}\s]+")


CONFUSION_GROUPS = [
    "铃玲灵陵", "薯署暑", "户护互", "籍藉集", "常长场",
    "驻住注", "灌罐贯", "溉概盖", "耕更羹", "畜蓄续", "禽擒勤",
]
CONFUSION_MAP = {char: group[0] for group in CONFUSION_GROUPS for char in group}


def compact_text(text: str) -> str:
    return _NOISE_RE.sub("", str(text or "")).strip().lower()


def pinyin_key(text: str) -> str:
    text = str(text or "").strip()
    if not text or lazy_pinyin is None:
        return ""
    return "".join(lazy_pinyin(text)).lower()


def pinyin_initials(text: str) -> str:
    text = str(text or "").strip()
    if not text or lazy_pinyin is None:
        return ""
    return "".join(item[0] for item in lazy_pinyin(text) if item).lower()


def shape_key(text: str) -> str:
    return "".join(CONFUSION_MAP.get(char, char) for char in str(text or "")).lower()


def load_oral_aliases(path: str) -> list[dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return [item for item in data if item.get("metric") and item.get("aliases")]


def build_metric_terms(metrics: Iterable[dict]) -> list[dict]:
    terms = []
    seen = set()
    for item in metrics:
        canonical = str(item.get("metric") or "").strip()
        if not canonical:
            continue
        aliases = item.get("aliases") or []
        for term in [canonical]:
            term = str(term or "").strip()
            key = compact_text(term)
            if not key or key in seen:
                continue
            seen.add(key)
            terms.append({
                "term": term,
                "canonical": canonical,
                "pinyin": pinyin_key(term),
                "initials": pinyin_initials(term),
                "shape": shape_key(term),
                "confidence": item.get("confidence", "high"),
                "region": item.get("region", ""),
                "source_url": item.get("source_url", ""),
            })
    for item in metrics:
        canonical = str(item.get("metric") or "").strip()
        if not canonical:
            continue
        for term in item.get("aliases") or []:
            term = str(term or "").strip()
            key = compact_text(term)
            if not key or key in seen:
                continue
            seen.add(key)
            terms.append({
                "term": term,
                "canonical": canonical,
                "pinyin": pinyin_key(term),
                "initials": pinyin_initials(term),
                "shape": shape_key(term),
                "confidence": item.get("confidence", "high"),
                "region": item.get("region", ""),
                "source_url": item.get("source_url", ""),
            })
    return terms


def generate_query_candidates(query: str, metric_terms: list[dict], limit: int = 5) -> list[dict]:
    """Return original plus conservative metric-library correction candidates."""
    original = str(query or "").strip()
    if not original:
        return []

    candidates = [{"text": original, "score": 1.0, "reason": "原始输入"}]
    query_key = compact_text(original)
    query_pinyin = pinyin_key(original)
    query_initials = pinyin_initials(original)
    scored = {}

    for item in metric_terms:
        term = item["term"]
        term_key = compact_text(term)
        if term_key == query_key:
            canonical_key = compact_text(item["canonical"])
            if term_key != canonical_key:
                score = 0.995
                reason = "农村口语或方言别名，标准指标库存在对应指标"
            else:
                continue
        else:
            score = 0.0
            reason = ""

        if not score and (
            len(query_key) >= 3
            and len(query_key) == len(term_key)
            and Counter(query_key) == Counter(term_key)
        ):
            score = 0.84
            reason = "字符顺序存在变化，但字符集合与标准指标一致"
        elif not score and (
            len(query_key) >= 2
            and shape_key(original) == item.get("shape", "")
            and query_key != term_key
        ):
            score = 0.97
            reason = "形近字或语音识别混淆，标准表达存在于指标库"
        elif not score and query_pinyin and item["pinyin"] == query_pinyin:
            score = 0.99 if compact_text(term) == compact_text(item["canonical"]) else 0.98
            reason = "拼音完全一致，且标准表达存在于指标库"
        elif not score and (
            query_pinyin
            and item["pinyin"]
            and len(query_key) >= 2
            and abs(len(query_key) - len(term_key)) <= 1
        ):
            if (
                query_pinyin in item["pinyin"]
                or item["pinyin"] in query_pinyin
            ) and abs(len(query_pinyin) - len(item["pinyin"])) <= 3:
                pinyin_similarity = 0.96
                reason = "拼音前缀匹配，可能存在漏字，且标准表达存在于指标库"
            else:
                pinyin_similarity = fuzzy_ratio(query_pinyin, item["pinyin"]) / 100.0
            if pinyin_similarity >= 0.86:
                score = pinyin_similarity * 0.92
                reason = reason or "拼音高度相似，可能存在错音或漏字，且标准表达存在于指标库"
        elif not score and query_initials and len(query_initials) >= 2 and item["initials"] == query_initials:
            score = 0.82
            reason = "拼音首字母一致，且标准表达存在于指标库"
        elif not score and (
            len(query_key) >= 3
            and len(query_key) == len(term_key)
            and Counter(query_key) == Counter(term_key)
        ):
            score = 0.84
            reason = "字符顺序存在变化，但字符集合与标准指标一致"
        elif not score and len(query_key) >= 2 and len(term_key) >= 2:
            similarity = fuzzy_ratio(query_key, term_key) / 100.0
            if similarity >= 0.78:
                score = similarity * 0.90
                reason = "字面相似，且标准表达存在于指标库"

        if score and (
            item["canonical"] not in scored
            or score > scored[item["canonical"]]["score"]
        ):
            confidence = item.get("confidence", "high")
            if confidence == "low":
                score *= 0.72
            elif confidence == "medium":
                score *= 0.92
            scored[item["canonical"]] = {
                "text": item["canonical"],
                "score": round(score, 4),
                "reason": reason,
                "matched_term": term,
                "confidence": confidence,
                "region": item.get("region", ""),
                "source_url": item.get("source_url", ""),
            }

    ranked = sorted(scored.values(), key=lambda item: item["score"], reverse=True)
    for item in ranked[: max(0, limit - 1)]:
        if item["text"] != original:
            candidates.append(item)
    return candidates[:limit]


def choose_normalized_query(query: str, candidates: list[dict], threshold: float = 0.82):
    """Choose a safe correction; keep ambiguous candidates for reranking only."""
    original = str(query or "").strip()
    if len(candidates) < 2 or len(compact_text(original)) <= 1:
        return original, None
    candidate = candidates[1]
    score = float(candidate.get("score", 0.0) or 0.0)
    confidence = candidate.get("confidence", "high")
    matched_term = str(candidate.get("matched_term", ""))
    canonical = str(candidate.get("text", ""))
    exact_alias = compact_text(matched_term) == compact_text(original)
    close_shape_or_sound = score >= 0.94
    likely_missing_char = score >= 0.86 and abs(
        len(compact_text(original)) - len(compact_text(canonical))
    ) <= 1
    if confidence == "low" or score < threshold:
        return original, None
    if exact_alias or close_shape_or_sound or likely_missing_char:
        return canonical, candidate
    return original, None
