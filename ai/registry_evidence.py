"""Rank curated public guidance for report cards."""
import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

GUIDE_PATH = Path(__file__).resolve().parents[1] / "data/knowledge_base/guides/registry-recheck.jsonl"
TRUST_GUIDE_PATH = GUIDE_PATH.with_name("trust-registration.jsonl")
TRUST_QUERY = "신탁등기 신탁원부 임대 권한 신탁회사 동의"
REGISTRY_QUERY = "잔금 지급 직전 등기부 권리관계 재확인"


def _tokens(text):
    words = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    return Counter(word[i:i + 2] for word in words for i in range(len(word) - 1))


@lru_cache(maxsize=3)
def _load_guides(path):
    try:
        with path.open(encoding="utf-8") as stream:
            return tuple(json.loads(line) for line in stream if line.strip())
    except (OSError, ValueError):
        return ()


def search_registry_guides(records, limit=2):
    return _search_guides(records, "registry_recheck", REGISTRY_QUERY, limit)


def load_registry_guides():
    return _load_guides(GUIDE_PATH)


def load_trust_guides():
    return _load_guides(TRUST_GUIDE_PATH)


def search_trust_guides(records, limit=2):
    return _search_guides(records, "trust_registration", TRUST_QUERY, limit)


def search_restriction_guides():
    path = GUIDE_PATH.with_name("ownership-restriction.jsonl")
    return _search_guides(_load_guides(path), "ownership_restriction", "등기부 갑구 압류 가압류 권리관계", 2)


def _search_guides(records, topic, query, limit):
    guides = [item for item in records if item.get("topic") == topic]
    if not guides:
        return []
    token_counts = [_tokens(f"{item['title']} {item['summary']}") for item in guides]
    lengths = [sum(counts.values()) for counts in token_counts]
    average = sum(lengths) / len(lengths) or 1
    scores = [0.0] * len(guides)
    for term in _tokens(query):
        document_frequency = sum(term in counts for counts in token_counts)
        if not document_frequency:
            continue
        idf = math.log1p((len(guides) - document_frequency + 0.5) / (document_frequency + 0.5))
        for index, counts in enumerate(token_counts):
            frequency = counts[term]
            norm = 1.2 * (0.25 + 0.75 * lengths[index] / average)
            scores[index] += idf * frequency * 2.2 / (frequency + norm)
    order = sorted(range(len(guides)), key=lambda index: (-scores[index], guides[index]["id"]))
    fields = ("id", "title", "url", "summary", "text_type")
    return [
        {key: guides[index][key] for key in fields}
        for index in order[:limit]
        if scores[index] > 0
    ]
