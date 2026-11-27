"""공공 API 캐시 테스트. 실제 API는 부르지 않고 가짜 응답과 임시 DB만 쓴다.

실행: python -m unittest discover -s document/api_cache/tests -v (저장소 루트에서)
"""

import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime
from unittest import mock

import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from document import api_cache  # noqa: E402
from document.api_cache import store  # noqa: E402
from document.api_cache import (  # noqa: E402
    DATA_SOURCE_API,
    DATA_SOURCE_CACHE,
    DATA_SOURCE_STALE,
    SQLiteApiCache,
    cached_call,
    track_cache_usage,
)
from document.address import juso_client, resolve_address  # noqa: E402
from document.price import rtms_client  # noqa: E402
from document.price.analysis_result import analyze_price  # noqa: E402
from document.price.building_register import fetch_building_info  # noqa: E402
from document.price.rtms_client import fetch_recent_trades, fetch_trades, trade_cache_ttl  # noqa: E402

TODAY = date(2026, 11, 27)


def rtms_xml(n=1, ymd="202611"):
    items = "".join(
        "<item><aptNm>상계주공6</aptNm><umdNm>상계동</umdNm><jibun>720</jibun>"
        "<excluUseAr>58.01</excluUseAr><dealAmount>60,000</dealAmount>"
        f"<dealYear>{ymd[:4]}</dealYear><dealMonth>{int(ymd[4:])}</dealMonth><dealDay>{i + 1}</dealDay>"
        "<floor>5</floor><buildYear>1988</buildYear></item>"
        for i in range(n)
    )
    return (
        "<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><items>{items}</items><totalCount>{n}</totalCount></body></response>"
    )


def title_xml():
    return (
        "<response><header><resultCode>00</resultCode><resultMsg>OK</resultMsg></header><body><items>"
        "<item><mainAtchGbCd>0</mainAtchGbCd><bldNm>상계주공6</bldNm><platPlc>서울 노원구 상계동 720</platPlc>"
        "<useAprDay>19880101</useAprDay><mainPurpsCd>02000</mainPurpsCd><mainPurpsCdNm>공동주택</mainPurpsCdNm>"
        "<etcPurps>아파트</etcPurps></item></items><totalCount>1</totalCount></body></response>"
    )


class FakeResp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class FakeSession:
    """responses: FakeResp 또는 예외. 다 쓰면 마지막 것을 계속 돌려준다."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        r = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r


def expire_all(cache: SQLiteApiCache, seconds_ago: float = 1):
    with cache._conn() as conn:
        conn.execute("UPDATE api_cache SET expires_at = ?", (time.time() - seconds_ago,))


class StoreTests(unittest.TestCase):
    def test_save_get_and_expiry(self):
        c = SQLiteApiCache(":memory:")
        c.save("ns", "k", {"a": [1, "가"]}, ttl_seconds=60)
        e = c.get("ns", "k")
        self.assertEqual(e.value, {"a": [1, "가"]})
        self.assertTrue(e.fresh)
        self.assertIsNone(c.get("other", "k"))
        expire_all(c)
        self.assertFalse(c.get("ns", "k").fresh)  # 만료돼도 지우지 않는다 (장애 때 저장본으로 씀)

    def test_file_cache_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "c.sqlite")
            SQLiteApiCache(path).save("ns", "k", [1], 60)
            self.assertEqual(SQLiteApiCache(path).get("ns", "k").value, [1])

    def test_default_cache_env(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.sqlite")
            with mock.patch.dict(os.environ, {"PUBLIC_API_CACHE_PATH": path}):
                c = api_cache.default_cache()
                self.assertEqual(c.path, path)
                self.assertTrue(os.path.exists(path))
                store._default.pop(path, None)
            with mock.patch.dict(os.environ, {"PUBLIC_API_CACHE": "off", "PUBLIC_API_CACHE_PATH": path}):
                self.assertIsNone(api_cache.default_cache())


class CachedCallTests(unittest.TestCase):
    def setUp(self):
        self.cache = SQLiteApiCache(":memory:")
        self.calls = 0

    def fetch_ok(self):
        self.calls += 1
        return {"n": self.calls}

    def fetch_fail(self):
        self.calls += 1
        raise RuntimeError("down")

    def call(self, fetch):
        return cached_call("ns", "k", fetch, ttl_seconds=60, cache=self.cache, fallback_errors=(RuntimeError,))

    def test_second_call_uses_cache(self):
        with track_cache_usage() as ev:
            self.assertEqual(self.call(self.fetch_ok), {"n": 1})
            self.assertEqual(self.call(self.fetch_ok), {"n": 1})
        self.assertEqual(self.calls, 1)
        self.assertEqual([e.source for e in ev], [DATA_SOURCE_API, DATA_SOURCE_CACHE])

    def test_expired_refetches(self):
        self.call(self.fetch_ok)
        expire_all(self.cache)
        self.assertEqual(self.call(self.fetch_ok), {"n": 2})

    def test_failure_uses_stale(self):
        self.call(self.fetch_ok)
        expire_all(self.cache)
        with track_cache_usage() as ev:
            self.assertEqual(self.call(self.fetch_fail), {"n": 1})
        self.assertEqual(ev[0].source, DATA_SOURCE_STALE)
        source, note = api_cache.summarize_events(ev)
        self.assertEqual(source, DATA_SOURCE_STALE)
        self.assertIn("저장", note)

    def test_failure_without_cache_raises_and_is_not_saved(self):
        with self.assertRaises(RuntimeError):
            self.call(self.fetch_fail)
        self.assertIsNone(self.cache.get("ns", "k"))

    def test_too_old_stale_not_used(self):
        self.call(self.fetch_ok)
        expire_all(self.cache, store.MAX_STALE_SECONDS + 60)
        with self.assertLogs("document.api_cache.store", "WARNING") as logs, self.assertRaises(RuntimeError):
            self.call(self.fetch_fail)
        self.assertIn("너무 오래", logs.output[0])

    def test_stale_use_is_logged(self):
        self.call(self.fetch_ok)
        expire_all(self.cache)
        with self.assertLogs("document.api_cache.store", "WARNING") as logs:
            self.call(self.fetch_fail)
        self.assertIn("저장본 사용", logs.output[0])
        self.assertIn("RuntimeError: down", logs.output[0])

    def test_purge_removes_old_rows(self):
        self.cache.save("juso", "old", [1], 60)
        self.cache.save("juso", "new", [2], 60)
        with self.cache._conn() as conn:
            conn.execute("UPDATE api_cache SET expires_at = ? WHERE key = 'old'",
                         (time.time() - store.PURGE_AFTER_EXPIRY_SECONDS - 60,))
        self.assertEqual(self.cache.purge(), 1)
        self.assertIsNone(self.cache.get("juso", "old"))
        self.assertIsNotNone(self.cache.get("juso", "new"))

    def test_purge_runs_on_open_and_save(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.sqlite")
            c = SQLiteApiCache(path)
            c.save("juso", "old", [1], 60)
            with c._conn() as conn:
                conn.execute("UPDATE api_cache SET expires_at = 0")
            self.assertIsNone(SQLiteApiCache(path).get("juso", "old"))  # 열 때 정리
            c.save("juso", "old", [1], 60)
            with c._conn() as conn:
                conn.execute("UPDATE api_cache SET expires_at = 0")
            c._last_purge = 0
            c.save("juso", "other", [2], 60)  # 저장할 때도 한 시간에 한 번 정리
            self.assertIsNone(c.get("juso", "old"))

    def test_other_errors_not_covered(self):
        self.call(self.fetch_ok)
        expire_all(self.cache)

        def bad():
            raise ValueError("bug")

        with self.assertRaises(ValueError):
            self.call(bad)


@mock.patch.object(rtms_client, "RETRY_WAIT", 0)
class TradeCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = SQLiteApiCache(":memory:")

    def test_ttl_by_month(self):
        self.assertEqual(trade_cache_ttl("202611", TODAY), rtms_client.TTL_THIS_MONTH)
        self.assertEqual(trade_cache_ttl("202610", TODAY), rtms_client.TTL_LAST_MONTH)
        self.assertEqual(trade_cache_ttl("202512", TODAY), rtms_client.TTL_OLDER)

    def test_same_month_not_called_again(self):
        s = FakeSession(FakeResp(rtms_xml(2)))
        a = fetch_trades("apt", "11350", "202611", service_key="k", session=s, cache=self.cache, today=TODAY)
        b = fetch_trades("아파트", "11350", "202611", service_key="k", session=s, cache=self.cache, today=TODAY)
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(a, b)
        self.assertEqual(b[0].deal_date, date(2026, 11, 1))
        # 다른 시군구·다른 달은 따로 부른다
        fetch_trades("apt", "11350", "202610", service_key="k", session=s, cache=self.cache, today=TODAY)
        fetch_trades("apt", "11500", "202611", service_key="k", session=s, cache=self.cache, today=TODAY)
        self.assertEqual(len(s.calls), 3)

    def test_api_down_uses_stale(self):
        ok = FakeSession(FakeResp(rtms_xml(1)))
        fetch_trades("apt", "11350", "202611", service_key="k", session=ok, cache=self.cache, today=TODAY)
        expire_all(self.cache)
        down = FakeSession(requests.ConnectionError("x"))
        got = fetch_trades("apt", "11350", "202611", service_key="k", session=down, cache=self.cache, today=TODAY)
        self.assertEqual(len(got), 1)
        self.assertEqual(len(down.calls), rtms_client.RETRIES + 1)

    def test_error_response_not_cached(self):
        err = "<response><header><resultCode>99</resultCode><resultMsg>LIMITED</resultMsg></header></response>"
        s = FakeSession(FakeResp(err), FakeResp(rtms_xml(1)))
        with self.assertRaises(rtms_client.RTMSApiError):
            fetch_trades("apt", "11350", "202611", service_key="k", session=s, cache=self.cache, today=TODAY)
        got = fetch_trades("apt", "11350", "202611", service_key="k", session=s, cache=self.cache, today=TODAY)
        self.assertEqual(len(got), 1)

    def test_fake_session_skips_default_cache(self):
        with mock.patch.object(rtms_client, "default_cache") as dc:
            fetch_trades("apt", "11350", "202611", service_key="k", session=FakeSession(FakeResp(rtms_xml())), today=TODAY)
        dc.assert_not_called()

    def test_cache_none_disables(self):
        s = FakeSession(FakeResp(rtms_xml()))
        for _ in range(2):
            fetch_trades("apt", "11350", "202611", service_key="k", session=s, cache=None, today=TODAY)
        self.assertEqual(len(s.calls), 2)


@mock.patch.object(rtms_client, "RETRY_WAIT", 0)
class BuildingCacheTests(unittest.TestCase):
    def test_second_call_uses_cache_and_key_not_stored(self):
        cache = SQLiteApiCache(":memory:")
        s = FakeSession(FakeResp(title_xml()))
        a = fetch_building_info("1135010500", "720", service_key="SECRET", session=s, cache=cache)
        b = fetch_building_info("1135010500", "720", service_key="OTHER", session=s, cache=cache)
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(s.calls[0][1]["serviceKey"], "SECRET")
        self.assertEqual((a.build_year, b.build_year), (1988, 1988))
        with cache._conn() as conn:
            keys = [r[0] for r in conn.execute("SELECT key FROM api_cache")]
        self.assertFalse(any("SECRET" in k for k in keys))

    def test_api_down_uses_stale(self):
        cache = SQLiteApiCache(":memory:")
        fetch_building_info("1135010500", "720", service_key="k", session=FakeSession(FakeResp(title_xml())), cache=cache)
        expire_all(cache)
        info = fetch_building_info("1135010500", "720", service_key="k", session=FakeSession(FakeResp("", 503)), cache=cache)
        self.assertEqual(info.build_year, 1988)


@mock.patch.object(rtms_client, "RETRY_WAIT", 0)
class AnalyzePriceDataSourceTests(unittest.TestCase):
    def run_price(self, cache, session):
        def fetcher(ptype, lawd_cd, months, today):
            return fetch_recent_trades(ptype, lawd_cd, months, today, service_key="k", session=session, cache=cache)

        return analyze_price("apt", "11350", "상계동", "상계주공6", 58.01, 300_000_000,
                             months=2, today=TODAY, fetcher=fetcher)

    def test_data_source_api_then_cache_then_stale(self):
        cache = SQLiteApiCache(":memory:")
        r1 = self.run_price(cache, FakeSession(FakeResp(rtms_xml(3))))
        self.assertEqual(r1["data_status_item"]["data_source"], DATA_SOURCE_API)
        self.assertIsNone(r1["data_status_item"]["reason"])
        self.assertIsNone(r1["data_status_item"]["data_saved_at"])

        down = FakeSession(requests.ConnectionError("x"))
        r2 = self.run_price(cache, down)
        self.assertEqual(r2["data_status_item"]["data_source"], DATA_SOURCE_CACHE)
        self.assertEqual(down.calls, [])

        expire_all(cache)
        r3 = self.run_price(cache, down)
        item = r3["data_status_item"]
        self.assertEqual((item["status"], item["data_source"]), ("ok", DATA_SOURCE_STALE))
        self.assertIn("저장해 둔 데이터", item["reason"])
        saved = datetime.fromisoformat(item["data_saved_at"])
        self.assertEqual(item["data_saved_at"][-6:], "+09:00")
        self.assertLess(abs(saved.timestamp() - time.time()), 60)
        self.assertIsNotNone(r2["data_status_item"]["data_saved_at"])
        self.assertEqual(r3["price_card"]["estimated_price"], r1["price_card"]["estimated_price"])

    def test_too_old_stale_fails_as_api_unavailable(self):
        cache = SQLiteApiCache(":memory:")
        self.run_price(cache, FakeSession(FakeResp(rtms_xml(3))))
        expire_all(cache, store.MAX_STALE_SECONDS + 60)
        with self.assertLogs("document.api_cache.store", "WARNING"):
            r = self.run_price(cache, FakeSession(requests.ConnectionError("x")))
        self.assertEqual((r["data_status_item"]["status"], r["data_status_item"]["reason_code"]),
                         ("failed", "API_UNAVAILABLE"))

    def test_no_cache_failure_keeps_api_unavailable(self):
        r = self.run_price(None, FakeSession(requests.ConnectionError("x")))
        self.assertEqual(r["data_status_item"]["reason_code"], "API_UNAVAILABLE")
        self.assertIsNone(r["data_status_item"]["data_source"])

    def test_trades_given_has_no_source(self):
        r = analyze_price("apt", "11350", "상계동", "상계주공6", 58.01, 300_000_000, today=TODAY, trades=[])
        self.assertIsNone(r["data_status_item"]["data_source"])


def juso_body():
    import json

    return json.dumps({"results": {
        "common": {"errorCode": "0", "errorMessage": "정상", "totalCount": "1"},
        "juso": [{
            "admCd": "1135010500", "mtYn": "0", "lnbrMnnm": "720", "lnbrSlno": "0",
            "roadAddr": "서울특별시 노원구 노원로 532", "jibunAddr": "서울특별시 노원구 상계동 720",
            "siNm": "서울특별시", "sggNm": "노원구", "emdNm": "상계동", "bdNm": "상계주공6단지", "bdKdcd": "1",
        }],
    }}, ensure_ascii=False)


class JusoResp:
    status_code = 200

    def __init__(self, text):
        self.text = text

    def json(self):
        import json

        return json.loads(self.text)


@mock.patch.object(juso_client, "RETRY_WAIT", 0)
class AddressDefaultCacheTests(unittest.TestCase):
    def test_default_cache_and_stale_note(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.sqlite")
            with mock.patch.dict(os.environ, {"PUBLIC_API_CACHE_PATH": path}):
                try:
                    with mock.patch.object(juso_client.requests, "get", return_value=JusoResp(juso_body())) as g:
                        r1 = resolve_address("노원로 532", api_key="T")
                        r2 = resolve_address("노원로  532", api_key="T")
                    self.assertEqual(g.call_count, 1)
                    self.assertEqual(r1["status"], "ok")
                    self.assertEqual(r1["address"], r2["address"])

                    expire_all(api_cache.default_cache())
                    with mock.patch.object(juso_client.requests, "get", side_effect=requests.ConnectionError("x")):
                        r3 = resolve_address("노원로 532", api_key="T")
                    self.assertEqual(r3["status"], "ok")
                    self.assertTrue(any("도로명주소 API 조회에 실패" in n for n in r3["notes"]))
                finally:
                    store._default.pop(path, None)

    def test_off_switch(self):
        with mock.patch.dict(os.environ, {"PUBLIC_API_CACHE": "off"}):
            with mock.patch.object(juso_client.requests, "get", return_value=JusoResp(juso_body())) as g:
                resolve_address("노원로 532", api_key="T")
                resolve_address("노원로 532", api_key="T")
        self.assertEqual(g.call_count, 2)


if __name__ == "__main__":
    unittest.main()
