import asyncio
import json

import httpx
import pytest

from app.clients.law import LawApiClient
from app.collectors.law_targets import LawTarget
from app.collectors.laws import LawNotFoundError, article_text, build_records, collect, pick_current_law
from app.core.config import Settings

DETAIL = {
    "법령": {
        "기본정보": {
            "법령ID": "000001",
            "법령명_한글": "가상임대차법",
            "법종구분": {"content": "법률"},
            "시행일자": "20260102",
            "공포일자": "20251001",
            "공포번호": "123",
        },
        "조문": {
            "조문단위": [
                {"조문여부": "전문", "조문번호": "1", "조문내용": "\n\t제1장 총칙\n"},
                {"조문여부": "조문", "조문번호": "1", "조문제목": "목적", "조문내용": "제1조(목적) 목적을 정한다."},
                {
                    "조문여부": "조문",
                    "조문번호": "3",
                    "조문가지번호": "7",
                    "조문제목": "정보 제시",
                    "조문내용": "제3조의7(정보 제시) 다음을 제시한다.",
                    "항": {"호": [{"호내용": "1. 확정일자"}, {"호내용": "2. 납세증명서", "목": {"목내용": ["가. 국세", "나. 지방세"]}}]},
                },
                {
                    "조문여부": "조문",
                    "조문번호": "4",
                    "조문제목": "기간",
                    "조문내용": "제4조(기간)",
                    "항": [{"항내용": "① 2년으로 본다."}, {"항내용": "\n② 존속한다.\n"}],
                },
                {"조문여부": "조문", "조문번호": "5", "조문내용": "제5조 삭제 <2008.3.21>"},
                {"조문여부": "조문", "조문번호": "5", "조문가지번호": "2", "조문내용": "제5조의2", "조문참고자료": "[제9조로 이동]"},
                {"조문여부": "조문", "조문번호": "9", "조문제목": "범위 밖", "조문내용": "제9조(범위 밖) 내용"},
            ]
        },
    }
}


def test_article_text_joins_paragraphs_items_and_subitems():
    unit = DETAIL["법령"]["조문"]["조문단위"][2]
    assert article_text(unit) == "제3조의7(정보 제시) 다음을 제시한다.\n1. 확정일자\n2. 납세증명서\n가. 국세\n나. 지방세"


def test_build_records_skips_headings_deleted_and_out_of_range():
    records = build_records(DETAIL, LawTarget("가상임대차법", "테스트", articles=((1, 5),)), "2026-11-27T10:00:00+09:00")

    assert [r["article"] for r in records] == ["제1조", "제3조의7", "제4조"]
    first = records[0]
    assert first["id"] == "law:000001:제1조"
    assert first["chapter"] == "제1장 총칙"
    assert first["law_type"] == "법률"
    assert first["effective_date"] == "2026-01-02"
    assert first["url"].startswith("https://www.law.go.kr/")
    assert records[2]["text"] == "제4조(기간)\n① 2년으로 본다.\n② 존속한다."


def test_pick_current_law_requires_exact_name():
    result = {"LawSearch": {"law": [{"법령명한글": "가상임대차법 시행령", "법령ID": "2"}, {"법령명한글": "가상임대차법", "법령ID": "1", "현행연혁코드": "현행"}]}}
    assert pick_current_law(result, "가상임대차법")["법령ID"] == "1"
    with pytest.raises(LawNotFoundError):
        pick_current_law({"LawSearch": {"law": {"법령명한글": "다른법"}}}, "가상임대차법")


def test_collect_writes_jsonl_without_oc(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("lawSearch.do"):
            link = "/DRF/lawService.do?OC=secret-id&target=law&MST=1"
            return httpx.Response(200, json={"LawSearch": {"law": [{"법령명한글": "가상임대차법", "법령ID": "000001", "법령상세링크": link}]}})
        return httpx.Response(200, json=DETAIL)

    client = LawApiClient(Settings(_env_file=None, law_api_oc="secret-id"), transport=httpx.MockTransport(handler))
    summary = asyncio.run(collect(client, (LawTarget("가상임대차법", "테스트"),), tmp_path))

    content = (tmp_path / "가상임대차법.jsonl").read_text(encoding="utf-8")
    lines = [json.loads(line) for line in content.splitlines()]
    assert len(lines) == 4 == summary[0]["articles"]
    assert "secret-id" not in content
