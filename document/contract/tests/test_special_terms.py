"""특약 구역 추출 테스트. 모두 지어낸 계약서 문구다.

실행 (저장소 루트에서): python -m unittest discover -s document/contract/tests -v
- 줄 목록 테스트는 표준 라이브러리만 쓴다.
- PDF 테스트는 pdfplumber·reportlab·한글 TTF 글꼴이 있어야 한다 (없으면 건너뜀, 글꼴은 KOREAN_TTF 환경변수).
- 샘플 테스트는 CONTRACT_SAMPLES_DIR 환경변수에 샘플 폴더(fake_contract_jeonse.pdf 등)를 주면 돈다.
"""

import io
import json
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from document.contract import analyze_contract, extract_special_terms, group_ocr_lines, split_custom_terms  # noqa: E402
from document.contract.reader import Line  # noqa: E402

# 2023.10 개정 표준계약서 특약사항 칸을 흉내 낸 줄 목록 (글자 단위 줄바꿈 포함)
STANDARD_LINES = [
    "제 13 조(중개대상물확인․설명서 교부) 개업공인중개사는 중개대상물 확인․설명서를 작성하고",
    "[특약사항]",
    "① 주택을 인도받은 임차인은 2027 년 1 월 29 일까지 주민등록(전입신고)과 주택임대차계약서상 확정일자를 받기로 하고, 임대인은 위 약정",
    "일자의 다음날까지 임차주택에 저당권 등 담보권을 설정할 수 없다.",
    "② 임대인이 위 특약에 위반하여 임차주택에 저당권 등 담보권을 설정한 경우에는 임차인은 임대차계약을 해제 또는 해지할 수 있다.",
    "③ 임대차계약을 체결한 임차인은 임대인이 사전에 고지하지 않은 선순위 임대차 정보가 있거나 체납한 국세･지방세가 있는 경우 해제할 수 있다.",
    "④ 주택임대차계약과 관련하여 분쟁이 있는 경우 먼저 주택임대차분쟁조정위원회에 조정을",
    "신청한다. ( □ 동의 ■ 미동의)",
    "※ 주택임대차분쟁조정위원회 조정을 통할 경우 60 일(최대 90 일) 이내 조정 결과를 받아볼 수 있습니다.",
    "⑤ 주택의 철거 또는 재건축에 관한 구체적 계획 ( ■ 없음 □ 있음 ※공사시기 : ※ 소요기간 : 개월)",
    "⑥ 상세주소가 없는 경우 임차인의 상세주소부여 신청에 대한 소유자 동의여부 ( □ 동의 □ 미동의)",
    "※ 기타",
    "1. 임차인은 반려동물을 기르지 않는다.",
    "2. 보증금은 새 임차인이 들어온 뒤에 돌려주며, 반환을 최",
    "대 6 개월까지 미룰 수 있다.",
    "- 2 / 4 -",
    "본 계약을 증명하기 위하여 계약 당사자가 이의 없음을 확인하고 각각 서명․날인 후",
    "임대인 주 소 서울특별시 가상구 가상로 1 서명 또는 날인",
]


def as_lines(texts, page=2, score=None):
    return [Line(t, page, i * 10.0, score) for i, t in enumerate(texts)]


class ExtractTest(unittest.TestCase):
    def test_standard_form(self):
        r = extract_special_terms(as_lines(STANDARD_LINES))
        self.assertEqual(r["form"], "standard_2023")
        self.assertEqual([t["no"] for t in r["base_terms"]], [1, 2, 3, 4, 5, 6])
        self.assertTrue(r["custom_marker_found"])
        self.assertEqual(r["warnings"], [])
        # 글자 단위 줄바꿈은 붙여 쓴다
        self.assertIn("위 약정일자의 다음날까지", r["base_terms"][0]["text"])
        self.assertEqual([c["no"] for c in r["custom_terms"]], [1, 2])
        self.assertEqual(r["custom_terms"][1]["text"], "2. 보증금은 새 임차인이 들어온 뒤에 돌려주며, 반환을 최대 6 개월까지 미룰 수 있다.")
        # 서명란·쪽 번호는 들어가지 않는다
        self.assertNotIn("본 계약을", r["section_text"])
        self.assertNotIn("2 / 4", r["section_text"])
        self.assertIn("※ 기타\n1. 임차인은", r["section_text"])

    def test_note_and_choices(self):
        r = extract_special_terms(as_lines(STANDARD_LINES))
        t4, t5, t6 = r["base_terms"][3:6]
        self.assertTrue(t4["note"].startswith("※ 주택임대차분쟁조정위원회"))
        self.assertEqual((t4["choice"], t4["choice_status"]), ("미동의", "selected"))
        self.assertEqual((t5["choice"], t5["choice_status"]), ("없음", "selected"))
        self.assertEqual((t6["choice"], t6["choice_status"]), (None, "none_selected"))
        # ⑤ 줄 안의 "※공사시기"는 note로 떼지 않는다
        self.assertIsNone(t5["note"])

    def test_ocr_without_checkbox_glyphs(self):
        lines = [t.replace("■", "").replace("□", "") for t in STANDARD_LINES]
        r = extract_special_terms(as_lines(lines, score=0.95))
        self.assertEqual(r["base_terms"][3]["choice_status"], "unreadable")
        self.assertIsNone(r["base_terms"][3]["choice"])

    def test_marker_merged_with_first_custom_line(self):
        # 사진 OCR은 "※기타"와 첫 특약을 한 줄로 붙이기도 한다
        lines = STANDARD_LINES[:11] + ["※기타 1.임차인은 반려동물을 기르지 않는다."] + STANDARD_LINES[13:]
        r = extract_special_terms(as_lines(lines))
        self.assertEqual(r["custom_terms"][0]["text"], "1.임차인은 반려동물을 기르지 않는다.")
        self.assertEqual(len(r["custom_terms"]), 2)

    def test_base_terms_without_circled_numbers(self):
        lines = [re.sub(r"^[①-⑥]\s*", "", t) for t in STANDARD_LINES]
        r = extract_special_terms(as_lines(lines))
        self.assertEqual([t["no"] for t in r["base_terms"]], [1, 2, 3, 4, 5, 6])

    def test_no_custom_terms(self):
        lines = STANDARD_LINES[:12] + STANDARD_LINES[16:]
        r = extract_special_terms(as_lines(lines))
        self.assertEqual(r["custom_terms"], [])
        self.assertIsNone(r["custom_terms_text"])
        self.assertIn("NO_CUSTOM_TERMS", r["warnings"])

    def test_guide_text_removed(self):
        lines = STANDARD_LINES[:12] + [
            "(임차인의 대항력·우선변제권 확보를 위한 사항, 관리비·전기료 납부방법 등 특별히 임대인과 임차인이 약정할 사항이 있으면 기재)",
            "[대항력과 우선변제권 확보 관련 예시] \"주택을 인도받은 임차인은 ○년 ○월 ○일까지 주민등록과",
            "확정일자를 받기로 하고\"는 등 당사자 사이 합의에 의한 특약 가능",
        ] + STANDARD_LINES[12:]
        r = extract_special_terms(as_lines(lines))
        self.assertEqual(len(r["custom_terms"]), 2)
        self.assertTrue(r["custom_terms"][0]["text"].startswith("1. 임차인은"))

    def test_non_standard_contract(self):
        lines = ["임대차 계약서", "특약사항", "1. 애완동물 금지", "2. 관리비는 임차인이 낸다.", "서명 또는 날인"]
        r = extract_special_terms(as_lines(lines, page=1))
        self.assertEqual(r["form"], "unknown")
        self.assertEqual(r["base_terms"], [])
        self.assertEqual([c["text"] for c in r["custom_terms"]], ["1. 애완동물 금지", "2. 관리비는 임차인이 낸다."])

    def test_section_status_read(self):
        r = extract_special_terms(as_lines(STANDARD_LINES))
        self.assertEqual(r["section_status"], {"base_terms": "read", "custom_terms": "read"})

    def test_section_status_empty_only_when_sure(self):
        no_custom = STANDARD_LINES[:12] + STANDARD_LINES[16:]
        r = extract_special_terms(as_lines(no_custom))
        self.assertEqual(r["section_status"]["custom_terms"], "empty")
        # OCR 신뢰도가 낮으면 비어 있다고 단정하지 않는다 (OCR 실패가 "특약 없음"으로 보이지 않게)
        r = extract_special_terms(as_lines(no_custom, score=0.5))
        self.assertEqual(r["section_status"]["custom_terms"], "failed")
        # ※ 기타를 못 찾아도 추출 실패
        r = extract_special_terms(as_lines(STANDARD_LINES[:11] + STANDARD_LINES[16:]))
        self.assertEqual(r["section_status"]["custom_terms"], "failed")

    def test_section_status_base_incomplete(self):
        lines = STANDARD_LINES[:9] + STANDARD_LINES[10:]  # ⑤ 빠짐
        r = extract_special_terms(as_lines(lines))
        self.assertEqual(r["section_status"]["base_terms"], "failed")

    def test_section_status_non_standard(self):
        lines = ["특약사항", "1. 애완동물 금지", "서명 또는 날인"]
        r = extract_special_terms(as_lines(lines, page=1))
        self.assertEqual(r["section_status"], {"base_terms": "empty", "custom_terms": "read"})

    def test_no_section(self):
        self.assertIsNone(extract_special_terms(as_lines(["제 1 조(목적)", "본 계약을 증명하기 위하여"])))

    def test_body_sentence_is_not_header(self):
        lines = ["특약에 위반하여 담보권을 설정한 경우 임차인은 계약을 해지할 수 있다고 정한다."]
        self.assertIsNone(extract_special_terms(as_lines(lines)))

    def test_low_ocr_score_and_missing_end(self):
        r = extract_special_terms(as_lines(STANDARD_LINES[:15], score=0.6))
        self.assertIn("LOW_OCR_CONFIDENCE", r["warnings"])
        self.assertIn("END_MARKER_NOT_FOUND", r["warnings"])

    def test_unnumbered_custom_terms(self):
        out = split_custom_terms(["임차인은 반려동물을 기르지", "않는다.", "관리비는 임차인이 낸다."])
        self.assertEqual([c["text"] for c in out], ["임차인은 반려동물을 기르지않는다.", "관리비는 임차인이 낸다."])


class OcrGroupingTest(unittest.TestCase):
    def test_groups_same_row_and_orders(self):
        items = [
            ("오른쪽", [(300, 102), (400, 102), (400, 122), (300, 122)], 0.9),
            ("왼쪽", [(10, 100), (200, 100), (200, 120), (10, 120)], 0.8),
            ("둘째 줄", [(10, 140), (200, 140), (200, 160), (10, 160)], 1.0),
        ]
        lines = group_ocr_lines(items, page=1)
        self.assertEqual([ln.text for ln in lines], ["왼쪽 오른쪽", "둘째 줄"])
        self.assertAlmostEqual(lines[0].score, 0.85)


class AnalyzeTest(unittest.TestCase):
    def test_fake_engine_on_image(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 없음")
        buf = io.BytesIO()
        Image.new("RGB", (50, 50), "white").save(buf, format="PNG")

        def engine(_image):
            return [(t, [(0, i * 30), (500, i * 30), (500, i * 30 + 20), (0, i * 30 + 20)], 0.95)
                    for i, t in enumerate(STANDARD_LINES)]

        r = analyze_contract(buf.getvalue(), engine=engine)
        self.assertEqual(r["extraction_status"], "ok")
        self.assertEqual(r["source"], "ocr")
        self.assertEqual(len(r["custom_terms"]), 2)
        self.assertTrue(r["masked"])

    def test_failures_do_not_raise(self):
        r = analyze_contract("계약서.hwp")
        self.assertEqual((r["extraction_status"], r["reason_code"]), ("failed", "PARSE_FAILED"))
        self.assertIsNone(r["section_text"])
        self.assertEqual(r["section_status"], {"base_terms": "failed", "custom_terms": "failed"})

    def test_no_section_fails(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 없음")
        buf = io.BytesIO()
        Image.new("RGB", (50, 50), "white").save(buf, format="PNG")
        r = analyze_contract(buf.getvalue(), engine=lambda _img: [("제 1 조(목적)", [(0, 0), (9, 0), (9, 9), (0, 9)], 0.9)])
        self.assertEqual(r["extraction_status"], "failed")
        self.assertIn("특약사항 칸을 찾지 못했습니다", r["reason"])

    def test_grader_accepts_result(self):
        from document.risk.grader import special_terms_part

        r = extract_special_terms(as_lines(STANDARD_LINES))
        item, block = special_terms_part({"extraction_status": "ok", **r, "masked": False})
        self.assertEqual(item["status"], "ok")
        self.assertEqual(block["page"], 2)


def find_korean_font():
    cands = [os.environ.get("KOREAN_TTF"), r"C:\Windows\Fonts\malgun.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]
    return next((c for c in cands if c and os.path.exists(c)), None)


try:
    import pdfplumber  # noqa: F401
    import reportlab  # noqa: F401
    HAVE_PDF_LIBS = True
except ImportError:
    HAVE_PDF_LIBS = False
FONT = find_korean_font()


@unittest.skipUnless(HAVE_PDF_LIBS and FONT, "pdfplumber·reportlab 또는 한글 글꼴 없음")
class PdfTest(unittest.TestCase):
    def test_text_layer_pdf_spanning_pages(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas

        pdfmetrics.registerFont(TTFont("KR", FONT))
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        c.setFont("KR", 9)
        y = 800
        for i, t in enumerate(STANDARD_LINES):
            if i == 12:  # 직접 쓴 특약 중간에 쪽이 넘어감
                c.showPage()
                c.setFont("KR", 9)
                y = 800
            c.drawString(30, y, t)
            y -= 14
        c.save()
        r = analyze_contract(buf.getvalue())
        self.assertEqual(r["extraction_status"], "ok", r["reason"])
        self.assertEqual(r["source"], "text_layer")
        self.assertEqual(r["pages"], [1, 2])
        self.assertEqual(len(r["base_terms"]), 6)
        self.assertEqual(len(r["custom_terms"]), 2)


SAMPLES = os.environ.get("CONTRACT_SAMPLES_DIR")


def _n(s):
    return re.sub(r"\s+", "", s)


@unittest.skipUnless(SAMPLES and os.path.isdir(SAMPLES or ""), "CONTRACT_SAMPLES_DIR 없음")
class SampleTest(unittest.TestCase):
    """가짜 계약서 샘플(fake_contract_jeonse)과 기대값 비교. 샘플은 저장소에 넣지 않는다."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(SAMPLES, "special_terms_expected.json"), encoding="utf-8") as f:
            cls.exp = json.load(f)

    def check(self, r, exact):
        import difflib

        self.assertEqual(r["extraction_status"], "ok", r["reason"])
        self.assertEqual(r["form"], "standard_2023")
        base = [t for t in self.exp["printed_base_terms"] if not t.startswith("※")]
        self.assertEqual(len(r["base_terms"]), len(base))
        self.assertEqual(len(r["custom_terms"]), len(self.exp["custom_terms"]))
        for got, want in zip(r["custom_terms"], self.exp["custom_terms"]):
            ratio = difflib.SequenceMatcher(None, _n(got["text"]), _n(want["text"])).ratio()
            self.assertGreaterEqual(ratio, 1.0 if exact else 0.95, got["text"])

    def test_pdf(self):
        r = analyze_contract(os.path.join(SAMPLES, "fake_contract_jeonse.pdf"))
        self.check(r, exact=True)
        self.assertEqual(r["base_terms"][3]["choice"], "동의")

    def test_photos(self):
        try:
            import rapidocr  # noqa: F401
        except ImportError:
            self.skipTest("rapidocr 없음")
        r = analyze_contract([os.path.join(SAMPLES, "photo_p1_page1.jpg"),
                              os.path.join(SAMPLES, "photo_p2_special_terms.jpg")])
        self.check(r, exact=False)
        self.assertEqual(r["pages"], [2])


if __name__ == "__main__":
    unittest.main()
