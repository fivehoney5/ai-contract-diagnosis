"""등기부 행 해석 테스트 (PDF 없이 가상 Row로). 표준 라이브러리만 쓴다.

실행 (저장소 루트에서): python -m unittest discover -s document/registry/tests -v
"""

import os
import sys
import unittest
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from document.registry.analysis_result import registry_flags, senior_amount_for_price  # noqa: E402
from document.registry.parser import (  # noqa: E402
    build_entries,
    cancel_refs,
    classify,
    mask_holder,
    mask_text,
    parse_amount,
    parse_title,
    summarize,
)
from document.registry.pdf_reader import Row  # noqa: E402


def R(section, rank, purpose, holder="", cause="", receipt="2020년1월2일 제1호", struck=0.0, page=1):
    return Row(section, None, {"rank": rank, "purpose": purpose, "receipt": receipt, "cause": cause, "holder": holder},
               struck, page)


def T(sub, cells, struck=0.0):
    return Row("title", sub, cells, struck, 1, list(cells.values()))


def by_rank(entries, section, rank):
    return next(e for e in entries if e.section == section and e.rank == rank)


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "근저당권설정": "mortgage",
            "근 저 당 권 설 정": "mortgage",
            "가압류": "provisional_seizure",
            "압류": "seizure",
            "가처분": "provisional_disposition",
            "임의경매개시결정": "auction",
            "강제경매개시결정": "auction",
            "소유권이전청구권가등기": "provisional_registration",
            "전세권설정": "jeonse_right",
            "주택임차권": "lease_right",
            "소유권보존": "ownership_preservation",
            "소유권이전": "ownership_transfer",
            "1번근저당권설정등기말소": "cancellation",
            "2-1번근저당권변경등기말소": "cancellation",
            "저당권설정": "hypothec",
        }
        for purpose, kind in cases.items():
            with self.subTest(purpose=purpose):
                self.assertEqual(classify(purpose), kind)

    def test_trust(self):
        self.assertEqual(classify("소유권이전", "2021년1월1일 신탁"), "trust")
        self.assertEqual(classify("신탁"), "trust")
        # 신탁이 끝나 소유권이 돌아온 경우는 소유권이전 + 말소 문구
        self.assertEqual(classify("소유권이전 3번신탁등기말소", "신탁재산의귀속"), "ownership_transfer")

    def test_cancel_refs(self):
        self.assertEqual(cancel_refs("1번근저당권설정등기말소"), ["1"])
        self.assertEqual(cancel_refs("소유권이전\n3번신탁등기말소"), ["3"])
        self.assertEqual(cancel_refs("근저당권설정"), [])


class AmountMaskTest(unittest.TestCase):
    def test_amount(self):
        self.assertEqual(parse_amount("채권최고액 금120,000,000원\n채무자 ***", ("채권최고액",)), 120_000_000)
        self.assertEqual(parse_amount("채권최고액  금 1,000,000원"), 1_000_000)
        self.assertEqual(parse_amount("전세금 금200,000,000원", ("채권최고액",)), None)
        self.assertIsNone(parse_amount("채권최고액 미기재", ("채권최고액",)))

    def test_mask_rrn(self):
        self.assertNotIn("800101", mask_text("소유자 김가상 800101-1000000"))
        self.assertNotIn("800101", mask_text("소유자 김가상 800101-1******"))

    def test_mask_holder(self):
        self.assertEqual(mask_holder("소유자 김가상 800101-1000000\n서울특별시 가상구 가상로 2"), "***")
        self.assertEqual(mask_holder("채권최고액 금1원\n채무자 김가상\n근저당권자 주식회사가상은행 110111-0000001"),
                         "주식회사가상은행")
        self.assertEqual(mask_holder("근저당권자 주식회사 가상캐피탈"), "주식회사 가상캐피탈")
        self.assertEqual(mask_holder("권리자 국민건강보험공단"), "국민건강보험공단")
        self.assertIsNone(mask_holder(""))


class EntriesTest(unittest.TestCase):
    def test_strike_and_note(self):
        rows = [
            R("eul", "1", "근저당권설정", "채권최고액 금100,000,000원\n근저당권자 가상은행", struck=0.9),
            R("eul", "2", "근저당권설정", "채권최고액 금50,000,000원\n근저당권자 가상은행"),
            R("eul", "3", "1번근저당권설정등기말소"),
            R("eul", "4", "근저당권설정", "채권최고액 금30,000,000원", struck=0.95),  # 취소선만 있음
            R("eul", "5", "근저당권설정", "채권최고액 금20,000,000원"),
            R("eul", "6", "5번근저당권설정등기말소"),  # 말소 등기만 있음
        ]
        es = build_entries(rows)
        self.assertEqual(by_rank(es, "eul", "1").cancel_basis, ["strike", "note"])
        self.assertEqual(by_rank(es, "eul", "4").cancel_basis, ["strike"])
        self.assertEqual(by_rank(es, "eul", "5").cancel_basis, ["note"])
        self.assertEqual(by_rank(es, "eul", "5").cancelled_by, "6")
        self.assertEqual(by_rank(es, "eul", "2").status, "active")
        self.assertEqual(summarize(es)["senior_amount_total"], 50_000_000)

    def test_partial_strike_is_not_cancel(self):
        es = build_entries([R("eul", "1", "근저당권설정", "채권최고액 금10,000,000원", struck=0.3)])
        self.assertEqual(es[0].status, "active")

    def test_note_in_other_section_does_not_cancel(self):
        es = build_entries([
            R("gap", "1", "가압류", "채권자 이가상"),
            R("eul", "2", "1번근저당권설정등기말소"),
        ])
        self.assertEqual(by_rank(es, "gap", "1").status, "active")

    def test_mortgage_change_and_parent_cancel(self):
        es = build_entries([
            R("eul", "1", "근저당권설정", "채권최고액 금60,000,000원"),
            R("eul", "1-1", "1번근저당권변경", "채권최고액 금48,000,000원"),
            R("eul", "2", "근저당권설정", "채권최고액 금70,000,000원"),
            R("eul", "2-1", "2번근저당권변경", "채권최고액 금90,000,000원", struck=1.0),  # 말소된 변경은 반영 안 함
            R("eul", "3", "근저당권설정", "채권최고액 금10,000,000원", struck=1.0),
            R("eul", "3-1", "3번근저당권부질권", "채권액 금5,000,000원"),
        ])
        self.assertEqual(by_rank(es, "eul", "1").amount, 48_000_000)
        self.assertEqual(by_rank(es, "eul", "2").amount, 70_000_000)
        self.assertEqual(by_rank(es, "eul", "3-1").status, "cancelled")
        s = summarize(es)
        self.assertEqual(s["senior_amount_total"], 118_000_000)
        self.assertEqual(s["senior_breakdown"]["mortgage_max_claim"], 118_000_000)

    def test_senior_sum_kinds(self):
        es = build_entries([
            R("eul", "1", "근저당권설정", "채권최고액 금100,000,000원", receipt="2018년3월1일 제1호"),
            R("eul", "2", "전세권설정", "전세금 금150,000,000원\n전세권자 박가상", receipt="2017년1월1일 제2호"),
            R("eul", "3", "주택임차권", "임차보증금 금80,000,000원\n임차권자 최가상"),
            R("eul", "4", "저당권설정", "채권액 금5,000,000원"),
            R("eul", "5", "근저당권설정", "채권최고액 미상"),
        ])
        s = summarize(es)
        self.assertEqual(s["senior_amount_total"], 335_000_000)
        self.assertEqual(s["senior_breakdown"], {
            "mortgage_max_claim": 100_000_000, "hypothec_claim": 5_000_000,
            "jeonse_right_deposit": 150_000_000, "lease_right_deposit": 80_000_000,
        })
        self.assertEqual(s["senior_amount_missing_ranks"], ["5"])
        self.assertEqual(s["earliest_security_date"], "2017-01-01")
        self.assertEqual(s["counts"]["lease_right"], 1)
        self.assertEqual(s["counts"]["jeonse_right"], 1)
        # 금액을 못 읽은 근저당이 있으면 시세 모듈에는 None을 넘긴다
        self.assertIsNone(senior_amount_for_price(s))

    def test_senior_for_price_when_complete(self):
        s = summarize(build_entries([R("eul", "1", "근저당권설정", "채권최고액 금100,000,000원")]))
        self.assertEqual(senior_amount_for_price(s), 100_000_000)

    def test_jeonse_mortgage_not_double_counted(self):
        es = build_entries([
            R("eul", "1", "전세권설정", "전세금 금150,000,000원\n전세권자 박가상"),
            R("eul", "1-1", "1번전세권근저당권설정", "채권최고액 금180,000,000원\n근저당권자 가상은행"),
            R("eul", "2", "근저당권설정", "채권최고액 금50,000,000원"),
        ])
        self.assertEqual(by_rank(es, "eul", "1-1").kind, "jeonse_mortgage")
        self.assertEqual(by_rank(es, "eul", "1-1").amount, 180_000_000)
        s = summarize(es)
        self.assertEqual(s["senior_amount_total"], 200_000_000)
        self.assertEqual(s["counts"]["mortgage"], 1)

    def test_gap_counts_and_trust_ended(self):
        es = build_entries([
            R("gap", "1", "소유권보존", "소유자 주식회사가상건설"),
            R("gap", "2", "소유권이전", "수탁자 가상신탁주식회사", cause="2020년1월1일 신탁"),
            R("gap", "3", "소유권이전\n2번신탁등기말소", "소유자 김가상 800101-1000000", cause="2021년1월1일 신탁재산의귀속"),
            R("gap", "4", "가압류", "채권자 이가상"),
            R("gap", "5", "압류", "권리자 가상구"),
            R("gap", "6", "임의경매개시결정", "채권자 가상은행", struck=1.0),
            R("gap", "7", "소유권이전청구권가등기", "가등기권자 정가상"),
        ])
        s = summarize(es)
        self.assertEqual(by_rank(es, "gap", "2").status, "cancelled")
        self.assertEqual(s["counts"]["trust"], 0)
        self.assertEqual(s["counts"]["restriction"], 2)
        self.assertEqual(s["counts"]["provisional_registration"], 1)
        self.assertEqual([h["rank"] for h in s["ownership_history"]], ["1", "3"])
        self.assertEqual(s["ownership_history"][1]["holder"], "***")

    def test_page_continuation_merged(self):
        rows = [
            R("eul", "1", "근저당권설정", "채권최고액 금100,000,000원", page=1),
            Row("eul", None, {"rank": "", "purpose": "", "receipt": "", "cause": "", "holder": "근저당권자 가상은행"}, 0.0, 2),
        ]
        es = build_entries(rows)
        self.assertEqual(len(es), 1)
        self.assertEqual(es[0].holder, "가상은행")

    def test_moved_rank_and_partial_strike(self):
        # '1(전2)'는 옛 등기부에서 옮겨 온 표시. 표시변경으로 주소 줄만 그어진 행(30%)은 살아 있음
        es = build_entries([
            R("eul", "1(전2)", "전세권설정", "전세금 금20,000,000원", struck=1.0),
            R("eul", "2", "1번전세권설정등기말소"),
            R("eul", "3", "근저당권설정", "채권최고액 금100,000,000원", struck=0.3),
        ])
        self.assertEqual(by_rank(es, "eul", "1").cancel_basis, ["strike", "note"])
        self.assertEqual(by_rank(es, "eul", "3").status, "active")

    def test_short_continuation_does_not_flip_strike(self):
        rows = [
            R("eul", "1", "주택임차권", "임차보증금 금60,000,000원\n임차권자 최가상\n임차권등기명령", struck=1.0),
            Row("eul", None, {"rank": "", "purpose": "", "receipt": "", "cause": "", "holder": "결정"}, 0.0, 2),
        ]
        self.assertEqual(build_entries(rows)[0].status, "cancelled")

    def test_no_personal_data_in_entries(self):
        es = build_entries([R("gap", "1", "소유권이전", "소유자 김가상 800101-1000000 서울특별시 가상구", cause="매매")])
        text = str([e.to_dict() for e in es])
        for secret in ("김가상", "800101", "가상구"):
            self.assertNotIn(secret, text)


class TitleTest(unittest.TestCase):
    def test_title(self):
        rows = [
            T("building", {"rank": "1", "location": "서울특별시 강서구 가상동 123-4\n[도로명주소]\n서울특별시 강서구 가상로 12",
                           "detail": "철근콘크리트구조 5층"}),
            T("unit", {"rank": "1", "unit_no": "제3층 제302호", "detail": "철근콘크리트구조\n30.1㎡"}, struck=1.0),
            T("unit", {"rank": "2", "unit_no": "제3층 제302호", "detail": "철근콘크리트구조\n29.8㎡"}),
        ]
        t = parse_title(rows, "[집합건물] 서울특별시 강서구 가상동 123-4 제3층 제302호")
        self.assertEqual(t["exclusive_area_m2"], 29.8)
        self.assertEqual(t["structure"], "철근콘크리트구조")
        self.assertEqual(t["road_address"], "서울특별시 강서구 가상로 12")
        self.assertEqual(t["address"], "서울특별시 강서구 가상동 123-4")
        self.assertEqual(t["address_display"], "서울특별시 강서구 가상동 123-4 제3층 제302호")
        self.assertFalse(t["has_land_right"])

    def test_general_building(self):
        # 일반건물(다가구 등)은 전유부분이 없어서 구조만 건물내역에서 꺼낸다
        rows = [T("building", {"rank": "1", "location": "서울특별시 가상구 가상동 1",
                               "detail": "철근콘크리트조 슬래브지붕\n4층\n다가구주택\n1층 100.00㎡"})]
        t = parse_title(rows, "[건물] 서울특별시 가상구 가상동 1")
        self.assertEqual(t["structure"], "철근콘크리트조")
        self.assertIsNone(t["exclusive_area_m2"])


class FlagsTest(unittest.TestCase):
    def summary(self, **counts):
        base = {"restriction": 0, "provisional_registration": 0, "trust": 0, "lease_right": 0,
                "jeonse_right": 0, "mortgage": 0, "cancelled": 0}
        base.update(counts)
        return {"counts": base, "senior_amount_missing_ranks": []}

    def title(self, land=True, separate=False):
        return {"has_land_right": land, "separate_land_registration": separate}

    def codes(self, flags):
        return {f["code"]: f for f in flags}

    def test_flags(self):
        fl = self.codes(registry_flags(self.summary(restriction=2, trust=1, lease_right=1, jeonse_right=1,
                                                    provisional_registration=1),
                                       self.title(), is_collective=True, issued=None, today=None))
        self.assertEqual(fl["OWNERSHIP_RESTRICTED"]["level"], "위험")
        self.assertEqual(fl["OWNERSHIP_RESTRICTED"]["value"], 2)
        self.assertEqual(fl["TRUST_REGISTERED"]["level"], "위험")
        self.assertEqual(fl["LEASE_RIGHT_REGISTERED"]["level"], "위험")
        self.assertEqual(fl["JEONSE_RIGHT_EXISTS"]["level"], "주의")
        self.assertEqual(fl["PROVISIONAL_REGISTRATION"]["level"], "위험")
        for f in fl.values():
            self.assertEqual(set(f), {"code", "level", "value", "threshold", "source"})

    def test_clean_registry_no_flags(self):
        self.assertEqual(registry_flags(self.summary(), self.title(), is_collective=True,
                                        issued=date(2026, 11, 25), today=date(2026, 11, 26)), [])

    def test_land_and_outdated(self):
        fl = self.codes(registry_flags(self.summary(), self.title(land=False), is_collective=True,
                                       issued=date(2026, 11, 1), today=date(2026, 11, 26)))
        self.assertEqual(fl["LAND_RIGHT_CHECK_NEEDED"]["level"], "확인필요")
        self.assertEqual(fl["REGISTRY_OUTDATED"]["value"], 25)
        self.assertEqual(fl["REGISTRY_OUTDATED"]["threshold"], 7)
        # 일반 건물(집합건물 아님)은 대지권 신호 대신 선순위 보증금 확인 안내
        general = self.codes(registry_flags(self.summary(), self.title(land=False), is_collective=False,
                                            issued=None, today=None))
        self.assertNotIn("LAND_RIGHT_CHECK_NEEDED", general)
        self.assertEqual(general["HIDDEN_SENIOR_CLAIM_CHECK_NEEDED"]["level"], "확인필요")
        self.assertIn("확정일자", general["HIDDEN_SENIOR_CLAIM_CHECK_NEEDED"]["source"])

    def test_trust_level_option(self):
        fl = self.codes(registry_flags(self.summary(trust=1), self.title(), is_collective=True,
                                       issued=None, today=None, trust_level="주의"))
        self.assertEqual(fl["TRUST_REGISTERED"]["level"], "주의")


if __name__ == "__main__":
    unittest.main()
