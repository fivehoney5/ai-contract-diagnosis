"""공공 API(실거래가·건축물대장·도로명주소) 응답 캐시.

- ApiCache: get/save만 있는 인터페이스. 서버 DB 등으로 바꿀 때 이 모양만 맞추면 된다.
- SQLiteApiCache: 표준 라이브러리 sqlite3로 만든 기본 구현. 요청마다 연결을 새로 열어서 여러 스레드에서 써도 된다.
- cached_call: "캐시 확인 → 없거나 만료면 API → 저장"을 한 번에 한다.
  API가 실패했는데 만료된 저장본이 있으면 그 저장본으로 응답한다 (시연 중 API 장애 대비).
- track_cache_usage: 분석 한 번 동안 캐시를 썼는지 모아서 결과의 data_source에 쓴다.

정상 응답만 저장하고 API 오류는 저장하지 않는다. 캐시 파일을 못 열거나 쓰지 못해도 분석은 계속한다.

환경 변수 (.env):
    PUBLIC_API_CACHE=off        캐시를 끈다 (기본: 켬)
    PUBLIC_API_CACHE_PATH=...   캐시 파일 위치 (기본: 저장소 루트의 data/local/public_api_cache.sqlite)
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

# /data/local/은 .gitignore에 있어서 깃에 올라가지 않는다. backend/var/와도 겹치지 않는다.
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "local" / "public_api_cache.sqlite"
ENV_SWITCH = "PUBLIC_API_CACHE"
ENV_PATH = "PUBLIC_API_CACHE_PATH"
OFF_VALUES = {"0", "off", "false", "no"}

DAY = 86400
# 만료 후 API가 실패할 때 저장본을 쓸 수 있는 최대 기간. 이보다 오래되면 저장본을 쓰지 않고 실패로 둔다
MAX_STALE_SECONDS = 30 * DAY
# 만료 후 이 기간이 지난 행은 지운다 (저장본으로도 못 쓰는 행, 사용자가 입력한 주소 검색어 포함)
PURGE_AFTER_EXPIRY_SECONDS = MAX_STALE_SECONDS
PURGE_INTERVAL_SECONDS = 3600  # 저장할 때 정리 작업은 이 간격에 한 번만

logger = logging.getLogger(__name__)

DATA_SOURCE_API = "api"  # 모두 API에서 새로 받음 (일부만 캐시여도 api)
DATA_SOURCE_CACHE = "cache"  # 모두 만료 전 캐시에서 씀
DATA_SOURCE_STALE = "stale_cache"  # API가 실패해서 만료된 저장본을 씀


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    saved_at: float
    expires_at: float

    @property
    def fresh(self) -> bool:
        return time.time() < self.expires_at


class ApiCache(Protocol):
    def get(self, namespace: str, key: str) -> CacheEntry | None:
        """저장된 값. 만료됐어도 돌려준다 (만료 여부는 entry.fresh). 없으면 None."""

    def save(self, namespace: str, key: str, value: Any, ttl_seconds: float) -> None:
        """JSON으로 바꿀 수 있는 값을 저장한다."""


class SQLiteApiCache:
    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH):
        self.path = str(path)
        self._lock = threading.Lock()
        self._memory: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._memory = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS api_cache ("
                " namespace TEXT NOT NULL,"
                " key TEXT NOT NULL,"
                " value_json TEXT NOT NULL,"
                " saved_at REAL NOT NULL,"
                " expires_at REAL NOT NULL,"
                " PRIMARY KEY (namespace, key))"
            )
        self._last_purge = 0.0
        self.purge()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._memory or sqlite3.connect(self.path, timeout=5)
            try:
                yield conn
                conn.commit()
            finally:
                if conn is not self._memory:
                    conn.close()

    def get(self, namespace: str, key: str) -> CacheEntry | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value_json, saved_at, expires_at FROM api_cache WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        try:
            return CacheEntry(json.loads(row[0]), float(row[1]), float(row[2]))
        except (ValueError, TypeError):
            return None

    def save(self, namespace: str, key: str, value: Any, ttl_seconds: float) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO api_cache (namespace, key, value_json, saved_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (namespace, key, json.dumps(value, ensure_ascii=False), now, now + ttl_seconds),
            )
        if now - self._last_purge > PURGE_INTERVAL_SECONDS:
            self.purge()

    def purge(self, after_expiry_seconds: float = PURGE_AFTER_EXPIRY_SECONDS) -> int:
        """만료 후 after_expiry_seconds가 지난 행을 지우고 지운 개수를 돌려준다.

        저장본으로도 쓸 수 없는 행이라 남길 이유가 없다. 주소 캐시에는 사용자가 입력한 주소가 들어 있어서
        오래 남지 않게 한다 (주소는 만료 30일 + 30일 = 저장 후 최대 60일).
        """
        now = time.time()
        self._last_purge = now
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM api_cache WHERE expires_at < ?", (now - after_expiry_seconds,))
            return cur.rowcount

    def close(self) -> None:
        if self._memory is not None:
            self._memory.close()


_default: dict[str, SQLiteApiCache] = {}
_default_lock = threading.Lock()


def default_cache() -> ApiCache | None:
    """환경 변수에 맞는 기본 캐시. 꺼져 있거나 파일을 만들 수 없으면 None."""
    if os.getenv(ENV_SWITCH, "").strip().lower() in OFF_VALUES:
        return None
    path = os.getenv(ENV_PATH, "").strip() or str(DEFAULT_CACHE_PATH)
    with _default_lock:
        if path not in _default:
            try:
                _default[path] = SQLiteApiCache(path)
            except (OSError, sqlite3.Error):
                return None
        return _default[path]


@dataclass(frozen=True)
class CacheEvent:
    namespace: str
    key: str
    source: str  # api / cache / stale_cache
    saved_at: float | None = None  # cache, stale_cache일 때 저장 시각


_events: contextvars.ContextVar[list[CacheEvent] | None] = contextvars.ContextVar("api_cache_events", default=None)


@contextmanager
def track_cache_usage() -> Iterator[list[CacheEvent]]:
    """이 블록 안에서 일어난 API·캐시 사용 기록을 모은다."""
    events: list[CacheEvent] = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)


def _record(event: CacheEvent) -> None:
    events = _events.get()
    if events is not None:
        events.append(event)


def summarize_events(events: list[CacheEvent]) -> tuple[str | None, str | None]:
    """(data_source, 안내 문구). 기록이 없으면 (None, None)."""
    if not events:
        return None, None
    stale = [e for e in events if e.source == DATA_SOURCE_STALE]
    if stale:
        oldest = min(e.saved_at for e in stale if e.saved_at is not None)
        when = datetime.fromtimestamp(oldest).strftime("%Y-%m-%d %H:%M")
        return DATA_SOURCE_STALE, f"공공 API 조회에 실패해 저장해 둔 데이터({when} 저장)를 사용했습니다"
    if all(e.source == DATA_SOURCE_CACHE for e in events):
        return DATA_SOURCE_CACHE, None
    return DATA_SOURCE_API, None


KST = timezone(timedelta(hours=9))


def cache_saved_at(events: list[CacheEvent]) -> str | None:
    """캐시(만료 전·저장본)에서 꺼낸 데이터 중 가장 오래된 저장 시각 (ISO 8601, +09:00). API로만 받았으면 None.

    data_source가 stale_cache면 저장본만, cache면 캐시 전체에서 고른다. 화면은 이 값으로 "11월 20일 저장" 등을 표시한다.
    """
    source, _ = summarize_events(events)
    wanted = {DATA_SOURCE_STALE: (DATA_SOURCE_STALE,), DATA_SOURCE_CACHE: (DATA_SOURCE_CACHE,)}.get(source)
    if wanted is None:
        return None
    times = [e.saved_at for e in events if e.source in wanted and e.saved_at is not None]
    if not times:
        return None
    return datetime.fromtimestamp(min(times), KST).isoformat(timespec="seconds")


def cached_call(
    namespace: str,
    key: str,
    fetch: Callable[[], Any],
    *,
    ttl_seconds: float,
    cache: ApiCache | None,
    fallback_errors: tuple[type[BaseException], ...] = (Exception,),
    dump: Callable[[Any], Any] = lambda v: v,
    load: Callable[[Any], Any] = lambda v: v,
    max_stale_seconds: float = MAX_STALE_SECONDS,
) -> Any:
    """캐시에 만료 전 값이 있으면 그 값, 없으면 fetch() 결과를 저장하고 돌려준다.

    fetch()가 fallback_errors를 던지면 만료된 지 max_stale_seconds 안의 저장본이 있을 때 그것을 돌려주고
    (경고 로그를 남김), 없거나 더 오래됐으면 그대로 던진다 (호출하는 쪽에서 API_UNAVAILABLE 등으로 처리).
    dump/load : 값 <-> JSON으로 저장할 모양 변환.
    """
    entry: CacheEntry | None = None
    if cache is not None:
        try:
            entry = cache.get(namespace, key)
        except sqlite3.Error:
            entry = None
        if entry is not None and entry.fresh:
            try:
                value = load(entry.value)
            except (ValueError, TypeError, KeyError):
                entry = None  # 저장 모양이 바뀌었으면 다시 받는다
            else:
                _record(CacheEvent(namespace, key, DATA_SOURCE_CACHE, entry.saved_at))
                return value

    try:
        value = fetch()
    except fallback_errors as e:
        if entry is None:
            raise
        if time.time() - entry.expires_at > max_stale_seconds:
            logger.warning("공공 API 실패, 저장본이 너무 오래돼 쓰지 않음 [%s] %s: %s",
                           namespace, type(e).__name__, str(e)[:200])
            raise
        stale = load(entry.value)
        # 인증키가 빠졌거나 만료된 경우도 여기로 온다. 운영 중에 모르고 지나가지 않게 경고를 남긴다
        logger.warning("공공 API 실패로 만료된 저장본 사용 [%s] 저장 %s, %s: %s",
                       namespace, datetime.fromtimestamp(entry.saved_at).strftime("%Y-%m-%d %H:%M"),
                       type(e).__name__, str(e)[:200])
        _record(CacheEvent(namespace, key, DATA_SOURCE_STALE, entry.saved_at))
        return stale

    if cache is not None:
        try:
            cache.save(namespace, key, dump(value), ttl_seconds)
        except (sqlite3.Error, TypeError, ValueError):
            pass
    _record(CacheEvent(namespace, key, DATA_SOURCE_API))
    return value
