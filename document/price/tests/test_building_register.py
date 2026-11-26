"""건축물대장 모듈 오프라인 테스트 (API 호출 없음).

실행: python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))  # 저장소 루트

from document.price.building_register import (  # noqa: E402
    CHECK_UNIT_PURPOSE,
    FLAG_NON_RESIDENTIAL,
    BuildingInfo,
    BuildingRegisterError,
    fetch_building_info,
    is_residential_purpose,
    parse_jibun,
    split_bjdong_code,
)
from document.price.estimator import BUILD_YEAR_UNKNOWN, NO_BUILDING_TRADES, estimate_price  # noqa: E402
from document.price.rtms_client import Trade  # noqa: E402


def title(dong="", use_apr="20150518", purps_cd="02000", purps="공동주택", etc="다세대주택", main_atch="0"):
    return (
        f"<item><platPlc>서울특별시 강서구 화곡동 355-14번지</platPlc><bldNm>위하우스</bldNm>"
        f"<dongNm>{dong}</dongNm><mainAtchGbCd>{main_atch}</mainAtchGbCd><useAprDay>{use_apr}</useAprDay>"
        f"<mainPurpsCd>{purps_cd}</mainPurpsCd><mainPurpsCdNm>{purps}</mainPurpsCdNm><etcPurps>{etc}</etcPurps></item>"
    )


def unit(ho, purps_cd, purps, gb="전유", dong=""):
    return (
        f"<item><dongNm>{dong}</dongNm><hoNm>{ho}</hoNm><exposPubuseGbCdNm>{gb}</exposPubuseGbCdNm>"
        f"<mainPurpsCd>{purps_cd}</mainPurpsCd><mainPurpsCdNm>{purps}</mainPurpsCdNm><etcPurps>{purps}</etcPurps></item>"
    )


def resp(items, code="00"):
    return (
        f"<response><header><resultCode>{code}</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><items>{''.join(items)}</items><totalCount>{len(items)}</totalCount></body></response>"
    )


class FakeResp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class FakeSession:
    def __init__(self, by_op):
        self.by_op, self.calls = by_op, []

    def get(self, url, params=None, timeout=None):
        op = url.rsplit("/", 1)[1]
        self.calls.append((op, params))
        return FakeResp(self.by_op[op])


class ParseTests(unittest.TestCase):
    def test_parse_jibun(self):
        self.assertEqual(parse_jibun("355-14"), ("0", "0355", "0014"))
        self.assertEqual(parse_jibun("316"), ("0", "0316", "0000"))
        self.assertEqual(parse_jibun("산 12-3"), ("1", "0012", "0003"))
        with self.assertRaises(ValueError):
            parse_jibun("강서로 139")

    def test_split_code(self):
        self.assertEqual(split_bjdong_code("1150010300"), ("11500", "10300"))
        self.assertEqual(split_bjdong_code("10300", "11500"), ("11500", "10300"))
        with self.assertRaises(ValueError):
            split_bjdong_code("10300")

    def test_residential(self):
        self.assertTrue(is_residential_purpose("02000", "공동주택", "다세대주택"))
        self.assertTrue(is_residential_purpose("01000", "단독주택", "다가구주택"))
        self.assertTrue(is_residential_purpose("14000", "업무시설", "오피스텔"))
        self.assertFalse(is_residential_purpose("04000", "제2종근린생활시설", "사무소"))
        self.assertFalse(is_residential_purpose("03000", "소매점", "소매점"))


class FetchTests(unittest.TestCase):
    def test_build_year_and_params(self):
        s = FakeSession({"getBrTitleInfo": resp([title("A동"), title("B동")])})
        info = fetch_building_info("1150010300", "355-14", service_key="k", session=s)
        self.assertTrue(info.found)
        self.assertEqual(info.build_year, 2015)
        self.assertTrue(info.is_residential)
        self.assertEqual(info.flags, [])
        self.assertIsNone(info.violation_building)
        p = s.calls[0][1]
        self.assertEqual((p["sigunguCd"], p["bjdongCd"], p["bun"], p["ji"], p["platGbCd"]), ("11500", "10300", "0355", "0014", "0"))

    def test_latest_approval_date_when_dongs_differ(self):
        s = FakeSession({"getBrTitleInfo": resp([title("A동", "20150518"), title("B동", "20240301")])})
        info = fetch_building_info("1150010300", "355-14", service_key="k", session=s)
        self.assertEqual(info.build_year, 2024)

    def test_dong_nm_picks_that_dong(self):
        s = FakeSession({"getBrTitleInfo": resp([title("A동", "20150518"), title("B동", "20240301")])})
        info = fetch_building_info("1150010300", "355-14", dong_nm="A동", service_key="k", session=s)
        self.assertEqual(info.build_year, 2015)

    def test_non_residential_building_flag(self):
        s = FakeSession({"getBrTitleInfo": resp([title(purps_cd="04000", purps="제2종근린생활시설", etc="사무소")])})
        info = fetch_building_info("1150010300", "355-14", service_key="k", session=s)
        self.assertEqual(info.flags, [FLAG_NON_RESIDENTIAL])

    def test_unit_purpose_flag(self):
        s = FakeSession({
            "getBrTitleInfo": resp([title(etc="다세대주택, 근린생활시설")]),
            "getBrExposPubuseAreaInfo": resp([unit("101", "03000", "소매점"), unit("101", "02000", "계단실", gb="공용")]),
        })
        info = fetch_building_info("1150010300", "355-14", ho_nm="101", service_key="k", session=s)
        self.assertTrue(info.is_residential)
        self.assertFalse(info.unit_is_residential)
        self.assertEqual(info.unit_purpose, "소매점")
        self.assertEqual(info.flags, [FLAG_NON_RESIDENTIAL])
        self.assertEqual(s.calls[1][1]["hoNm"], "101")

    def test_same_ho_in_two_dongs_with_different_purpose_needs_check(self):
        s = FakeSession({
            "getBrTitleInfo": resp([title("A동"), title("B동")]),
            "getBrExposPubuseAreaInfo": resp([unit("101", "02000", "다세대주택", dong="A동"),
                                              unit("101", "03000", "소매점", dong="B동")]),
        })
        info = fetch_building_info("1150010300", "355-14", ho_nm="101", service_key="k", session=s)
        self.assertIsNone(info.unit_is_residential)
        self.assertEqual(info.flags, [])  # 첫 결과로 판정하지 않음
        self.assertIn(CHECK_UNIT_PURPOSE, info.checks_needed)
        self.assertTrue(any("A동, B동" in n for n in info.notes))

    def test_same_ho_in_two_dongs_with_same_purpose_is_judged(self):
        s = FakeSession({
            "getBrTitleInfo": resp([title("A동"), title("B동")]),
            "getBrExposPubuseAreaInfo": resp([unit("101", "02000", "다세대주택", dong="A동"),
                                              unit("101", "02000", "다세대주택", dong="B동")]),
        })
        info = fetch_building_info("1150010300", "355-14", ho_nm="101", service_key="k", session=s)
        self.assertTrue(info.unit_is_residential)
        self.assertNotIn(CHECK_UNIT_PURPOSE, info.checks_needed)

    def test_dong_nm_picks_that_unit(self):
        s = FakeSession({
            "getBrTitleInfo": resp([title("A동"), title("B동")]),
            "getBrExposPubuseAreaInfo": resp([unit("101", "02000", "다세대주택", dong="A동"),
                                              unit("101", "03000", "소매점", dong="B동")]),
        })
        info = fetch_building_info("1150010300", "355-14", dong_nm="B동", ho_nm="101", service_key="k", session=s)
        self.assertFalse(info.unit_is_residential)
        self.assertEqual(info.flags, [FLAG_NON_RESIDENTIAL])
        self.assertNotIn(CHECK_UNIT_PURPOSE, info.checks_needed)

    def test_not_found(self):
        s = FakeSession({"getBrTitleInfo": resp([])})
        info = fetch_building_info("1150010300", "9999-99", service_key="k", session=s)
        self.assertFalse(info.found)
        self.assertIsNone(info.build_year)

    def test_error_code(self):
        s = FakeSession({"getBrTitleInfo": resp([], code="03")})
        with self.assertRaises(BuildingRegisterError):
            fetch_building_info("1150010300", "355-14", service_key="k", session=s)


def T(name, area, price, jibun, year, dong="화곡동"):
    return Trade("rowhouse", name, dong, jibun, area, price * 10_000, date(2026, 10, 1), "3", build_year=year)  # 가격은 만원으로 적음


NEIGHBORS = [T(f"이웃{i}", 45.0, 20000 + i * 100, str(i + 10), 2012) for i in range(3)]
NEW_NEIGHBORS = [T(f"신축이웃{i}", 45.0, 30000 + i * 100, str(i + 20), 2024) for i in range(3)]


def fake_register(year, flags=()):
    calls = []

    def f(bjdong_cd, jibun, **kw):
        calls.append((bjdong_cd, jibun, kw))
        return BuildingInfo("11500", "10300", jibun, True, build_year=year, flags=list(flags))

    f.calls = calls
    return f


class EstimateWithRegisterTests(unittest.TestCase):
    def est(self, building, register, **kw):
        return estimate_price("rowhouse", "11500", "화곡동", building, 45.0, trades=NEIGHBORS + NEW_NEIGHBORS,
                              today=date(2026, 11, 25), building_fetcher=register, **kw)

    def test_without_register_unknown(self):
        e = self.est("123-4", fake_register(2012))
        self.assertEqual(e.reason_code, BUILD_YEAR_UNKNOWN)

    def test_register_fills_old_building_year(self):
        reg = fake_register(2012)
        e = self.est("123-4", reg, bjdong_cd="1150010300")
        self.assertEqual(e.status, "estimated")
        self.assertEqual(e.build_year, 2012)
        self.assertEqual(e.build_year_source, "building_register")
        self.assertEqual(e.price, 20100 * 10_000)
        self.assertEqual(reg.calls[0][:2], ("1150010300", "123-4"))

    def test_register_new_building_is_no_price(self):
        e = self.est("123-4", fake_register(2025), bjdong_cd="1150010300")
        self.assertEqual(e.reason_code, NO_BUILDING_TRADES)

    def test_input_build_year_wins(self):
        e = self.est("123-4", fake_register(2025), bjdong_cd="1150010300", build_year=2012)
        self.assertEqual(e.build_year_source, "input")
        self.assertEqual(e.status, "estimated")

    def test_flags_passed_through(self):
        e = self.est("123-4", fake_register(2012, [FLAG_NON_RESIDENTIAL]), bjdong_cd="1150010300")
        self.assertEqual(e.building_flags, [FLAG_NON_RESIDENTIAL])
        self.assertEqual(e.to_dict()["building_flags"], [FLAG_NON_RESIDENTIAL])

    def test_violation_check_always_requested(self):
        for e in (self.est("123-4", fake_register(2012)),
                  self.est("123-4", fake_register(2012), bjdong_cd="1150010300")):
            self.assertEqual(e.checks_needed, ["VIOLATION_BUILDING_CHECK_NEEDED"])
            self.assertTrue(e.to_dict()["check_messages"][0].startswith("위반건축물 여부 확인 필요"))

    def test_jibun_from_trades_when_name_given(self):
        reg = fake_register(2012)
        self.est("이웃0", reg, bjdong_cd="1150010300")
        self.assertEqual(reg.calls[0][1], "10")

    def test_register_failure_does_not_break_estimate(self):
        def broken(*a, **kw):
            raise BuildingRegisterError("점검 중")

        e = self.est("123-4", broken, bjdong_cd="1150010300")
        self.assertEqual(e.reason_code, BUILD_YEAR_UNKNOWN)
        self.assertTrue(any("건축물대장 조회 실패" in n for n in e.notes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
