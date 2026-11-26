"""오프라인 테스트 (API 호출 없음).

실행: python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))  # 저장소 루트

from document.price.estimator import (  # noqa: E402
    INSUFFICIENT_SAMPLES,
    NO_TRADES_IN_DONG,
    NO_TRADES_IN_REGION,
    BUILD_YEAR_UNKNOWN,
    BUILDING_NOT_IDENTIFIED,
    MATCH_AMBIGUOUS,
    NO_BUILDING_TRADES,
    MATCH_EXACT,
    MATCH_PARTIAL,
    ONLY_BULK_TRADES,
    assess_jeonse,
    calc_jeonse_ratio,
    estimate_from_trades,
    estimate_price,
)
from document.price.rtms_client import (  # noqa: E402
    RTMSApiError,
    Trade,
    fetch_trades,
    parse_amount,
    parse_response,
    recent_months,
)


def item(name_tag, name, dong, jibun, area, amount, ymd=(2026, 10, 5), cdeal="", house_type=None):
    y, m, d = ymd
    ht = f"<houseType>{house_type}</houseType>" if house_type is not None else ""
    return (
        f"<item><{name_tag}>{name}</{name_tag}><umdNm>{dong}</umdNm><jibun>{jibun}</jibun>{ht}"
        f"<excluUseAr>{area}</excluUseAr><dealAmount>{amount}</dealAmount>"
        f"<dealYear>{y}</dealYear><dealMonth>{m}</dealMonth><dealDay>{d}</dealDay>"
        f"<floor>5</floor><cdealType>{cdeal}</cdealType></item>"
    )


def response(items, total=None, code="000"):
    total = len(items) if total is None else total
    return (
        "<?xml version='1.0' encoding='UTF-8'?><response>"
        f"<header><resultCode>{code}</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><items>{''.join(items)}</items><numOfRows>1000</numOfRows>"
        f"<pageNo>1</pageNo><totalCount>{total}</totalCount></body></response>"
    )


def T(name, dong, area, price, jibun="1", d=date(2026, 10, 1), ptype="apt", year=2000):
    return Trade(ptype, name, dong, jibun, area, price, d, "3", build_year=year)


class ParseTests(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(parse_amount("63,400"), 63400)
        self.assertEqual(parse_amount("  125,000 "), 125000)
        self.assertEqual(parse_amount("9500"), 9500)
        with self.assertRaises(ValueError):
            parse_amount("")

    def test_parse_apt_and_skip_cancelled(self):
        xml = response([
            item("aptNm", "은마", "대치동", "316", "76.79", "  245,000"),
            item("aptNm", "은마", "대치동", "316", "76.79", "250,000", cdeal="O"),
        ])
        trades, total = parse_response(xml, "아파트")
        self.assertEqual(total, 2)
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual((t.building_name, t.dong, t.price, t.area), ("은마", "대치동", 245000, 76.79))
        self.assertEqual(t.deal_date, date(2026, 10, 5))

    def test_parse_officetel_and_rowhouse_name_fields(self):
        o, _ = parse_response(response([item("offiNm", "A오피스텔", "역삼동", "1", "30", "30,000")]), "officetel")
        r, _ = parse_response(
            response([
                item("mhouseNm", "B빌라", "화곡동", "2", "45", "20,000", house_type="다세대"),
                item("mhouseNm", "C연립", "화곡동", "3", "60", "30,000", house_type="연립"),
            ]),
            "연립다세대",
        )
        self.assertEqual(o[0].building_name, "A오피스텔")
        self.assertEqual(o[0].house_type, "")
        self.assertEqual([(t.building_name, t.house_type) for t in r], [("B빌라", "다세대"), ("C연립", "연립")])
        self.assertEqual(r[0].to_dict()["house_type"], "다세대")

    def test_rowhouse_endpoint(self):
        s = FakeSession([response([])])
        s.urls = []
        orig = s.get
        s.get = lambda url, **kw: (s.urls.append(url), orig(url, **kw))[1]
        fetch_trades("rowhouse", "11500", "202610", service_key="k", session=s)
        self.assertEqual(
            s.urls[0],
            "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade2/getRTMSDataSvcRHTrade2",
        )

    def test_error_code_raises(self):
        with self.assertRaises(RTMSApiError):
            parse_response(response([], code="03"), "apt")

    def test_gateway_auth_error_raises(self):
        xml = (
            "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
            "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
            "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
        )
        with self.assertRaisesRegex(RTMSApiError, "SERVICE_KEY_IS_NOT_REGISTERED"):
            parse_response(xml, "apt")

    def test_recent_months(self):
        ms = recent_months(12, date(2026, 3, 15))
        self.assertEqual(ms[0], "202603")
        self.assertEqual(ms[-1], "202504")
        self.assertEqual(len(ms), 12)


class FakeResp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return FakeResp(self.pages[params["pageNo"] - 1])


class FetchTests(unittest.TestCase):
    def test_paging(self):
        import document.price.rtms_client as rc
        old = rc.PAGE_SIZE
        rc.PAGE_SIZE = 1
        try:
            s = FakeSession([
                response([item("aptNm", "A", "대치동", "1", "80", "100,000")], total=2),
                response([item("aptNm", "B", "대치동", "2", "80", "110,000")], total=2),
            ])
            trades = fetch_trades("apt", "11680", "202610", service_key="k", session=s)
        finally:
            rc.PAGE_SIZE = old
        self.assertEqual([t.building_name for t in trades], ["A", "B"])
        self.assertEqual(len(s.calls), 2)
        self.assertEqual(s.calls[0]["LAWD_CD"], "11680")

    def test_bad_lawd_cd(self):
        with self.assertRaises(ValueError):
            fetch_trades("apt", "1168", "202610", service_key="k", session=FakeSession([]))


class EstimateTests(unittest.TestCase):
    TRADES = [
        T("래미안대치팰리스", "대치동", 84.9, 300000),
        T("래미안대치팰리스", "대치동", 84.97, 310000),
        T("래미안대치팰리스", "대치동", 114.0, 400000),
        T("은마", "대치동", 76.79, 245000, jibun="316"),
        T("은마", "대치동", 84.43, 260000, jibun="316"),
        T("개포자이", "개포동", 84.0, 280000),
    ]

    def est(self, building, area, dong="대치동", **kw):
        return estimate_from_trades(self.TRADES, dong, building, area, **kw)

    def test_tier1_same_building_similar_area(self):
        e = self.est("래미안 대치 팰리스", 84.95)
        self.assertEqual(e.status, "estimated")
        self.assertEqual(e.basis, "same_building_similar_area")
        self.assertEqual(e.price, 305000)
        self.assertEqual(e.sample_count, 2)

    def test_tier2_same_building_any_area(self):
        e = self.est("래미안대치팰리스", 59.0)
        self.assertEqual(e.basis, "same_building_any_area")
        unit = sorted([300000 / 84.9, 310000 / 84.97, 400000 / 114.0])[1]
        self.assertEqual(e.price, round(unit * 59.0))

    def test_tier1_by_jibun(self):
        e = self.est("316", 76.79)
        self.assertEqual(e.basis, "same_building_similar_area")
        self.assertEqual(e.price, 245000)

    def test_tier3_same_dong_similar_area(self):
        # 은마는 2건뿐이고 84.0㎡ ±5%에는 84.43 1건 -> 1단계 성립. 90㎡로 1·2단계를 피한다
        e = self.est("은마", 90.0)
        self.assertEqual(e.basis, "same_dong_similar_area")
        # 대치동 90㎡ ±10%(81~99): 300000(84.9), 310000(84.97), 260000(84.43)
        self.assertEqual(e.price, 300000)
        self.assertEqual(e.build_year, 2000)

    def test_tier4_same_dong_any_area(self):
        e = self.est("은마", 200.0)
        self.assertEqual(e.basis, "same_dong_any_area")
        self.assertEqual(e.sample_count, 5)

    def test_dong_name_without_suffix(self):
        self.assertEqual(self.est("은마", 76.79, dong="대치").basis, "same_building_similar_area")

    def test_no_trades_in_region(self):
        e = estimate_from_trades([], "대치동", "은마", 76.79, period=("2025-12-01", "2026-11-25"))
        self.assertEqual(e.status, "no_price")
        self.assertIsNone(e.price)
        self.assertEqual(e.reason_code, NO_TRADES_IN_REGION)
        self.assertIn("2025-12-01", e.reason)

    def test_no_trades_in_dong(self):
        e = self.est("은마", 76.79, dong="도곡동")
        self.assertEqual(e.status, "no_price")
        self.assertEqual(e.reason_code, NO_TRADES_IN_DONG)
        self.assertIn("도곡동", e.reason)

    def test_insufficient_samples(self):
        e = estimate_from_trades(self.TRADES, "개포동", "개포자이", 84.0, min_samples=3)
        self.assertEqual(e.status, "no_price")
        self.assertEqual(e.reason_code, INSUFFICIENT_SAMPLES)

    def test_invalid_area(self):
        with self.assertRaises(ValueError):
            self.est("은마", 0)


def B(name, area, price, d=date(2026, 10, 2), gbn="직거래", buyer="법인", seller="법인", dong="논현동", jibun="236-8", year=2015):
    return Trade("officetel", name, dong, jibun, area, price, d, "5",
                 dealing_gbn=gbn, buyer_gbn=buyer, seller_gbn=seller, build_year=year)


class BulkTradeTests(unittest.TestCase):
    def test_bulk_group_excluded_and_counted(self):
        bulk = [B("폴스타인 논현", 38.33, 200000)] + [B("폴스타인 논현", 30.0, 10000) for _ in range(3)]
        normal = [
            B("폴스타인 논현", 30.0, 30000, d=date(2026, 9, 1), gbn="중개거래", buyer="개인", seller="개인"),
            B("폴스타인 논현", 30.2, 32000, d=date(2026, 8, 1), gbn="중개거래", buyer="개인", seller="개인"),
        ]
        other = [B("다른오피스텔", 30.0, 9000, jibun="1")] * 3  # 같은 동, 다른 건물의 일괄거래
        e = estimate_from_trades(bulk + normal + other, "논현동", "폴스타인 논현", 30.0)
        self.assertEqual(e.basis, "same_building_similar_area")
        self.assertEqual(e.price, 31000)
        self.assertEqual(e.sample_count, 2)
        self.assertEqual(e.bulk_excluded_count, 3)  # 같은 건물·비슷한 면적 범위 안에서 뺀 건수 (38.33㎡ 제외)
        self.assertEqual(e.bulk_excluded_total, 7)
        self.assertEqual(e.to_dict()["bulk_excluded_count"], 3)

    def test_same_day_individual_brokered_trades_kept(self):
        trades = [B("은마", 76.79, 310000 + i, gbn="중개거래", buyer="개인", seller="개인") for i in range(4)]
        e = estimate_from_trades(trades, "논현동", "은마", 76.79)
        self.assertEqual(e.sample_count, 4)
        self.assertEqual(e.bulk_excluded_total, 0)

    def test_two_same_day_direct_trades_not_bulk(self):
        trades = [B("A", 30.0, 30000, buyer="개인"), B("A", 30.0, 31000, buyer="개인")]
        e = estimate_from_trades(trades, "논현동", "A", 30.0)
        self.assertEqual(e.sample_count, 2)
        self.assertEqual(e.bulk_excluded_total, 0)

    def test_filter_can_be_disabled(self):
        trades = [B("A", 30.0, 30000) for _ in range(3)]
        e = estimate_from_trades(trades, "논현동", "A", 30.0, bulk_min_count=None)
        self.assertEqual(e.sample_count, 3)
        self.assertEqual(e.bulk_excluded_total, 0)

    def test_only_bulk_trades_in_dong(self):
        trades = [B("A", 30.0, 30000) for _ in range(3)] + [B("X", 30.0, 1, dong="역삼동", gbn="중개거래", buyer="개인", seller="개인")]
        e = estimate_from_trades(trades, "논현동", "A", 30.0)
        self.assertEqual(e.status, "no_price")
        self.assertEqual(e.reason_code, ONLY_BULK_TRADES)
        self.assertEqual(e.bulk_excluded_count, 3)
        self.assertIn("일괄거래", e.reason)

    def test_parse_reads_bulk_fields(self):
        xml = response([item("offiNm", "A", "논현동", "1", "30", "30,000")]).replace(
            "</cdealType>", "</cdealType><dealingGbn>직거래</dealingGbn><buyerGbn>법인</buyerGbn><slerGbn>개인</slerGbn>"
        )
        t = parse_response(xml, "officetel")[0][0]
        self.assertEqual((t.dealing_gbn, t.buyer_gbn, t.seller_gbn), ("직거래", "법인", "개인"))


class BuildingMatchTests(unittest.TestCase):
    TRADES = [
        T("강남역 쉐르빌", "역삼동", 30.0, 30000, jibun="832-3"),
        T("강남역 쉐르빌", "역삼동", 30.1, 31000, jibun="832-3"),
        T("강남역 와이즈 플레이스", "역삼동", 30.0, 50000, jibun="837-13"),
        T("강남역 센트럴 푸르지오 시티", "역삼동", 30.0, 40000, jibun="825-20"),
        T("쉐르빌", "역삼동", 30.0, 99000, jibun="1"),
    ]

    def test_ambiguous_without_year_is_no_price(self):
        e = estimate_from_trades(self.TRADES, "역삼동", "강남", 30.0)
        self.assertEqual(e.status, "no_price")
        self.assertEqual(e.reason_code, BUILDING_NOT_IDENTIFIED)
        self.assertEqual(len(e.building_candidates), 3)

    def test_ambiguous_partial_name_skips_building_tiers(self):
        e = estimate_from_trades(self.TRADES, "역삼동", "강남", 30.0, build_year=2000)
        self.assertEqual(e.building_match, MATCH_AMBIGUOUS)
        self.assertEqual(e.basis, "same_dong_similar_area")
        self.assertEqual(len(e.building_candidates), 3)
        self.assertEqual(e.confidence, "low")
        self.assertTrue(any("3곳" in n for n in e.notes))

    def test_exact_name_wins_over_partial(self):
        # "쉐르빌"은 "강남역 쉐르빌"에도 부분 일치하지만, 정확히 같은 "쉐르빌"만 쓴다
        e = estimate_from_trades(self.TRADES, "역삼동", "쉐르빌", 30.0)
        self.assertEqual(e.building_match, MATCH_EXACT)
        self.assertEqual(e.price, 99000)

    def test_single_partial_match_accepted(self):
        e = estimate_from_trades(self.TRADES, "역삼동", "와이즈", 30.0)
        self.assertEqual(e.building_match, MATCH_PARTIAL)
        self.assertEqual(e.price, 50000)
        self.assertEqual(e.confidence, "low")  # 1건뿐

    def test_confidence_high_with_two_same_building(self):
        e = estimate_from_trades(self.TRADES, "역삼동", "강남역 쉐르빌", 30.0)
        self.assertEqual(e.confidence, "high")
        self.assertEqual(e.to_dict()["confidence_label"], "높음")


class WeakTierTests(unittest.TestCase):
    def test_single_other_area_trade_not_extrapolated(self):
        # 폴스타인 논현 사례: 같은 건물에 다른 면적 거래 1건뿐이면 ㎡당 단가 환산을 하지 않는다
        trades = [T("폴스타인 논현", "논현동", 38.33, 60000)] + [
            T(f"다른{i}", "논현동", 25.0, 23000 + i * 100, jibun=str(i + 10)) for i in range(3)
        ]
        e = estimate_from_trades(trades, "논현동", "폴스타인 논현", 25.0)
        self.assertEqual(e.basis, "same_dong_similar_area")
        self.assertEqual(e.price, 23100)
        self.assertTrue(any("1건뿐" in n for n in e.notes))

    def test_dong_tier_needs_three(self):
        trades = [T("A", "논현동", 40.0, 23000), T("B", "논현동", 25.0, 24000, jibun="2")]
        e = estimate_from_trades(trades, "논현동", "A", 25.0)
        self.assertEqual(e.status, "no_price")
        self.assertEqual(e.reason_code, INSUFFICIENT_SAMPLES)

    def test_corp_to_corp_direct_single_trade_excluded(self):
        polstein = B("폴스타인 논현", 38.33, 200000, d=date(2026, 10, 7))  # 직거래, 법인-법인
        others = [B(f"다른{i}", 25.0, 23000, gbn="중개거래", buyer="개인", seller="개인", jibun=str(i)) for i in range(3)]
        e = estimate_from_trades([polstein] + others, "논현동", "폴스타인 논현", 25.0,
                                 period=("2025-12-01", "2026-11-25"))
        # 같은 건물 거래가 제외돼서 0건, 2015년 구축 -> 같은 동 비슷한 연식으로 추정
        self.assertEqual(e.status, "estimated")
        self.assertEqual(e.basis, "same_dong_similar_area")
        self.assertEqual(e.price, 23000)
        self.assertEqual(e.bulk_excluded_total, 1)
        self.assertTrue(any("일괄거래로 판단돼 제외" in n for n in e.notes))

    def test_corp_direct_with_individual_kept(self):
        t = B("A", 30.0, 30000, buyer="개인")  # 직거래지만 매수인이 개인
        e = estimate_from_trades([t], "논현동", "A", 30.0)
        self.assertEqual(e.sample_count, 1)
        self.assertEqual(e.bulk_excluded_total, 0)


class NewBuildTests(unittest.TestCase):
    P = ("2025-12-01", "2026-11-25")
    DONG = [T(f"이웃{i}", "화곡동", 45.0, 20000 + i * 100, jibun=str(i + 10), year=2012) for i in range(3)]

    def test_zero_trades_new_building_is_no_price(self):
        e = estimate_from_trades(self.DONG, "화곡동", "신축빌라", 45.0, period=self.P, build_year=2024)
        self.assertEqual(e.status, "no_price")
        self.assertIsNone(e.price)
        self.assertEqual(e.reason_code, NO_BUILDING_TRADES)
        self.assertTrue(e.reason.startswith("신축 등으로 시세 확인 불가"))
        self.assertTrue(e.is_new_building)

    def test_zero_trades_old_building_uses_dong_similar_year(self):
        e = estimate_from_trades(self.DONG, "화곡동", "구축빌라", 45.0, period=self.P, build_year=2010)
        self.assertEqual(e.status, "estimated")
        self.assertEqual(e.basis, "same_dong_similar_area")
        self.assertEqual(e.price, 20100)
        self.assertEqual(e.confidence, "low")

    def test_zero_trades_old_building_no_similar_year(self):
        e = estimate_from_trades(self.DONG, "화곡동", "구축빌라", 45.0, period=self.P, build_year=1995)
        self.assertEqual(e.reason_code, INSUFFICIENT_SAMPLES)

    def test_zero_trades_unknown_year(self):
        e = estimate_from_trades(self.DONG, "화곡동", "어떤빌라", 45.0, period=self.P)
        self.assertEqual(e.reason_code, BUILD_YEAR_UNKNOWN)

    def test_dong_tier_uses_only_similar_build_year(self):
        trades = [
            T("신축빌라", "화곡동", 60.0, 40000, year=2025),  # 같은 건물, 면적이 달라 1·2단계 불가
            T("A", "화곡동", 45.0, 35000, jibun="2", year=2022),
            T("B", "화곡동", 45.0, 36000, jibun="3", year=2021),
            T("C", "화곡동", 45.0, 37000, jibun="4", year=2020),
            T("옛빌라", "화곡동", 45.0, 15000, jibun="5", year=1995),
            T("옛빌라2", "화곡동", 45.0, 16000, jibun="6", year=2019),  # 6년 차이 -> 제외
        ]
        e = estimate_from_trades(trades, "화곡동", "신축빌라", 45.0)
        self.assertEqual(e.basis, "same_dong_similar_area")
        self.assertEqual(e.build_year, 2025)
        self.assertEqual(e.sample_count, 3)
        self.assertEqual(e.price, 36000)

    def test_build_year_argument_overrides(self):
        trades = [T("X", "화곡동", 60.0, 40000, year=None)] + [
            T(f"A{i}", "화곡동", 45.0, 30000 + i, jibun=str(i + 2), year=2010) for i in range(3)
        ]
        e = estimate_from_trades(trades, "화곡동", "X", 45.0)
        self.assertEqual(e.status, "no_price")  # 건축년도 모름 -> 같은 동 추정 안 함
        self.assertTrue(any("건축년도를 몰라" in n for n in e.notes))
        e = estimate_from_trades(trades, "화곡동", "X", 45.0, build_year=2012)
        self.assertEqual(e.basis, "same_dong_similar_area")

    def test_same_name_different_jibun_is_ambiguous(self):
        trades = [
            T("위하우스", "화곡동", 26.2, 21000, jibun="163-7", year=2026),
            T("위하우스", "화곡동", 26.2, 15000, jibun="355-14", year=2015),
        ]
        e = estimate_from_trades(trades, "화곡동", "위하우스", 26.2)
        self.assertEqual(e.reason_code, BUILDING_NOT_IDENTIFIED)
        self.assertIn("위하우스 (지번 163-7, 2026년)", e.building_candidates)
        e = estimate_from_trades(trades, "화곡동", "163-7", 26.2)
        self.assertEqual(e.price, 21000)

    def test_bulk_excluded_new_building_not_confused_with_old_namesake(self):
        # 신축 위하우스(163-7) 거래는 모두 일괄거래로 빠지고, 같은 이름의 2015년 건물만 남는 경우
        new = [B("위하우스", 26.2, 24000, dong="화곡동", jibun="163-7", year=2026) for _ in range(3)]
        old = [T("위하우스", "화곡동", 26.2, 15000, jibun="355-14", year=2015)]
        e = estimate_from_trades(new + old, "화곡동", "위하우스", 26.2)
        self.assertEqual(e.reason_code, BUILDING_NOT_IDENTIFIED)
        e = estimate_from_trades(new + old, "화곡동", "163-7", 26.2)
        self.assertEqual(e.reason_code, NO_BUILDING_TRADES)
        self.assertEqual(e.build_year, 2026)

    def test_parse_build_year(self):
        xml = response([item("mhouseNm", "B빌라", "화곡동", "2", "45", "20,000", house_type="다세대")]).replace(
            "</cdealType>", "</cdealType><buildYear>2025</buildYear>"
        )
        self.assertEqual(parse_response(xml, "rowhouse")[0][0].build_year, 2025)


class NewBuildingWarningTests(unittest.TestCase):
    PERIOD = ("2025-12-01", "2026-11-25")

    def dong_trades(self, price=30000, year=2023):
        return [T(f"이웃{i}", "화곡동", 45.0, price + i * 100, jibun=str(i + 10), year=year) for i in range(3)]

    def test_new_building_few_trades_is_medium(self):
        trades = [T("신축", "화곡동", 45.0, 32000, year=2025)] + self.dong_trades()
        e = estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD)
        self.assertTrue(e.is_new_building)
        self.assertEqual(e.confidence, "medium")
        self.assertEqual(e.to_dict()["confidence_label"], "중간")
        self.assertEqual(e.warnings, [])
        self.assertEqual(e.dong_reference_price, 30100)

    def test_inflation_warning_over_30_percent(self):
        trades = [T("신축", "화곡동", 45.0, 40000, year=2025)] + self.dong_trades()  # 30100 대비 +33%
        e = estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD)
        self.assertEqual(e.warnings, ["PRICE_INFLATION_SUSPECTED"])
        self.assertTrue(e.warning_messages[0].startswith("매매가 부풀림 의심"))

    def test_no_warning_at_30_percent_or_lower_price(self):
        trades = [T("신축", "화곡동", 45.0, 39000, year=2025)] + self.dong_trades()  # +29.6%
        self.assertEqual(estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD).warnings, [])
        trades = [T("신축", "화곡동", 45.0, 10000, year=2025)] + self.dong_trades()  # 훨씬 낮음
        self.assertEqual(estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD).warnings, [])

    def test_reference_uses_similar_year_only(self):
        trades = [T("신축", "화곡동", 45.0, 40000, year=2025)] + self.dong_trades(year=1995)
        e = estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD)
        self.assertEqual(e.warnings, [])
        self.assertIsNone(e.dong_reference_price)
        self.assertTrue(any("부풀림 여부는 확인하지 못했습니다" in n for n in e.notes))

    def test_new_building_with_three_trades_still_checked(self):
        trades = [T("신축", "화곡동", 45.0, 40000, year=2025, d=date(2026, m, 1)) for m in (3, 4, 5)] + self.dong_trades()
        e = estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD)
        self.assertEqual(e.confidence, "high")
        self.assertEqual(e.warnings, ["PRICE_INFLATION_SUSPECTED"])

    def test_public_buyer_only_not_compared(self):
        trades = [B("신축", 45.0, 40000 + i, dong="화곡동", jibun="9", buyer="공공기관", seller="법인", year=2025,
                    d=date(2026, 3, 4)) for i in range(3)] + self.dong_trades()
        e = estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD)
        self.assertEqual(e.status, "estimated")
        self.assertEqual(e.warnings, [])
        self.assertTrue(any("공공기관 매수라 부풀림 비교" in n for n in e.notes))

    def test_compares_price_per_m2(self):
        # 이웃 거래는 면적이 커서 총액은 높지만 ㎡당 가격은 낮다 -> ㎡당으로 비교해야 경고가 맞게 나온다
        trades = [T("신축", "화곡동", 40.0, 40000, year=2025)] + [
            T(f"이웃{i}", "화곡동", 44.0, 33000, jibun=str(i + 10), year=2023) for i in range(3)
        ]
        e = estimate_from_trades(trades, "화곡동", "신축", 40.0, period=self.PERIOD)
        # ㎡당 1000 vs 750 -> +33% (총액으로는 40000 vs 33000 = +21%라 경고가 안 났을 것)
        self.assertEqual(e.warnings, ["PRICE_INFLATION_SUSPECTED"])
        self.assertEqual(e.price_per_m2, 1000.0)
        self.assertEqual(e.dong_reference_price_per_m2, 750.0)

    def test_comparison_uses_three_year_range(self):
        trades = [T("신축", "화곡동", 45.0, 40000, year=2025)] + self.dong_trades(year=2021)  # 4년 차이
        e = estimate_from_trades(trades, "화곡동", "신축", 45.0, period=self.PERIOD)
        self.assertIsNone(e.dong_reference_price)
        self.assertEqual(e.warnings, [])

    def test_old_building_single_trade_still_low(self):
        trades = [T("구축", "화곡동", 45.0, 40000, year=2010)] + self.dong_trades(year=2010)
        e = estimate_from_trades(trades, "화곡동", "구축", 45.0, period=self.PERIOD)
        self.assertFalse(e.is_new_building)
        self.assertEqual(e.confidence, "low")


class PublicBuyerTests(unittest.TestCase):
    def test_public_buyer_bulk_kept_in_price(self):
        trades = [B("레인트리", 48.22, 40000 + i * 100, dong="화곡동", buyer="공공기관", seller="법인", year=2026)
                  for i in range(5)]
        e = estimate_from_trades(trades, "화곡동", "레인트리", 48.22, period=("2025-12-01", "2026-11-25"))
        self.assertEqual(e.status, "estimated")
        self.assertEqual(e.sample_count, 5)
        self.assertEqual(e.bulk_excluded_total, 0)

    def test_private_bulk_in_same_group_still_excluded(self):
        trades = [B("A", 30.0, 30000, buyer="공공기관")] + [B("A", 30.0, 10000) for _ in range(3)]
        e = estimate_from_trades(trades, "논현동", "A", 30.0)
        self.assertEqual(e.sample_count, 1)
        self.assertEqual(e.price, 30000)
        self.assertEqual(e.bulk_excluded_total, 3)


class RetryTests(unittest.TestCase):
    def setUp(self):
        import document.price.rtms_client as rc
        self.rc, self.old_wait = rc, rc.RETRY_WAIT
        rc.RETRY_WAIT = 0

    def tearDown(self):
        self.rc.RETRY_WAIT = self.old_wait

    def test_retry_once_then_success(self):
        import requests
        ok = response([item("aptNm", "A", "대치동", "1", "80", "100,000")])

        class Flaky:
            calls = 0

            def get(self, url, params=None, timeout=None):
                Flaky.calls += 1
                if Flaky.calls == 1:
                    raise requests.ConnectionError("끊김")
                return FakeResp(ok)

        trades = fetch_trades("apt", "11680", "202610", service_key="k", session=Flaky())
        self.assertEqual(len(trades), 1)
        self.assertEqual(Flaky.calls, 2)

    def test_gives_korean_error_after_retries(self):
        import requests

        class Down:
            def get(self, url, params=None, timeout=None):
                raise requests.Timeout()

        with self.assertRaisesRegex(RTMSApiError, "아파트 202610 거래 조회 실패.*2번 시도"):
            fetch_trades("apt", "11680", "202610", service_key="k", session=Down())

    def test_server_error_retried(self):
        ok = response([])
        pages = [FakeResp("", 503), FakeResp(ok)]

        class S:
            def get(self, url, params=None, timeout=None):
                return pages.pop(0)

        self.assertEqual(fetch_trades("apt", "11680", "202610", service_key="k", session=S()), [])


class JeonseTests(unittest.TestCase):
    def test_ratio(self):
        self.assertAlmostEqual(calc_jeonse_ratio(24000, 30000), 0.8)
        self.assertIsNone(calc_jeonse_ratio(24000, None))

    def test_assess_estimated(self):
        trades = [T("은마", "대치동", 76.79, 250000)]
        r = assess_jeonse("apt", "11680", "대치동", "은마", 76.79, 200000,
                          trades=trades, today=date(2026, 11, 25))
        self.assertEqual(r["status"], "estimated")
        self.assertEqual(r["estimated_price"], 250000)
        self.assertEqual(r["jeonse_ratio"], 0.8)
        self.assertEqual(r["jeonse_ratio_pct"], 80.0)
        self.assertEqual(r["estimate"]["period"], {"start": "2025-12-01", "end": "2026-11-25"})

    def test_assess_no_price_returns_reason(self):
        r = assess_jeonse("apt", "11680", "대치동", "은마", 76.79, 200000,
                          trades=[], today=date(2026, 11, 25))
        self.assertEqual(r["status"], "no_price")
        self.assertIsNone(r["estimated_price"])
        self.assertIsNone(r["jeonse_ratio"])
        self.assertEqual(r["reason_code"], NO_TRADES_IN_REGION)
        self.assertIn("11680", r["reason"])
        self.assertIn("아파트", r["reason"])

    def test_estimate_price_uses_fetcher(self):
        seen = {}

        def fake_fetcher(ptype, lawd_cd, months, today):
            seen.update(ptype=ptype, lawd_cd=lawd_cd, months=months)
            return [T("A오피스텔", "역삼동", 30.0, 30000, ptype="officetel")]

        e = estimate_price("오피스텔", "11680", "역삼동", "A오피스텔", 30.0, fetcher=fake_fetcher)
        self.assertEqual(seen, {"ptype": "officetel", "lawd_cd": "11680", "months": 12})
        self.assertEqual(e.price, 30000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
