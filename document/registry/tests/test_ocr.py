"""등기부 스캔본·사진 OCR 경로 테스트.

- 가짜 OCR 엔진 테스트: 글자 상자를 직접 만들어 칸 나누기, 행 묶기, 취소선, 신뢰도 처리를 본다 (Pillow·numpy만 필요).
- 실제 OCR 테스트: 가상 등기부 PDF를 사진처럼 만들어(기울기·흐림·노이즈) RapidOCR로 읽고 글자 층 결과와 비교한다.
  rapidocr·onnxruntime·pdfplumber·reportlab·한글 글꼴이 있어야 한다 (없으면 건너뜀). 쪽마다 몇 초 걸린다.
실행 (저장소 루트에서): python -m unittest discover -s document/registry/tests -v
"""

import os
import sys
import unittest
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

try:
    import numpy  # noqa: F401
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

try:
    import onnxruntime  # noqa: F401
    import pdfplumber  # noqa: F401
    import rapidocr  # noqa: F401
    import reportlab  # noqa: F401
    HAVE_OCR = True
except ImportError:
    HAVE_OCR = False

from fake_registry import find_korean_font, make_pdf, sample_pages  # noqa: E402

from document.registry import analyze_registry  # noqa: E402
from document.registry.ocr_reader import Box, _snap, _split_box, fix_text, match_title  # noqa: E402

FONT = find_korean_font()
TODAY = date(2026, 11, 26)


def box(text, x0, y0, x1=None, score=0.99, h=24):
    x1 = x1 if x1 is not None else x0 + 22 * len(text)
    return (text, [(x0, y0), (x1, y0), (x1, y0 + h), (x0, y0 + h)], score)


GAP_HEAD = [box("순위번호", 100, 200), box("등기목적", 220, 200), box("접수", 420, 200),
            box("등기원인", 600, 200), box("권리자 및 기타사항", 800, 200)]


def page(items_by_line):
    return [it for line in items_by_line for it in line]


class FakeEngine:
    """그림을 받으면 미리 정한 상자를 돌려준다 (쪽 순서대로)."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.i = 0

    def __call__(self, image):
        p = self.pages[self.i]
        self.i += 1
        return p


def blank(n=1, size=(1400, 1400)):
    return [Image.new("RGB", size, "white") for _ in range(n)]


def basic_page(score=0.99, amount_score=0.99):
    return page([
        [box("[집합건물] 서울특별시 가상구 가상동 1 가상아파트 제101동 제3층 제302호", 100, 40)],
        [box("[갑 구 1(소유권에 관한 사항)", 100, 150)],
        GAP_HEAD,
        [box("1", 110, 260), box("소유권보존", 220, 258), box("2015년4월20일", 420, 258), box("소유자 가상건설주식회사", 800, 258)],
        [box("2", 110, 330), box("소유권이전", 220, 330), box("2020년1월2일", 420, 330), box("매매", 600, 330),
         box("소유자홍길동 800101-1234567", 800, 330, score=score)],
        [box("1을 구1(소유권 이외의 권리에 관한 사항)", 100, 430)],
        [box("순위번호", 100, 480), box("등기목적", 220, 480), box("접수", 420, 480),
                      box("등기원인", 600, 480), box("권리자 및 기타사항", 800, 480)],
        # 날짜·금액 줄이 순위번호보다 몇 픽셀 위에 잡혀도 같은 행이어야 한다
        [box("2021년3월4일", 420, 532), box("채권최고액 금120,000,000원", 800, 532, score=amount_score)],
        [box("1", 110, 545, h=18), box("근저당권설정", 220, 540)],
        [box("근저당권자 주식회사가상은행", 800, 566)],
        [box("열람일시 : 2026년11월25일 10시00분00초", 100, 1300)],
    ])


@unittest.skipUnless(HAVE_PIL, "Pillow·numpy 없음")
class FakeOcrTest(unittest.TestCase):
    def run_pages(self, pages, images=None):
        return analyze_registry(images or blank(len(pages)), engine=FakeEngine(pages), today=TODAY)

    def test_rows_and_columns(self):
        r = self.run_pages([basic_page()])
        self.assertEqual(r["data_status_item"]["status"], "ok", r["data_status_item"])
        ents = {(e["section"], e["rank"]): e for e in r["detail"]["entries"]}
        self.assertEqual(ents[("gap", "2")]["kind"], "ownership_transfer")
        self.assertEqual(ents[("gap", "2")]["holder"], "***")  # 띄어쓰기를 잃은 개인 이름도 가린다
        m = ents[("eul", "1")]
        self.assertEqual((m["kind"], m["amount"], m["receipt_date"]), ("mortgage", 120000000, "2021-03-04"))
        self.assertEqual(r["senior_amount_used"], 120000000)
        card = r["registry_card"]
        self.assertEqual(card["read_method"], "ocr")
        self.assertGreater(card["ocr_score"], 0.9)
        self.assertEqual(card["issued_date"], "2026-11-25")

    def test_low_score_amount_is_unreadable(self):
        r = self.run_pages([basic_page(amount_score=0.7)])
        self.assertIsNone(r["senior_amount_used"])
        self.assertFalse(r["registry_card"]["senior_amount_complete"])
        self.assertIn("SENIOR_AMOUNT_UNREADABLE", [f["code"] for f in r["flags"]])

    def test_low_page_score_fails(self):
        low = [(t, b, 0.5) for t, b, _ in basic_page()]
        r = self.run_pages([low])
        self.assertEqual(r["data_status_item"]["reason_code"], "PARSE_FAILED")
        self.assertIn("신뢰도", r["data_status_item"]["reason"])

    def test_missed_section_title_fails(self):
        p = [it for it in basic_page() if "을 구" not in it[0]]
        r = self.run_pages([p])
        self.assertEqual(r["data_status_item"]["reason_code"], "PARSE_FAILED")
        self.assertIn("갑구·을구", r["data_status_item"]["reason"])

    def test_missing_rank_fails(self):
        # 갑구 1번 행을 통째로 놓치면 순위번호가 2부터 시작한다 -> 빠진 행이 있으니 판단보류
        p = [it for it in basic_page() if it[0] not in ("소유권보존", "소유자 가상건설주식회사")
             and not (it[0] == "1" and it[1][0][1] == 260) and it[0] != "2015년4월20일"]
        r = self.run_pages([p])
        self.assertEqual(r["data_status_item"]["reason_code"], "PARSE_FAILED")
        self.assertIn("순위번호", r["data_status_item"]["reason"])

    def test_no_table(self):
        r = self.run_pages([[box("아무 글자", 100, 100)]])
        self.assertIn("스캔", r["data_status_item"]["reason"])

    def test_strike_line_cancels(self):
        img = blank(1)[0]
        d = ImageDraw.Draw(img)
        # 근저당권설정 행 글자 가운데를 지나는 빨간 줄
        for x0, x1, y in ((220, 220 + 22 * 6, 552), (800, 800 + 22 * 14, 578), (420, 420 + 22 * 10, 544),
                          (800, 800 + 22 * 16, 544)):
            d.line([(x0, y), (x1, y)], fill=(220, 0, 0), width=2)
        r = analyze_registry([img], engine=FakeEngine([basic_page()]), today=TODAY)
        ents = {(e["section"], e["rank"]): e for e in r["detail"]["entries"]}
        self.assertEqual(ents[("eul", "1")]["status"], "cancelled")
        self.assertIn("strike", ents[("eul", "1")]["cancel_basis"])
        self.assertEqual(r["senior_amount_used"], 0)

    def test_text_is_not_strike(self):
        r = self.run_pages([basic_page()])
        self.assertTrue(all(e["status"] == "active" for e in r["detail"]["entries"]))


class HelperTest(unittest.TestCase):
    def test_titles(self):
        self.assertEqual(match_title("1을구1(소유권 이외의 권리에 관한 사항)")[0], "eul")
        self.assertEqual(match_title("[갑 구 ](소유권에 관한 사항)")[0], "gap")
        self.assertEqual(match_title("[표제 부1(전유부분의 건물의 표시)"), ("title", "unit"))
        self.assertEqual(match_title("소유권이전")[0], None)

    def test_fixes(self):
        self.assertEqual(fix_text("그저당귀설정"), "근저당권설정")
        self.assertEqual(fix_text("1번근저당권설정등기말쇠"), "1번근저당권설정등기말소")
        self.assertEqual(fix_text("58.01m'"), "58.01㎡")
        self.assertEqual(fix_text("제10층제1003호"), "제10층 제1003호")
        self.assertEqual(fix_text("근저당권자주식회사가상은행110111-0000001"), "근저당권자 주식회사가상은행 110111-0000001")

    def test_split_snaps_to_boundary(self):
        t = "1번근저당권설정등기말소 2023년9월12일"
        self.assertEqual(t[:_snap(t, 10, 0)], "1번근저당권설정등기말소")
        b = Box(t, 0, 0, len(t) * 10, 20, 0.99)
        parts = _split_box(b, [100])
        self.assertEqual([p.text.strip() for p in parts], ["1번근저당권설정등기말소", "2023년9월12일"])
        # 1글자만 삐져나온 것은 자르지 않는다
        self.assertEqual(len(_split_box(Box("근저당권설정", 0, 0, 60, 20, 0.99), [55])), 1)


@unittest.skipUnless(HAVE_OCR and HAVE_PIL and FONT, "rapidocr·onnxruntime·pdfplumber·reportlab 또는 한글 글꼴 없음")
class RealOcrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fake_photo import images_to_pdf, pdf_to_photos, to_jpeg
        import io

        pdf = make_pdf(sample_pages(), font_path=FONT)
        cls.text = analyze_registry(pdf, today=TODAY)
        photos = pdf_to_photos(io.BytesIO(pdf), angle=2.0, noise=12, blur=0.8)
        cls.photo = analyze_registry([to_jpeg(p) for p in photos], today=TODAY)
        cls.scan = analyze_registry(images_to_pdf(photos), today=TODAY)

    @staticmethod
    def key(r):
        act = sorted((e["section"], e["rank"], e["kind"], e["amount"], e["holder"])
                     for e in r["detail"]["entries"] if e["status"] == "active")
        return act, r["senior_amount_used"], sorted(f["code"] for f in r["flags"])

    def check(self, r):
        self.assertEqual(r["data_status_item"]["status"], "ok", r["data_status_item"])
        self.assertEqual(r["registry_card"]["read_method"], "ocr")
        self.assertEqual(self.key(r), self.key(self.text))
        n_cancel = lambda x: x["registry_card"]["counts"]["cancelled"]  # noqa: E731
        self.assertEqual(n_cancel(r), n_cancel(self.text))

    def test_photo_matches_text_layer(self):
        self.check(self.photo)

    def test_scanned_pdf_matches_text_layer(self):
        self.check(self.scan)


if __name__ == "__main__":
    unittest.main()
