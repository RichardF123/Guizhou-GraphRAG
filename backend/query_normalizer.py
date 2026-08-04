"""Metric-library constrained query normalization.

This module generates correction candidates without replacing the user's
original query. It is intentionally conservative: a correction is accepted
only when it maps to an existing metric or alias.
"""

from __future__ import annotations

from difflib import SequenceMatcher
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
            continue

        score = 0.0
        reason = ""
        if query_pinyin and item["pinyin"] == query_pinyin:
            score = 0.99 if compact_text(term) == compact_text(item["canonical"]) else 0.98
            reason = "拼音完全一致，且标准表达存在于指标库"
        elif query_initials and len(query_initials) >= 2 and item["initials"] == query_initials:
            score = 0.82
            reason = "拼音首字母一致，且标准表达存在于指标库"
        elif len(query_key) >= 2 and len(term_key) >= 2:
            similarity = fuzzy_ratio(query_key, term_key) / 100.0
            if similarity >= 0.78:
                score = similarity * 0.90
                reason = "字面相似，且标准表达存在于指标库"

        if score and (
            item["canonical"] not in scored
            or score > scored[item["canonical"]]["score"]
        ):
            scored[item["canonical"]] = {
                "text": item["canonical"],
                "score": round(score, 4),
                "reason": reason,
                "matched_term": term,
            }

    ranked = sorted(scored.values(), key=lambda item: item["score"], reverse=True)
    for item in ranked[: max(0, limit - 1)]:
        if item["text"] != original:
            candidates.append(item)
    return candidates[:limit]
