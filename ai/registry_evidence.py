"""Rank curated public guidance for report cards."""
import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

GUIDE_PATH = Path(__file__).resolve().parents[1] / "data/knowledge_base/guides/registry-recheck.jsonl"
REGISTRY_QUERY = "잔금 지급 직전 등기부 권리관계 재확인"


def _tokens(text):
    words = re.findall(r"[가-힣A-Za-z0-9]+", text.lower())
    return Counter(word[i:i + 2] for word in words for i in range(len(word) - 1))


@lru_cache(maxsize=1)
def load_registry_guides():
    try:
        with GUIDE_PATH.open(encoding="utf-8") as stream:
            return tuple(json.loads(line) for line in stream if line.strip())
    except (OSError, ValueError):
        return ()


def search_registry_guides(records, limit=2):
    guides = [item for item in records if item.get("topic") == "registry_recheck"]
    if not guides:
        return []
    token_counts = [_tokens(f"{item['title']} {item['summary']}") for item in guides]
    lengths = [sum(counts.values()) for counts in token_counts]
    average = sum(lengths) / len(lengths) or 1
    scores = [0.0] * len(guides)
    for term in _tokens(REGISTRY_QUERY):
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
