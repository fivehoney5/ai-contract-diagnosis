"""주소 변환 테스트. 인터넷과 키 없이 돈다 (HTTP는 가짜 세션으로 대신함).

저장소 루트에서: python -m unittest discover -s document/address/tests -v
"""

import unittest
from unittest import mock

import requests

from document.address import (
    ADDRESS_NOT_FOUND,
    API_UNAVAILABLE,
    PARSE_FAILED,
    SQLiteAddressCache,
    resolve_address,
    split_unit,
    to_price_args,
)
from document.address import juso_client


def juso(adm="1168010100", mt="0", bun="123", ji="0", emd="역삼동", bd="테스트빌딩",
         road="서울특별시 강남구 테헤란로 152", jibun_addr=None, mgt="B1", bdkd="0"):
    return {
        "admCd": adm, "mtYn": mt, "lnbrMnnm": bun, "lnbrSlno": ji, "emdNm": emd, "liNm": "",
        "bdNm": bd, "roadAddr": road, "jibunAddr": jibun_addr or f"서울특별시 강남구 {emd} {bun}",
        "zipNo": "06236", "bdMgtSn": mgt, "bdKdcd": bdkd,
    }


def body(items, code="0", msg="정상", total=None):
    return {"results": {"common": {
        "errorCode": code, "errorMessage": msg,
        "totalCount": str(len(items) if total is None else total),
    }, "juso": items}}


class FakeResp:
    def __init__(self, data=None, status=200, bad_json=False):
        self._data, self.status_code, self._bad = data, status, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._data


class FakeSession:
    """get이 불릴 때마다 responses에서 하나씩 꺼낸다. 예외 객체면 던진다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(dict(params))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def run(text, *responses, **kw):
    s = FakeSession(*responses)
    return resolve_address(text, api_key="TEST", session=s, **kw), s


@mock.patch.object(juso_client, "RETRY_WAIT", 0)
class ResolveOkTests(unittest.TestCase):
    def test_road_address_to_key(self):
        r, s = run("서울 강남구 테헤란로 152", FakeResp(body([juso()])))
        self.assertEqual(r["status"], "ok")
        self.assertIsNone(r["reason_code"])
        a = r["address"]
        self.assertEqual(a["address_key"], "1168010100-0123-0000")
        self.assertEqual(a["bjdong_cd"], "1168010100")
        self.assertEqual(a["sigungu_cd"], "11680")
        self.assertEqual((a["bun"], a["ji"], a["plat_gb"]), ("0123", "0000", "0"))
        self.assertEqual(a["jibun"], "123")
        self.assertEqual(a["legal_dong_name"], "역삼동")
        self.assertEqual(s.calls[0]["keyword"], "서울 강남구 테헤란로 152")
        self.assertEqual(s.calls[0]["resultType"], "json")

    def test_key_matches_team_example_format(self):
        r, _ = run("서울 강서구 화곡동 123-4", FakeResp(body([juso(adm="1150010300", bun="123", ji="4", emd="화곡동")])))
        self.assertEqual(r["address"]["address_key"], "1150010300-0123-0004")
        self.assertEqual(r["address"]["jibun"], "123-4")

    def test_unit_parsed_from_text(self):
        r, s = run("서울 강남구 테헤란로 152 101동 1203호", FakeResp(body([juso()])))
        self.assertEqual(r["address"]["dong_nm"], "101동")
        self.assertEqual(r["address"]["ho_nm"], "1203")
        self.assertEqual(s.calls[0]["keyword"], "서울 강남구 테헤란로 152")

    def test_explicit_unit_wins(self):
        r, _ = run("서울 강남구 테헤란로 152 401호", FakeResp(body([juso()])), dong_nm="A동", ho_nm="402")
        self.assertEqual((r["address"]["dong_nm"], r["address"]["ho_nm"]), ("A동", "402"))

    def test_same_lot_multiple_buildings_is_ok(self):
        items = [juso(bd="가동", mgt="B1"), juso(bd="나동", mgt="B2")]
        r, _ = run("역삼동 123", FakeResp(body(items)))
        self.assertEqual(r["status"], "ok")
        self.assertTrue(any("건물이 2개" in n for n in r["notes"]))

    def test_same_lot_buildings_left_empty_when_unknown(self):
        items = [juso(bd="해피빌라", mgt="B1", bdkd="1", road="A로 1", jibun_addr="서울특별시 강남구 역삼동 123 해피빌라"),
                 juso(bd="스마일빌라", mgt="B2", road="A로 3")]
        r, _ = run("역삼동 123 401호", FakeResp(body(items)))
        a = r["address"]
        self.assertEqual(a["address_key"], "1168010100-0123-0000")
        for k in ("building_name", "building_mgmt_no", "is_apartment_complex", "road_address", "zip_code"):
            self.assertIsNone(a[k], k)
        self.assertEqual(a["jibun_address"], "서울특별시 강남구 역삼동 123")
        self.assertEqual(len(a["building_candidates"]), 2)
        self.assertTrue(any("정하지 못함" in n for n in r["notes"]))

    def test_same_lot_building_picked_by_name(self):
        items = [juso(bd="해피빌라", mgt="B1"), juso(bd="스마일빌라", mgt="B2")]
        r, _ = run("역삼동 123 스마일빌라 401호", FakeResp(body(items)))
        self.assertEqual(r["address"]["building_mgmt_no"], "B2")
        self.assertEqual(r["address"]["building_name"], "스마일빌라")

    def test_same_lot_building_picked_by_dong(self):
        items = [juso(bd="해피빌라 A동", mgt="B1"), juso(bd="해피빌라 B동", mgt="B2")]
        r, _ = run("역삼동 123 B동 401호", FakeResp(body(items)))
        self.assertEqual(r["address"]["building_mgmt_no"], "B2")

    def test_same_lot_name_overlapping_legal_dong_not_picked(self):
        items = [juso(bd="역삼", mgt="B1"), juso(bd="스마일빌라", mgt="B2")]
        r, _ = run("역삼동 123", FakeResp(body(items)))
        self.assertIsNone(r["address"]["building_mgmt_no"])

    def test_single_building_has_empty_candidates(self):
        r, _ = run("테헤란로 152", FakeResp(body([juso()])))
        self.assertEqual(r["address"]["building_candidates"], [])
        self.assertEqual(r["address"]["building_name"], "테스트빌딩")

    def test_mountain_jibun(self):
        r, _ = run("강서구 개화동 산 12-3", FakeResp(body([juso(adm="1150011000", mt="1", bun="12", ji="3", emd="개화동")])))
        self.assertEqual(r["status"], "ok")
        a = r["address"]
        self.assertIsNone(a["address_key"])
        self.assertTrue(a["is_mountain"])
        self.assertEqual(a["plat_gb"], "1")
        self.assertEqual(a["jibun"], "산 12-3")
        self.assertEqual((a["bun"], a["ji"]), ("0012", "0003"))
        self.assertTrue(any("산 지번" in n for n in r["notes"]))

    def test_fallback_to_core_address(self):
        r, s = run(
            "서울 강남구 테헤란로 152 강남파이낸스센터 별관",
            FakeResp(body([])),
            FakeResp(body([juso()])),
        )
        self.assertEqual(r["status"], "ok")
        self.assertEqual(s.calls[1]["keyword"], "서울 강남구 테헤란로 152")

    def test_to_price_args(self):
        r, _ = run("서울 강서구 화곡동 355-14 B동 401호",
                   FakeResp(body([juso(adm="1150010300", bun="355", ji="14", emd="화곡동")])))
        args = to_price_args(r["address"])
        self.assertEqual(args, {
            "lawd_cd": "11500", "dong": "화곡동", "building": "355-14", "bjdong_cd": "1150010300",
            "jibun": "355-14", "dong_nm": "B동", "ho_nm": "401",
        })


@mock.patch.object(juso_client, "RETRY_WAIT", 0)
class ResolveFailTests(unittest.TestCase):
    def assertFailed(self, r, code):
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["reason_code"], code)
        self.assertIsNone(r["address"])
        self.assertTrue(r["reason"])

    def test_no_match(self):
        r, _ = run("없는로 99999", FakeResp(body([])))
        self.assertFailed(r, ADDRESS_NOT_FOUND)

    def test_ambiguous_returns_candidates(self):
        items = [juso(bun="1", road="A로 1"), juso(bun="2", road="A로 2"), juso(adm="1168010200", bun="1")]
        r, _ = run("테헤란로", FakeResp(body(items)))
        self.assertFailed(r, ADDRESS_NOT_FOUND)
        self.assertEqual(len(r["candidates"]), 3)
        self.assertEqual(r["candidates"][0]["address_key"], "1168010100-0001-0000")

    def test_more_results_than_page_is_ambiguous(self):
        r, _ = run("역삼동 123", FakeResp(body([juso()], total=40)))
        self.assertFailed(r, ADDRESS_NOT_FOUND)

    def test_empty_input(self):
        r, s = run("  ")
        self.assertFailed(r, ADDRESS_NOT_FOUND)
        self.assertEqual(s.calls, [])

    def test_keyword_error_is_not_found(self):
        r, _ = run("서울", FakeResp(body([], code="E0006", msg="주소를 상세히 입력해 주시기 바랍니다.")))
        self.assertFailed(r, ADDRESS_NOT_FOUND)
        self.assertIn("E0006", r["reason"])

    def test_bad_key_is_api_unavailable(self):
        r, _ = run("테헤란로 152", FakeResp(body([], code="E0001", msg="승인되지 않은 KEY 입니다.")))
        self.assertFailed(r, API_UNAVAILABLE)

    def test_system_error_is_api_unavailable(self):
        r, _ = run("테헤란로 152", FakeResp(body([], code="-999", msg="시스템에러")))
        self.assertFailed(r, API_UNAVAILABLE)

    def test_network_error_retries_then_fails(self):
        err = requests.ConnectionError("https://x?confmKey=SECRET")
        r, s = run("테헤란로 152", err, err)
        self.assertFailed(r, API_UNAVAILABLE)
        self.assertEqual(len(s.calls), 2)
        self.assertNotIn("SECRET", r["reason"])

    def test_network_error_then_success(self):
        r, s = run("테헤란로 152", requests.Timeout(), FakeResp(body([juso()])))
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(s.calls), 2)

    def test_http_500_is_api_unavailable(self):
        r, _ = run("테헤란로 152", FakeResp(status=503), FakeResp(status=503))
        self.assertFailed(r, API_UNAVAILABLE)

    def test_bad_json_is_parse_failed(self):
        r, _ = run("테헤란로 152", FakeResp(bad_json=True))
        self.assertFailed(r, PARSE_FAILED)

    def test_missing_common_is_parse_failed(self):
        r, _ = run("테헤란로 152", FakeResp({"foo": 1}))
        self.assertFailed(r, PARSE_FAILED)

    def test_bad_adm_code_is_parse_failed(self):
        r, _ = run("테헤란로 152", FakeResp(body([juso(adm="1168")])))
        self.assertFailed(r, PARSE_FAILED)

    def test_missing_key_is_api_unavailable(self):
        with mock.patch.object(juso_client, "load_dotenv"), mock.patch.dict("os.environ", {}, clear=True):
            r = resolve_address("테헤란로 152", session=FakeSession())
        self.assertFailed(r, API_UNAVAILABLE)


class SplitUnitTests(unittest.TestCase):
    def test_cases(self):
        cases = {
            "테헤란로 152 101동 1203호": ("테헤란로 152", "101", "1203"),
            "화곡동 355-14 B동 401호": ("화곡동 355-14", "B", "401"),
            "화곡동 355-14 401호": ("화곡동 355-14", None, "401"),
            "화곡동 355-14, 제1동 제201호": ("화곡동 355-14", "1", "201"),
            "화곡동 355-14 가동 201호": ("화곡동 355-14", "가", "201"),
            "화곡동 355-14": ("화곡동 355-14", None, None),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(split_unit(text), expected)


class CacheTests(unittest.TestCase):
    def test_cache_skips_second_call(self):
        cache = SQLiteAddressCache(":memory:")
        s = FakeSession(FakeResp(body([juso()])))
        r1 = resolve_address("테헤란로 152", api_key="T", session=s, cache=cache)
        r2 = resolve_address("테헤란로  152", api_key="T", session=s, cache=cache)
        self.assertEqual(len(s.calls), 1)
        self.assertEqual(r1["address"]["address_key"], r2["address"]["address_key"])

    def test_errors_not_cached(self):
        cache = SQLiteAddressCache(":memory:")
        s = FakeSession(FakeResp(body([], code="-999", msg="x")), FakeResp(body([juso()])))
        r1 = resolve_address("테헤란로 152", api_key="T", session=s, cache=cache)
        r2 = resolve_address("테헤란로 152", api_key="T", session=s, cache=cache)
        self.assertEqual((r1["status"], r2["status"]), ("failed", "ok"))

    def test_expired_entry_ignored(self):
        cache = SQLiteAddressCache(":memory:", ttl_days=0)
        cache.save("k", 1, [juso()])
        with mock.patch("document.address.cache.time.time", return_value=10**12):
            self.assertIsNone(cache.get("k"))


if __name__ == "__main__":
    unittest.main()
