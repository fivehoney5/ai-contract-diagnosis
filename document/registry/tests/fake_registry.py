"""테스트용 가상 등기부 PDF 만들기 (reportlab). 이름·번호·주소는 모두 지어낸 값이다.

인터넷등기소 PDF처럼 표 테두리를 선으로 긋고, 말소된 행은 글자 줄마다 빨간 가로선을 긋는다.
한글 글꼴(TTF)이 있어야 글자 층에 한글이 제대로 들어간다. 없으면 find_korean_font()가 None을 돌려주고
PDF 테스트는 건너뛴다.
"""

from __future__ import annotations

import io
import os

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\malgun.ttf",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/AppleGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/nanum/NanumGothic.ttf",
)
FONT = "FakeKorean"
SIZE = 8
LINE = 11
PAD = 3

GAP_HEADERS = ["순위번호", "등 기 목 적", "접 수", "등 기 원 인", "권리자 및 기타사항"]
GAP_WIDTHS = [45, 95, 80, 85, 215]
BUILDING_HEADERS = ["표시번호", "접 수", "소재지번,건물명칭 및 번호", "건 물 내 역", "등기원인 및 기타사항"]
BUILDING_WIDTHS = [45, 70, 150, 150, 105]
UNIT_HEADERS = ["표시번호", "접 수", "건 물 번 호", "건 물 내 역", "등기원인 및 기타사항"]
UNIT_WIDTHS = [45, 70, 110, 150, 145]
LAND_RIGHT_HEADERS = ["표시번호", "대지권종류", "대지권비율", "등기원인 및 기타사항"]
LAND_RIGHT_WIDTHS = [45, 150, 150, 175]


def find_korean_font() -> str | None:
    env = os.environ.get("KOREAN_TTF")
    for p in ((env,) if env else ()) + FONT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def _register(font_path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT, font_path))


def make_pdf(pages, *, font_path=None, header="[집합건물] 서울특별시 강서구 가상동 123-4 가상빌라 제3층 제302호",
             issued="열람일시 : 2026년11월20일 10시00분00초") -> bytes:
    """pages: 쪽마다 블록 목록. 블록은
        ("title", "【 갑 구 】 ( 소유권에 관한 사항 )")
        ("table", headers, widths, rows)  rows의 각 행은 (칸 목록, 말소여부). 칸 안 줄바꿈은 \\n
        ("text", "아무 글")
    """
    from reportlab.lib.colors import black, red
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    font_path = font_path or find_korean_font()
    _register(font_path)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    left = 40
    for blocks in pages:
        c.setFont(FONT, SIZE)
        y = H - 40
        if header:
            c.drawString(left, y, header)
        y -= 25
        for blk in blocks:
            if blk[0] in ("title", "text"):
                c.setFont(FONT, SIZE + 2 if blk[0] == "title" else SIZE)
                c.drawString(left, y - 10, blk[1])
                c.setFont(FONT, SIZE)
                y -= 22
                continue
            _, headers, widths, rows = blk
            all_rows = [(headers, False)] + list(rows)
            for cells, struck in all_rows:
                lines = [str(v).split("\n") for v in cells]
                h = max(len(ls) for ls in lines) * LINE + PAD * 2
                x = left
                for w, ls in zip(widths, lines):
                    c.setStrokeColor(black)
                    c.setLineWidth(0.5)
                    c.rect(x, y - h, w, h, stroke=1, fill=0)
                    for i, t in enumerate(ls):
                        ty = y - PAD - (i + 1) * LINE + 3
                        c.setFillColor(black)
                        c.drawString(x + 3, ty, t)
                        if struck and t.strip():
                            tw = c.stringWidth(t, FONT, SIZE)
                            c.setStrokeColor(red)
                            c.setLineWidth(0.8)
                            c.line(x + 2, ty + SIZE * 0.33, x + 4 + tw, ty + SIZE * 0.33)
                    x += w
                y -= h
            y -= 15
        if issued:
            c.setStrokeColor(black)
            c.drawString(left, 30, issued)
        c.showPage()
    c.save()
    return buf.getvalue()


def make_image_only_pdf() -> bytes:
    """글자 층이 없는 PDF (스캔본 흉내: 도형만 있음)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.rect(50, 50, 300, 300, stroke=1, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


def sample_pages():
    """기본 가상 등기부 (2쪽). 말소된 근저당 1건, 말소된 가압류 1건, 살아 있는 근저당 1건(변경 있음)·전세권 1건."""
    title = [
        ("title", "【 표 제 부 】 ( 1동의 건물의 표시 )"),
        ("table", BUILDING_HEADERS, BUILDING_WIDTHS, [
            (["1", "2016년3월2일", "서울특별시 강서구 가상동\n123-4 가상빌라\n[도로명주소]\n서울특별시 강서구 가상로 12",
              "철근콘크리트구조\n철근콘크리트지붕 5층\n공동주택(다세대주택)", ""], False),
        ]),
        ("title", "( 대지권의 목적인 토지의 표시 )"),
        ("title", "【 표 제 부 】 ( 전유부분의 건물의 표시 )"),
        ("table", UNIT_HEADERS, UNIT_WIDTHS, [
            (["1", "2016년3월2일", "제3층 제302호", "철근콘크리트구조\n29.8㎡", "도면편철장 제1책"], False),
        ]),
        ("title", "( 대지권의 표시 )"),
        ("table", LAND_RIGHT_HEADERS, LAND_RIGHT_WIDTHS, [
            (["1", "1 소유권대지권", "200분의 20", "2016년3월2일 대지권"], False),
        ]),
    ]
    gap = [
        ("title", "【 갑 구 】 ( 소유권에 관한 사항 )"),
        ("table", GAP_HEADERS, GAP_WIDTHS, [
            (["1", "소유권보존", "2016년3월2일\n제1001호", "", "소유자 주식회사가상건설 110111-0000000\n서울특별시 가상구 가상로 1"], False),
            (["2", "소유권이전", "2017년5월10일\n제2002호", "2017년4월1일\n매매", "소유자 김가상 800101-1000000\n서울특별시 가상구 가상로 2\n거래가액 금250,000,000원"], False),
            (["3", "가압류", "2019년1월5일\n제3003호", "2019년1월4일\n서울중앙지방법원의\n가압류결정", "청구금액 금30,000,000원\n채권자 이가상 750505-2000000"], True),
            (["4", "3번가압류등기말소", "2019년6월1일\n제4004호", "2019년5월30일\n해제", ""], False),
        ]),
    ]
    eul = [
        ("title", "【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )"),
        ("table", GAP_HEADERS, GAP_WIDTHS, [
            (["1", "근저당권설정", "2017년5월10일\n제2003호", "2017년5월10일\n설정계약", "채권최고액 금180,000,000원\n채무자 김가상\n근저당권자 주식회사가상은행 110111-0000001"], True),
            (["2", "근저당권설정", "2020년2월3일\n제5005호", "2020년2월3일\n설정계약", "채권최고액 금60,000,000원\n채무자 김가상\n근저당권자 가상저축은행주식회사"], False),
            (["2-1", "2번근저당권변경", "2021년3월3일\n제6006호", "2021년3월3일\n변경계약", "채권최고액 금48,000,000원"], False),
            (["3", "1번근저당권설정등기\n말소","2020년2월3일\n제5006호", "2020년2월3일\n해지", ""], False),
            (["4", "전세권설정", "2022년7월1일\n제7007호", "2022년6월30일\n설정계약", "전세금 금100,000,000원\n범 위 주거용 건물의 전부\n전세권자 박가상 900909-1000000"], False),
        ]),
    ]
    return [title, gap + eul]
