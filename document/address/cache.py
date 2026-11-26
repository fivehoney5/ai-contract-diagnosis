"""주소 검색 결과 캐시. 같은 주소를 다시 넣으면 API를 부르지 않는다.

- AddressCache: get/save만 있는 인터페이스. 다른 저장소(서버 DB 등)로 바꿀 때 이 모양만 맞추면 된다.
- SQLiteAddressCache: 표준 라이브러리 sqlite3로 만든 기본 구현.
- 정상 응답(검색 결과 0건 포함)만 저장한다. API 오류는 저장하지 않는다.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Protocol

# 저장소 루트 기준. /data/local/은 .gitignore에 있어서 깃에 올라가지 않는다.
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "local" / "address_cache.sqlite"
DEFAULT_TTL_DAYS = 30  # 주소는 잘 바뀌지 않지만 신축·도로명 변경이 있어서 한 달 뒤엔 다시 조회


class AddressCache(Protocol):
    def get(self, keyword: str) -> tuple[int, list[dict]] | None:
        """저장된 (전체 건수, 주소 목록). 없거나 기간이 지났으면 None."""

    def save(self, keyword: str, total: int, juso: list[dict]) -> None:
        """검색 결과를 저장한다."""


def normalize_cache_key(keyword: str) -> str:
    return " ".join(keyword.split())


class SQLiteAddressCache:
    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH, ttl_days: float = DEFAULT_TTL_DAYS):
        self.path = str(path)
        self.ttl_seconds = ttl_days * 86400
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS juso_cache ("
            " keyword TEXT PRIMARY KEY,"
            " total INTEGER NOT NULL,"
            " juso_json TEXT NOT NULL,"
            " saved_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, keyword: str) -> tuple[int, list[dict]] | None:
        row = self._conn.execute(
            "SELECT total, juso_json, saved_at FROM juso_cache WHERE keyword = ?",
            (normalize_cache_key(keyword),),
        ).fetchone()
        if row is None:
            return None
        total, juso_json, saved_at = row
        if time.time() - saved_at > self.ttl_seconds:
            return None
        try:
            return int(total), json.loads(juso_json)
        except (ValueError, TypeError):
            return None

    def save(self, keyword: str, total: int, juso: list[dict]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO juso_cache (keyword, total, juso_json, saved_at) VALUES (?, ?, ?, ?)",
            (normalize_cache_key(keyword), int(total), json.dumps(juso, ensure_ascii=False), time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
