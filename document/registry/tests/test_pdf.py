"""가상 등기부 PDF를 만들어 처음부터 끝까지 읽는 테스트.

pdfplumber·reportlab과 한글 TTF 글꼴이 있어야 한다 (없으면 건너뜀). 글꼴 경로는 KOREAN_TTF 환경변수로 줄 수 있다.
실행 (저장소 루트에서): python -m unittest discover -s document/registry/tests -v
"""

import json
import os
import sys
import unittest
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

try:
    import pdfplumber  # noqa: F401
    import reportlab  # noqa: F401
    HAVE_LIBS = True
except ImportError:
    HAVE_LIBS = False

from fake_registry import (  # noqa: E402
    GAP_HEADERS,
    GAP_WIDTHS,
    find_korean_font,
    make_image_only_pdf,
    make_pdf,
    sample_pages,
)

from document.registry import analyze_registry  # noqa: E402

FONT = find_korean_font()
TODAY = date(2026, 11, 26)


@unittest.skipUnless(HAVE_LIBS and FONT, "pdfplumber·reportlab 또는 한글 글꼴 없음")
class SamplePdfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = analyze_registry(make_pdf(sample_pages()), today=TODAY)

    def entry(self, section, rank):
        return next(e for e in self.result["detail"]["entries"] if e["section"] == section and e["rank"] == rank)

    def test_status_ok(self):
        self.assertEqual(self.result["data_status_item"],
                         {"part": "registry", "status": "ok", "reason_code": None, "reason": None})

    def test_strike_detected(self):
        self.assertIn("strike", self.entry("eul", "1")["cancel_basis"])
        self.assertIn("strike", self.entry("gap", "3")["cancel_basis"])
        self.assertEqual(self.entry("eul", "2")["status"], "active")
        self.assertEqual(self.entry("eul", "4")["status"], "active")

    def test_senior_amount(self):
        # 근저당 2번(변경 후 4,800만) + 전세권 1억. 말소된 근저당 1억8천만은 빠짐
        self.assertEqual(self.result["senior_amount_used"], 148_000_000)
        self.assertEqual(self.result["registry_card"]["senior_breakdown"]["mortgage_max_claim"], 48_000_000)

    def test_title(self):
        p = self.result["property"]
        self.assertEqual(p["exclusive_area_m2"], 29.8)
        self.assertEqual(p["structure"], "철근콘크리트구조")
        self.assertEqual(p["unit_no"], "제3층 제302호")
        self.assertEqual(p["road_address"], "서울특별시 강서구 가상로 12")
        self.assertIn("가상동 123-4", p["address_display"])

    def test_flags(self):
        codes = {f["code"]: f["level"] for f in self.result["flags"]}
        self.assertEqual(codes, {"JEONSE_RIGHT_EXISTS": "주의"})  # 가압류는 말소됨, 대지권 있음, 열람 6일 전
        self.assertEqual(self.result["registry_card"]["issued_date"], "2026-11-20")

    def test_no_personal_data(self):
        text = json.dumps(self.result, ensure_ascii=False)
        for secret in ("김가상", "이가상", "박가상", "800101", "750505", "900909", "가상로 2\"", "-1000000", "-0000000"):
            self.assertNotIn(secret, text)
        # 법인 이름은 남김
        self.assertEqual(self.entry("eul", "2")["holder"], "가상저축은행주식회사")

    def test_feeds_price_module(self):
        from document.price.analysis_result import build_price_result
        from document.price.estimator import PriceEstimate  # noqa: F401
        out = build_price_result(None, property_type="연립다세대", area=29.8, deposit=100_000_000,
                                 senior_amount_used=self.result["senior_amount_used"], base_date=TODAY,
                                 period=("2025-11-01", "2026-10-31"), failure=("NO_TRADES", "테스트"))
        self.assertEqual(out["price_card"]["senior_amount_used"], 148_000_000)

    def test_outdated(self):
        r = analyze_registry(make_pdf(sample_pages()), today=date(2026, 12, 10))
        f = next(f for f in r["flags"] if f["code"] == "REGISTRY_OUTDATED")
        self.assertEqual((f["level"], f["value"], f["threshold"]), ("주의", 20, 7))


@unittest.skipUnless(HAVE_LIBS and FONT, "pdfplumber·reportlab 또는 한글 글꼴 없음")
class RiskyPdfTest(unittest.TestCase):
    def test_restrictions_trust_lease_across_pages(self):
        gap = [
            ("title", "【 갑 구 】 ( 소유권에 관한 사항 )"),
            ("table", GAP_HEADERS, GAP_WIDTHS, [
                (["1", "소유권보존", "2015년1월1일", "", "소유자 주식회사가상건설"], False),
                (["2", "소유권이전", "2021년2월2일", "2021년2월2일\n신탁", "수탁자 가상신탁주식회사\n신탁원부 제2021-1호"], False),
                (["3", "가압류", "2025년3월3일", "가압류결정", "채권자 이가상"], False),
                (["4", "압류", "2025년4월4일", "압류", "권리자 가상구"], False),
            ]),
        ]
        eul = [
            ("title", "【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )"),
            ("table", GAP_HEADERS, GAP_WIDTHS, [
                (["1", "근저당권설정", "2021년2월2일", "설정계약", "채권최고액 금240,000,000원\n근저당권자 가상은행"], False),
                (["2", "주택임차권", "2025년5월5일", "임차권등기명령", "임차보증금 금150,000,000원\n임차권자 최가상"], False),
            ]),
        ]
        r = analyze_registry(make_pdf([gap, eul]), today=TODAY)
        self.assertEqual(r["data_status_item"]["status"], "ok")
        self.assertEqual(r["senior_amount_used"], 390_000_000)
        codes = {f["code"]: (f["level"], f["value"]) for f in r["flags"]}
        self.assertEqual(codes["OWNERSHIP_RESTRICTED"], ("위험", 2))
        self.assertEqual(codes["TRUST_REGISTERED"], ("위험", 1))
        self.assertEqual(codes["LEASE_RIGHT_REGISTERED"], ("위험", 1))
        self.assertIn("LAND_RIGHT_CHECK_NEEDED", codes)  # 집합건물인데 표제부(대지권) 없음


@unittest.skipUnless(HAVE_LIBS, "pdfplumber·reportlab 없음")
class FailureTest(unittest.TestCase):
    def assertParseFailed(self, result, word):
        item = result["data_status_item"]
        self.assertEqual((item["part"], item["status"], item["reason_code"]), ("registry", "failed", "PARSE_FAILED"))
        self.assertIn(word, item["reason"])
        self.assertIsNone(result["senior_amount_used"])
        self.assertEqual(result["flags"], [])

    def test_scanned_pdf(self):
        self.assertParseFailed(analyze_registry(make_image_only_pdf()), "스캔")

    def test_not_a_pdf(self):
        self.assertParseFailed(analyze_registry(b"not a pdf"), "PDF")

    def test_missing_file(self):
        self.assertParseFailed(analyze_registry(os.path.join(ROOT, "no_such_registry.pdf")), "PDF")

    @unittest.skipUnless(FONT, "한글 글꼴 없음")
    def test_not_a_registry(self):
        r = analyze_registry(make_pdf([[("text", "등기부가 아닌 문서입니다")]], header="", issued=""))
        self.assertParseFailed(r, "찾지 못했습니다")


if __name__ == "__main__":
    unittest.main()
