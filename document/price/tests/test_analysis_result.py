"""팀 분석 결과 형식(docs/analysis-result.md) 변환 테스트 (API 호출 없음).

실행 (저장소 루트에서): python -m unittest discover -s document/price/tests -v
"""

import json
import os
import sys
import unittest
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))  # 저장소 루트
sys.path.insert(0, ROOT)

from document.price.analysis_result import (  # noqa: E402
    ADDRESS_NOT_FOUND,
    API_UNAVAILABLE,
    NO_TRADES,
    PARSE_FAILED,
    analyze_price,
    make_address_key,
)
from document.price.building_register import BuildingInfo  # noqa: E402
from document.price.rtms_client import RTMSApiError, Trade, fetch_recent_trades  # noqa: E402


def load_example(name):
    with open(os.path.join(ROOT, "docs", "examples", name), encoding="utf-8") as f:
        return json.load(f)


OK_EXAMPLE = load_example("analysis-result-ok.json")
FAILED_EXAMPLE = load_example("analysis-result-failed.json")
TODAY = date(2026, 11, 25)


def T(name, area, price_won, jibun, year, dong="가상동", d=date(2026, 10, 1)):
    return Trade("rowhouse", name, dong, jibun, area, price_won, d, "3", build_year=year)


def register(year):
    def f(bjdong_cd, jibun, **kw):
        return BuildingInfo(bjdong_cd[:5], bjdong_cd[5:], jibun, True, build_year=year)
    return f


# 예시 1과 같은 상황: 같은 건물·비슷한 면적 거래 4건, 중앙값 3억
OK_TRADES = [
    T("가상빌라", 29.8, p, "123-4", 2016, d=date(2026, m, 1))
    for p, m in ((290_000_000, 3), (295_000_000, 5), (305_000_000, 7), (310_000_000, 9))
]
# 예시 2와 같은 상황: 2025년 신축, 같은 건물 거래 없음
NEIGHBORS = [T(f"이웃{i}", 24.5, 200_000_000 + i * 1_000_000, str(i + 10), 2015) for i in range(3)]


def run(trades=None, **kw):
    args = dict(property_type="연립다세대", lawd_cd="11500", dong="가상동", building="123-4", area=29.8,
                deposit=200_000_000, today=TODAY, bjdong_cd="1150010300", building_fetcher=register(2016))
    args.update(kw)
    if trades is not None:
        args["trades"] = trades
    return analyze_price(**args)


class OkExampleTests(unittest.TestCase):
    def setUp(self):
        self.r = run(OK_TRADES, senior_amount_used=24_000_000)

    def test_same_keys_as_example(self):
        # other_tenant_deposits, confidence_label은 위험 등급 모듈(document/risk)이 붙이는 칸
        self.assertEqual(set(self.r["price_card"]),
                         set(OK_EXAMPLE["price_card"]) - {"other_tenant_deposits", "confidence_label"})
        self.assertEqual(set(self.r["data_status_item"]), set(OK_EXAMPLE["data_status"]["items"][0]))
        for flag in self.r["flags"]:
            self.assertEqual(set(flag), set(OK_EXAMPLE["flags"][0]))
        self.assertTrue(set(self.r["property"]) <= set(OK_EXAMPLE["property"]))

    def test_price_card_values_match_example(self):
        card, ex = self.r["price_card"], OK_EXAMPLE["price_card"]
        for key in ("deposit", "senior_amount_used", "estimated_price", "sample_count", "method",
                    "method_label", "confidence", "jeonse_ratio", "senior_burden_ratio"):
            self.assertEqual(card[key], ex[key], key)
        self.assertEqual(card["base_date"], "2026-11-25")
        self.assertEqual(card["trade_period"], {"from": "2025-12-01", "to": "2026-11-25"})
        self.assertIsInstance(card["estimated_price"], int)

    def test_status_and_property(self):
        # 거래 목록을 직접 넣어서 API를 부르지 않았으니 data_source는 None (예시는 api)
        self.assertEqual(self.r["data_status_item"], dict(OK_EXAMPLE["data_status"]["items"][0], data_source=None))
        prop, ex = self.r["property"], OK_EXAMPLE["property"]
        for key in ("address_key", "housing_type", "exclusive_area_m2", "build_year"):
            self.assertEqual(prop[key], ex[key], key)

    def test_violation_check_flag_matches_example(self):
        self.assertEqual(self.r["flags"], [OK_EXAMPLE["flags"][1]])

    def test_result_is_json_serializable(self):
        json.dumps(self.r, ensure_ascii=False)


class FailedExampleTests(unittest.TestCase):
    def setUp(self):
        self.r = run(NEIGHBORS, building="456-7", area=24.5, deposit=250_000_000, senior_amount_used=0,
                     building_fetcher=register(2025))

    def test_status_no_trades(self):
        item = self.r["data_status_item"]
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["reason_code"], NO_TRADES)
        self.assertTrue(item["reason"].startswith("신축 등으로 시세 확인 불가"))
        self.assertEqual(self.r["detail"]["reason_code"], "NO_BUILDING_TRADES")

    def test_price_card_nulls_match_example(self):
        card, ex = self.r["price_card"], FAILED_EXAMPLE["price_card"]
        for key in ("deposit", "senior_amount_used", "estimated_price", "sample_count", "method",
                    "method_label", "confidence", "jeonse_ratio", "senior_burden_ratio"):
            self.assertEqual(card[key], ex[key], key)

    def test_flags_match_example(self):
        # SPECIAL_TERMS_CHECK_NEEDED는 위험 등급 모듈이 특약 추출 실패로 붙이는 신호
        price_flags = [f for f in FAILED_EXAMPLE["flags"] if f["code"] != "SPECIAL_TERMS_CHECK_NEEDED"]
        self.assertEqual(self.r["flags"], price_flags)
        self.assertEqual(self.r["property"]["address_key"], "1150010300-0456-0007")
        self.assertEqual(self.r["property"]["build_year"], 2025)


class FailureCodeTests(unittest.TestCase):
    def test_api_unavailable(self):
        def down(*a, **kw):
            raise RTMSApiError("아파트 202611 거래 조회 실패: 10초 안에 응답이 없었습니다")

        r = run(fetcher=down)
        self.assertEqual(r["data_status_item"]["reason_code"], API_UNAVAILABLE)
        self.assertIsNone(r["price_card"]["estimated_price"])
        self.assertIsNone(r["detail"])
        self.assertEqual(r["flags"][-1]["code"], "VIOLATION_BUILDING_CHECK_NEEDED")

    def test_missing_key_is_api_unavailable(self):
        def no_key(*a, **kw):
            raise RuntimeError(".env에 PUBLIC_DATA_API_KEY가 없습니다")

        r = run(fetcher=no_key)
        self.assertEqual(r["data_status_item"]["reason_code"], API_UNAVAILABLE)
        self.assertIn("PUBLIC_DATA_API_KEY", r["data_status_item"]["reason"])

    def test_parse_failed_when_response_is_not_xml(self):
        class Resp:
            status_code, text = 200, "<html>점검 중</html"

        class Session:
            def get(self, url, params=None, timeout=None):
                return Resp()

        def fetcher(ptype, lawd_cd, months, today):
            return fetch_recent_trades(ptype, lawd_cd, months, today, service_key="k", session=Session())

        r = run(fetcher=fetcher)
        self.assertEqual(r["data_status_item"]["reason_code"], PARSE_FAILED)

    def test_bad_lawd_code_is_address_not_found(self):
        r = run(lawd_cd="115")
        self.assertEqual(r["data_status_item"]["reason_code"], ADDRESS_NOT_FOUND)

    def test_building_not_identified_is_address_not_found(self):
        trades = [T("위하우스", 26.2, 210_000_000, "163-7", 2026), T("위하우스", 26.2, 150_000_000, "355-14", 2015)]
        r = run(trades, building="위하우스", area=26.2, bjdong_cd=None)
        self.assertEqual(r["data_status_item"]["reason_code"], ADDRESS_NOT_FOUND)
        self.assertEqual(r["detail"]["reason_code"], "BUILDING_NOT_IDENTIFIED")


class OtherTests(unittest.TestCase):
    def test_senior_unknown_gives_null_ratio(self):
        r = run(OK_TRADES)
        self.assertIsNone(r["price_card"]["senior_amount_used"])
        self.assertIsNone(r["price_card"]["senior_burden_ratio"])
        self.assertEqual(r["price_card"]["jeonse_ratio"], 0.6667)

    def test_inflation_flag(self):
        new = [T("신축", 45.0, 400_000_000, "9", 2025)]
        dong = [T(f"이웃{i}", 45.0, 300_000_000 + i * 1_000_000, str(i + 10), 2023) for i in range(3)]
        r = run(new + dong, building="9", area=45.0, bjdong_cd=None)
        flag = next(f for f in r["flags"] if f["code"] == "PRICE_INFLATION_SUSPECTED")
        self.assertEqual(flag["level"], "주의")
        self.assertEqual(flag["threshold"], 0.3)
        self.assertAlmostEqual(flag["value"], 400 / 301 - 1, places=3)

    def test_non_residential_flag(self):
        def reg(bjdong_cd, jibun, **kw):
            return BuildingInfo("11500", "10300", jibun, True, build_year=2016, flags=["NON_RESIDENTIAL"])

        r = run(OK_TRADES, building_fetcher=reg)
        self.assertIn("NON_RESIDENTIAL", [f["code"] for f in r["flags"]])

    def test_unit_purpose_check_flag(self):
        def reg(bjdong_cd, jibun, **kw):
            info = BuildingInfo("11500", "10300", jibun, True, build_year=2016)
            info.checks_needed.append("UNIT_PURPOSE_CHECK_NEEDED")
            return info

        r = run(OK_TRADES, building_fetcher=reg)
        codes = {f["code"]: f["level"] for f in r["flags"]}
        self.assertEqual(codes["UNIT_PURPOSE_CHECK_NEEDED"], "확인필요")
        self.assertIn("VIOLATION_BUILDING_CHECK_NEEDED", codes)
        self.assertTrue(r["detail"]["check_messages"][1].startswith("호 용도 확인 필요"))

    def test_address_key(self):
        self.assertEqual(make_address_key("1150010300", "355-14"), "1150010300-0355-0014")
        self.assertEqual(make_address_key("1150010300", "316"), "1150010300-0316-0000")
        self.assertIsNone(make_address_key("1150010300", "산 12-3"))  # 산 지번은 키 형식 미정
        self.assertIsNone(make_address_key(None, "316"))
        self.assertIsNone(make_address_key("11500", "316"))

    def test_deposit_must_be_positive(self):
        with self.assertRaises(ValueError):
            run(OK_TRADES, deposit=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
