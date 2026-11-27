"""위험 등급 모듈 테스트 (가상 입력만, 네트워크·PDF 없음).

실행 (저장소 루트에서): python -m unittest discover -s document/risk/tests -v
"""

import copy
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))  # 저장소 루트
sys.path.insert(0, ROOT)

from document.risk.address_match import compare, parse_ho, parse_lot  # noqa: E402
from document.risk import (  # noqa: E402
    RiskConfig,
    address_flags,
    band_level,
    build_analysis_result,
    decide_grade,
    merge_flags,
    ratio_flags,
    special_terms_part,
)

EXAMPLES = os.path.join(ROOT, "docs", "examples")

VIOLATION = {
    "code": "VIOLATION_BUILDING_CHECK_NEEDED", "level": "확인필요", "value": None, "threshold": None,
    "source": "공공데이터 건축물대장 API에 위반건축물 항목 없음, 건축물대장 열람본 확인 필요",
}
OK = {"status": "ok", "reason_code": None, "reason": None}


def load(name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
        return json.load(f)


def flag(code, level, value=None, threshold=None, source="테스트"):
    return {"code": code, "level": level, "value": value, "threshold": threshold, "source": source}


def price_part(*, price=300_000_000, deposit=200_000_000, senior=None, confidence="높음", flags=None,
               status=None):
    """analyze_price() 결과 모양의 가상 입력."""
    jr = None if price is None else round(deposit / price, 4)
    sr = None if price is None or senior is None else round((senior + deposit) / price, 4)
    return {
        "data_status_item": {"part": "price", **(status or OK)},
        "property": {"address_key": "1150010300-0123-0004", "housing_type": "연립다세대",
                     "exclusive_area_m2": 29.8, "build_year": 2016},
        "price_card": {
            "deposit": deposit, "senior_amount_used": senior, "estimated_price": price,
            "sample_count": 4 if price else 0,
            "method": "same_building_similar_area" if price else None,
            "method_label": "같은 건물·비슷한 면적 거래 중앙값" if price else None,
            "base_date": "2026-11-25", "trade_period": {"from": "2025-11-01", "to": "2026-10-31"},
            "confidence": confidence if price else None, "jeonse_ratio": jr, "senior_burden_ratio": sr,
        },
        "flags": [VIOLATION] if flags is None else flags,
        "detail": None,
    }


def registry_part(*, senior=0, flags=None, failed=False):
    """analyze_registry() 결과 모양의 가상 입력."""
    if failed:
        return {"data_status_item": {"part": "registry", "status": "failed", "reason_code": "PARSE_FAILED",
                                     "reason": "등기부를 읽지 못했습니다"},
                "property": None, "senior_amount_used": None, "registry_card": None, "flags": [], "detail": None}
    return {
        "data_status_item": {"part": "registry", **OK},
        "property": {"address_display": "서울특별시 강서구 가상동 123-4", "road_address": None, "unit_no": "401",
                     "exclusive_area_m2": 29.8, "structure": None},
        "senior_amount_used": senior,
        "registry_card": {"senior_amount_total": senior, "senior_amount_complete": senior is not None,
                          "senior_amount_missing_count": 0 if senior is not None else 1,
                          "counts": {"mortgage": 1 if senior else 0}},
        "flags": flags or [], "detail": None,
    }


def terms_ok():
    return {"extraction_status": "ok", "masked": True, "page": 2, "section_text": "1. 특약 문장"}


def full(**kw):
    kw.setdefault("price", price_part())
    kw.setdefault("registry", registry_part())
    kw.setdefault("special_terms", terms_ok())
    return build_analysis_result(analysis_id="t", analyzed_at="2026-11-26T14:00:00+09:00", **kw)


class ExampleContractTest(unittest.TestCase):
    """docs/examples JSON을 가상 부분 결과로 똑같이 만들어 낸다."""

    def test_ok_example(self):
        expected = load("analysis-result-ok.json")
        address = {"status": "ok", "reason_code": None, "reason": None,
                   "address": {"address_key": "1150010300-0123-0004",
                               "jibun_address": "서울특별시 강서구 가상동 123-4 (가상 주소)"}}
        # 선순위는 analyze_price에 넣지 않고 등기부 결과에서 채워지는지도 함께 확인
        result = build_analysis_result(
            price=price_part(senior=None), registry=registry_part(senior=24_000_000), address=address,
            special_terms=copy.deepcopy(expected["special_terms"]),
            analysis_id=expected["analysis_id"], analyzed_at=expected["analyzed_at"],
        )
        self.assertEqual(result, expected)

    def test_failed_example(self):
        expected = load("analysis-result-failed.json")
        price = price_part(price=None, deposit=250_000_000, flags=[
            expected["flags"][0], VIOLATION,
        ], status={"status": "failed", "reason_code": "NO_TRADES",
                   "reason": expected["data_status"]["items"][0]["reason"]})
        price["property"] = {"address_key": "1150010300-0456-0007", "housing_type": "연립다세대",
                             "exclusive_area_m2": 24.5, "build_year": 2025}
        registry = registry_part(senior=0)
        registry["property"]["address_display"] = expected["property"]["address_display"]
        terms = {"extraction_status": "failed", "masked": True, "page": None, "section_text": None,
                 "reason": expected["data_status"]["items"][2]["reason"]}
        result = build_analysis_result(price=price, registry=registry, special_terms=terms,
                                       analysis_id=expected["analysis_id"], analyzed_at=expected["analyzed_at"])
        self.assertEqual(result, expected)

    def test_keys_match_contract(self):
        expected = load("analysis-result-ok.json")
        result = full()
        self.assertEqual(set(result), set(expected))
        self.assertEqual(set(result["price_card"]), set(expected["price_card"]))
        self.assertEqual(set(result["property"]), set(expected["property"]))
        for f in result["flags"]:
            self.assertEqual(set(f), {"code", "level", "value", "threshold", "source"})


class BandTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertIsNone(band_level(0.6999, 0.7, 0.8))
        self.assertEqual(band_level(0.7, 0.7, 0.8), "주의")
        self.assertEqual(band_level(0.8, 0.7, 0.8), "주의")  # 0.8은 "초과"가 아님
        self.assertEqual(band_level(0.8001, 0.7, 0.8), "위험")
        self.assertIsNone(band_level(None, 0.7, 0.8))

    def test_ratio_flags_threshold_is_level_boundary(self):
        flags = ratio_flags({"jeonse_ratio": 0.85, "senior_burden_ratio": 0.72})
        by = {f["code"]: f for f in flags}
        self.assertEqual((by["JEONSE_RATIO_HIGH"]["level"], by["JEONSE_RATIO_HIGH"]["threshold"]), ("위험", 0.8))
        self.assertEqual((by["SENIOR_BURDEN_HIGH"]["level"], by["SENIOR_BURDEN_HIGH"]["threshold"]), ("주의", 0.7))

    def test_config_changes_band_and_source(self):
        cfg = RiskConfig(senior_caution=0.6, senior_danger=0.7)
        f = ratio_flags({"jeonse_ratio": None, "senior_burden_ratio": 0.65}, cfg)[0]
        self.assertEqual((f["level"], f["threshold"]), ("주의", 0.6))
        self.assertIn("60% 이상 주의 / 70% 초과 위험", f["source"])


class GradeTest(unittest.TestCase):
    def test_safe_when_no_flags(self):
        r = full(price=price_part(price=400_000_000, flags=[]))
        self.assertEqual(r["grade"], "안전")
        self.assertEqual(r["flags"], [])

    def test_check_needed_alone_is_safe(self):
        r = full(price=price_part(price=400_000_000))
        self.assertEqual(r["grade"], "안전")
        self.assertEqual([f["code"] for f in r["flags"]], ["VIOLATION_BUILDING_CHECK_NEEDED"])

    def test_highest_level_wins(self):
        r = full(registry=registry_part(flags=[flag("OWNERSHIP_RESTRICTED", "위험", 1, 1)]))
        self.assertEqual(r["grade"], "위험")
        self.assertEqual(r["flags"][0]["code"], "OWNERSHIP_RESTRICTED")

    def test_jeonse_danger(self):
        r = full(price=price_part(price=240_000_000))  # 200/240 = 0.8333
        self.assertEqual(r["grade"], "위험")

    def test_price_failed_without_danger_holds(self):
        r = full(price=price_part(price=None, status={"status": "failed", "reason_code": "NO_TRADES",
                                                      "reason": "거래 없음"}))
        self.assertEqual(r["grade"], "판단보류")
        self.assertEqual(r["data_status"]["overall"], "incomplete")

    def test_danger_beats_hold(self):
        r = full(price=price_part(price=None, status={"status": "failed", "reason_code": "NO_TRADES",
                                                      "reason": "거래 없음"}),
                 registry=registry_part(flags=[flag("LEASE_RIGHT_REGISTERED", "위험", 1, 1)]))
        self.assertEqual(r["grade"], "위험")

    def test_registry_parse_failed_holds(self):
        r = full(registry=registry_part(failed=True))
        self.assertEqual(r["grade"], "판단보류")
        self.assertIsNone(r["price_card"]["senior_amount_used"])
        self.assertIsNone(r["price_card"]["senior_burden_ratio"])

    def test_registry_failed_but_jeonse_danger(self):
        r = full(price=price_part(price=240_000_000), registry=registry_part(failed=True))
        self.assertEqual(r["grade"], "위험")

    def test_registry_not_provided_holds(self):
        r = full(registry=None)
        self.assertEqual(r["grade"], "판단보류")
        self.assertEqual(r["data_status"]["items"][1]["status"], "not_provided")

    def test_special_terms_failure_does_not_hold_by_default(self):
        r = full(special_terms={"extraction_status": "failed"})
        self.assertEqual(r["grade"], "안전")
        item = r["data_status"]["items"][2]
        self.assertEqual((item["status"], item["reason_code"]), ("failed", "PARSE_FAILED"))
        self.assertIsNone(r["special_terms"]["section_text"])

    def test_special_terms_failure_holds_with_config(self):
        r = full(special_terms={"extraction_status": "failed"},
                 config=RiskConfig(special_terms_failure_holds_grade=True))
        self.assertEqual(r["grade"], "판단보류")

    def test_unknown_level_raises(self):
        with self.assertRaises(ValueError):
            decide_grade([flag("X", "심각")], [])


class LowConfidenceCapTest(unittest.TestCase):
    def test_low_confidence_caps_price_area(self):
        r = full(price=price_part(price=240_000_000, confidence="낮음"))
        f = r["flags"][0]
        self.assertEqual((f["code"], f["level"]), ("JEONSE_RATIO_HIGH", "주의"))
        self.assertIn("시세 신뢰도 낮음", f["source"])
        self.assertEqual(r["grade"], "주의")

    def test_low_confidence_does_not_cap_registry(self):
        r = full(price=price_part(price=240_000_000, confidence="낮음"),
                 registry=registry_part(flags=[flag("TRUST_REGISTERED", "위험", 1, 1)]))
        self.assertEqual(r["grade"], "위험")
        self.assertEqual(r["flags"][0]["code"], "TRUST_REGISTERED")

    def test_medium_confidence_not_capped(self):
        r = full(price=price_part(price=240_000_000, confidence="중간"))
        self.assertEqual(r["grade"], "위험")


class MergeTest(unittest.TestCase):
    def test_dedupe_keeps_higher_level(self):
        merged = merge_flags([flag("A", "주의", source="1")], [flag("A", "위험", source="2"), flag("B", "확인필요")])
        self.assertEqual([(f["code"], f["level"]) for f in merged], [("A", "위험"), ("B", "확인필요")])

    def test_dedupe_same_level_keeps_first(self):
        merged = merge_flags([VIOLATION], [dict(VIOLATION, source="다른 문구")])
        self.assertEqual(merged, [VIOLATION])

    def test_sorted_by_level(self):
        merged = merge_flags([flag("C", "확인필요"), flag("B", "주의"), flag("A", "위험")])
        self.assertEqual([f["code"] for f in merged], ["A", "B", "C"])

    def test_inputs_not_mutated(self):
        price = price_part(price=240_000_000, confidence="낮음")
        before = copy.deepcopy(price)
        full(price=price)
        self.assertEqual(price, before)


class PartsTest(unittest.TestCase):
    def test_address_failed_becomes_price_failure(self):
        address = {"status": "failed", "reason_code": "ADDRESS_NOT_FOUND", "reason": "주소 없음", "address": None}
        r = build_analysis_result(address=address, registry=registry_part(), special_terms=terms_ok(),
                                  analyzed_at="x")
        item = r["data_status"]["items"][0]
        self.assertEqual((item["status"], item["reason_code"]), ("failed", "ADDRESS_NOT_FOUND"))
        self.assertEqual(r["grade"], "판단보류")
        self.assertIsNone(r["price_card"]["estimated_price"])
        self.assertEqual(r["price_card"]["senior_amount_used"], 0)

    def test_price_senior_kept_over_registry(self):
        r = full(price=price_part(senior=10_000_000), registry=registry_part(senior=24_000_000))
        self.assertEqual(r["price_card"]["senior_amount_used"], 10_000_000)

    def test_special_terms_not_provided(self):
        item, block = special_terms_part(None)
        self.assertEqual(item["status"], "not_provided")
        self.assertIsNone(block)

    def test_ok_with_empty_text_is_failed(self):
        item, block = special_terms_part({"extraction_status": "ok", "section_text": ""})
        self.assertEqual((item["status"], block["extraction_status"]), ("failed", "failed"))

    def test_analyzed_at_default(self):
        r = build_analysis_result()
        self.assertTrue(r["analyzed_at"].endswith("+09:00"))
        self.assertEqual(r["data_status"]["overall"], "incomplete")


class ReviewFixTest(unittest.TestCase):
    """PR #9 리뷰 반영."""

    def test_senior_unknown_holds(self):
        # 등기부 ok인데 금액을 못 읽어 senior_amount_used=None (+ SENIOR_AMOUNT_UNREADABLE 확인필요)
        reg = registry_part(senior=None, flags=[flag("SENIOR_AMOUNT_UNREADABLE", "확인필요", 1, 1)])
        r = full(registry=reg)
        self.assertIsNone(r["price_card"]["senior_burden_ratio"])
        self.assertEqual(r["grade"], "판단보류")

    def test_senior_unknown_but_danger(self):
        r = full(price=price_part(price=240_000_000), registry=registry_part(senior=None))
        self.assertEqual(r["grade"], "위험")

    def test_senior_unknown_hold_can_be_turned_off(self):
        r = full(registry=registry_part(senior=None), config=RiskConfig(hold_when_senior_ratio_missing=False))
        self.assertEqual(r["grade"], "안전")

    def test_low_confidence_over_100pct_stays_danger(self):
        # 선순위 부담률 1.5 (250M+200M)/300M
        r = full(price=price_part(confidence="낮음"), registry=registry_part(senior=250_000_000))
        by = {f["code"]: f for f in r["flags"]}
        self.assertEqual(by["SENIOR_BURDEN_HIGH"]["level"], "위험")
        self.assertIn("깡통전세 기준(팀 확인 필요)", by["SENIOR_BURDEN_HIGH"]["source"])
        self.assertEqual(r["grade"], "위험")

    def test_low_confidence_exactly_100pct_stays_danger(self):
        r = full(price=price_part(price=200_000_000, confidence="낮음"))  # 전세가율 1.0
        by = {f["code"]: f for f in r["flags"]}
        self.assertEqual(by["JEONSE_RATIO_HIGH"]["level"], "위험")

    def test_low_confidence_under_100pct_capped(self):
        r = full(price=price_part(confidence="낮음"), registry=registry_part(senior=80_000_000))  # 0.9333
        by = {f["code"]: f for f in r["flags"]}
        self.assertEqual(by["SENIOR_BURDEN_HIGH"]["level"], "주의")
        self.assertEqual(r["grade"], "주의")


def address_ok(jibun="서울특별시 강서구 가상동 123-4", ho="401", **extra):
    a = {"address_key": "1150010300-0123-0004", "jibun_address": jibun, "ho_nm": ho}
    a.update(extra)
    return {"status": "ok", "reason_code": None, "reason": None, "address": a}


def registry_at(display, unit_no=None, **kw):
    reg = registry_part(**kw)
    reg["property"]["address_display"] = display
    reg["property"]["unit_no"] = unit_no
    return reg


class AddressMatchTest(unittest.TestCase):
    def test_parse_lot(self):
        self.assertEqual(parse_lot("서울특별시 강서구 화곡동 355-14 제4층 제401호"), ("화곡동", False, 355, 14))
        self.assertEqual(parse_lot("경기도 남양주시 오남읍 양지리 산 12"), ("양지리", True, 12, 0))
        self.assertEqual(parse_lot("서울특별시 종로구 종로1가 24"), ("종로1가", False, 24, 0))
        self.assertIsNone(parse_lot("서울특별시 강서구 화곡로 123"))
        self.assertIsNone(parse_lot(None))

    def test_parse_ho(self):
        self.assertEqual(parse_ho("제4층 제401호"), 401)
        self.assertEqual(parse_ho("401"), 401)
        self.assertIsNone(parse_ho("제4층"))

    def test_same_home_no_flag(self):
        reg = registry_at("서울특별시 강서구 가상동 123-4 제4층 제401호", "제4층 제401호")
        r = full(address=address_ok(), registry=reg)
        self.assertNotIn("REGISTRY_ADDRESS_MISMATCH", [f["code"] for f in r["flags"]])
        self.assertEqual(r["grade"], "안전")

    def test_uses_structured_lot_fields(self):
        a = address_ok(jibun=None, legal_dong_name="가상동", bun="0123", ji="0004", is_mountain=False)
        self.assertEqual(compare(a, registry_at("서울특별시 강서구 가상동 123-4"))["match"], True)

    def test_different_lot_holds(self):
        reg = registry_at("서울특별시 강서구 가상동 123-5", flags=[flag("OWNERSHIP_RESTRICTED", "위험", 1, 1)])
        r = full(address=address_ok(), registry=reg)
        f = [f for f in r["flags"] if f["code"] == "REGISTRY_ADDRESS_MISMATCH"][0]
        self.assertEqual(f["level"], "확인필요")
        self.assertIn("지번", f["source"])
        self.assertEqual(r["grade"], "판단보류")  # 위험 신호가 있어도 판단보류

    def test_different_ho_holds(self):
        reg = registry_at("서울특별시 강서구 가상동 123-4 제3층 제301호", "제3층 제301호")
        r = full(address=address_ok(), registry=reg)
        f = [f for f in r["flags"] if f["code"] == "REGISTRY_ADDRESS_MISMATCH"][0]
        self.assertIn("호수", f["source"])
        self.assertEqual(r["grade"], "판단보류")

    def test_ho_missing_on_one_side_not_compared(self):
        r = full(address=address_ok(ho=None), registry=registry_at("서울특별시 강서구 가상동 123-4", "제3층 제301호"))
        self.assertEqual(address_flags(address_ok(ho=None), registry_at("서울특별시 강서구 가상동 123-4")), [])
        self.assertEqual(r["grade"], "안전")

    def test_not_comparable(self):
        self.assertIsNone(compare(None, registry_part()))
        self.assertIsNone(compare(address_ok(), registry_part(failed=True)))
        self.assertIsNone(compare(address_ok(), registry_at(None)))
        failed = {"status": "failed", "reason_code": "ADDRESS_NOT_FOUND", "reason": "x", "address": None}
        self.assertIsNone(compare(failed, registry_part()))

    def test_mismatch_hold_can_be_turned_off(self):
        reg = registry_at("서울특별시 강서구 가상동 123-5")
        r = full(address=address_ok(), registry=reg, config=RiskConfig(address_mismatch_holds_grade=False))
        self.assertEqual(r["grade"], "안전")


class ReviewFix2Test(unittest.TestCase):
    """PR #9 두 번째 리뷰 반영."""

    def test_eup_myeon_uses_ri_name(self):
        a = address_ok(jibun=None, legal_dong_name="오남읍", ri_name="양지리", bun="0005", ji="0000", ho=None)
        reg = registry_at("경기도 남양주시 오남읍 양지리 5")
        self.assertEqual(compare(a, reg), {"match": True, "diff": []})

    def test_eup_myeon_jibun_text_fallback(self):
        a = address_ok(jibun="경기도 남양주시 오남읍 양지리 5", ho=None)
        self.assertTrue(compare(a, registry_at("경기도 남양주시 오남읍 양지리 5"))["match"])

    # 팀 합의 2026-11-27: 다가구는 최소 주의 대신 "다른 세대의 선순위 보증금 확인 필요", 금액을 모르면 판단보류
    def test_multi_household_unknown_deposits_holds(self):
        reg = registry_part(flags=[flag("HIDDEN_SENIOR_CLAIM_CHECK_NEEDED", "확인필요")])
        r = full(price=price_part(price=400_000_000), registry=reg)
        self.assertEqual(r["grade"], "판단보류")
        self.assertIsNone(r["price_card"]["other_tenant_deposits"])

    def test_multi_household_danger_still_danger(self):
        reg = registry_part(flags=[flag("HIDDEN_SENIOR_CLAIM_CHECK_NEEDED", "확인필요")])
        self.assertEqual(full(price=price_part(price=240_000_000), registry=reg)["grade"], "위험")

    def test_multi_household_with_user_deposits(self):
        reg = registry_part(flags=[flag("HIDDEN_SENIOR_CLAIM_CHECK_NEEDED", "확인필요")])
        # 시세 4억, 보증금 2억, 선순위 0 + 다른 세대 1억 -> (1억+2억)/4억 = 0.75 주의
        r = full(price=price_part(price=400_000_000), registry=reg, other_tenant_deposits=100_000_000)
        self.assertEqual(r["price_card"]["senior_amount_used"], 100_000_000)
        self.assertEqual(r["price_card"]["senior_burden_ratio"], 0.75)
        self.assertEqual(r["grade"], "주의")
        r = full(price=price_part(price=400_000_000), registry=reg, other_tenant_deposits=0)
        self.assertEqual(r["grade"], "안전")

    def test_multi_household_hold_can_be_turned_off(self):
        reg = registry_part(flags=[flag("HIDDEN_SENIOR_CLAIM_CHECK_NEEDED", "확인필요")])
        cfg = RiskConfig(hold_when_hidden_senior_unknown=False)
        self.assertEqual(full(price=price_part(price=400_000_000), registry=reg, config=cfg)["grade"], "안전")


class TeamDecisionTest(unittest.TestCase):
    """팀 합의 2026-11-27 (특약 확인 필요, 신뢰도 낮음 표시, 선순위 한 줄 요약)."""

    def test_special_terms_failure_adds_check_flag(self):
        r = full(special_terms={"extraction_status": "failed"})
        codes = [f["code"] for f in r["flags"]]
        self.assertIn("SPECIAL_TERMS_CHECK_NEEDED", codes)
        self.assertEqual(r["grade"], "안전")  # 확인필요는 등급에 반영 안 함
        self.assertEqual(r["special_terms"]["section_status"], {"base_terms": "failed", "custom_terms": "failed"})

    def test_custom_section_failed_adds_check_flag(self):
        st = dict(terms_ok(), section_status={"base_terms": "read", "custom_terms": "failed"})
        r = full(special_terms=st)
        self.assertIn("SPECIAL_TERMS_CHECK_NEEDED", [f["code"] for f in r["flags"]])
        # 리뷰 반영: 일부 구역만 못 읽어도 데이터 상태는 실패, 전체는 incomplete. 등급은 그대로
        item = r["data_status"]["items"][2]
        self.assertEqual((item["status"], item["reason_code"]), ("failed", "PARSE_FAILED"))
        self.assertIn("직접 쓴 특약", item["reason"])
        self.assertEqual(r["data_status"]["overall"], "incomplete")
        self.assertEqual(r["grade"], "안전")
        self.assertEqual(r["special_terms"]["section_text"], "1. 특약 문장")  # 읽은 부분은 그대로 넘김

    def test_base_section_failed_adds_check_flag(self):
        st = dict(terms_ok(), section_status={"base_terms": "failed", "custom_terms": "read"})
        r = full(special_terms=st)
        flag_ = next(f for f in r["flags"] if f["code"] == "SPECIAL_TERMS_CHECK_NEEDED")
        self.assertIn("기본특약", flag_["source"])
        self.assertEqual(r["data_status"]["items"][2]["status"], "failed")
        self.assertEqual(r["data_status"]["overall"], "incomplete")
        self.assertEqual(r["grade"], "안전")

    def test_external_send_flag_passes_through(self):
        self.assertFalse(full()["special_terms"]["external_send_allowed"])  # 판단 안 된 입력은 보내지 않음
        r = full(special_terms=dict(terms_ok(), external_send_allowed=True))
        self.assertTrue(r["special_terms"]["external_send_allowed"])
        r = full(special_terms={"extraction_status": "failed", "external_send_allowed": True})
        self.assertFalse(r["special_terms"]["external_send_allowed"])

    def test_ratio_decided_before_rounding(self):
        # 리뷰 반영: (선순위 + 보증금) / 시세 = 0.80001 은 표시값 0.8 이지만 80% 초과라 위험
        price = price_part(price=1_000_000_000, deposit=500_000_000, senior=300_010_000)
        price["price_card"]["senior_burden_ratio"] = 0.8
        r = full(price=price)
        f = next(f for f in r["flags"] if f["code"] == "SENIOR_BURDEN_HIGH")
        self.assertEqual((f["level"], f["value"]), ("위험", 0.8))
        self.assertEqual(r["grade"], "위험")

    def test_multi_household_ratio_decided_before_rounding(self):
        reg = registry_part(flags=[flag("HIDDEN_SENIOR_CLAIM_CHECK_NEEDED", "확인필요")])
        price = price_part(price=1_000_000_000, deposit=500_000_000, senior=0)
        r = full(price=price, registry=reg, other_tenant_deposits=300_010_000)
        self.assertEqual(r["price_card"]["senior_burden_ratio"], 0.8)
        self.assertEqual(r["grade"], "위험")

    def test_low_confidence_cap_uses_exact_ratio(self):
        # 0.99995는 표시값 1.0 이지만 100% 미만이라 신뢰도 낮음이면 주의로 낮춘다
        price = price_part(price=1_000_000_000, deposit=999_950_000, confidence="낮음")
        price["price_card"]["jeonse_ratio"] = 1.0
        r = full(price=price)
        f = next(f for f in r["flags"] if f["code"] == "JEONSE_RATIO_HIGH")
        self.assertEqual(f["level"], "주의")

    def test_custom_section_empty_is_not_flagged(self):
        st = dict(terms_ok(), section_status={"base_terms": "read", "custom_terms": "empty"})
        r = full(special_terms=st)
        self.assertNotIn("SPECIAL_TERMS_CHECK_NEEDED", [f["code"] for f in r["flags"]])
        self.assertEqual(r["special_terms"]["section_status"]["custom_terms"], "empty")

    def test_not_provided_is_not_flagged(self):
        r = full(special_terms=None)
        self.assertNotIn("SPECIAL_TERMS_CHECK_NEEDED", [f["code"] for f in r["flags"]])

    def test_low_confidence_label_on_price_card(self):
        self.assertEqual(full(price=price_part(confidence="낮음"))["price_card"]["confidence_label"],
                         "추정 시세 기준 · 신뢰도 낮음")
        self.assertIsNone(full(price=price_part(confidence="중간"))["price_card"]["confidence_label"])

    def test_registry_summary(self):
        reg = registry_part(senior=300_000_000)
        reg["registry_card"] = {"senior_amount_total": 300_000_000, "senior_amount_complete": False,
                                "senior_amount_missing_count": 1,
                                "counts": {"mortgage": 2, "jeonse_right": 1, "lease_right": 0}}
        s = full(registry=reg)["registry_summary"]
        self.assertEqual(s["summary_label"], "근저당 2건 · 전세권 1건")
        self.assertEqual(s["senior_amount_missing_count"], 1)
        self.assertEqual(s["senior_counts"], {"mortgage": 2, "hypothec": 0, "jeonse_right": 1, "lease_right": 0})
        self.assertIsNone(full(registry=registry_part(failed=True))["registry_summary"])


if __name__ == "__main__":
    unittest.main()
