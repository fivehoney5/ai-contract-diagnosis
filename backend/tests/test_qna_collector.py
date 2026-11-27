import asyncio
import json

import httpx

from app.clients.public_data import PublicDataClient
from app.collectors import qna
from app.collectors.text import html_to_text
from app.core.config import Settings


def _resp(items, total=None):
    return {"response": {"header": {"resultCode": "00", "resultMsg": "정상입니다."}, "body": {"totalCount": len(items) if total is None else total, "items": {"item": items}}}}


def test_html_to_text_keeps_paragraphs_and_unescapes():
    raw = "<p>임대차는 <b>갱신</b>된 것으로 봅니다.</p><p></p><p>◇ 요건&nbsp;&amp; 효과</p>첫 줄<br />둘째 줄"
    assert html_to_text(raw) == "임대차는 갱신된 것으로 봅니다.\n◇ 요건 & 효과\n첫 줄\n둘째 줄"


def test_collect_filters_dedupes_and_builds_records(tmp_path, monkeypatch):
    monkeypatch.setattr(qna, "KEYWORDS", ("전세",))
    monkeypatch.setattr(qna, "LAW_NAMES", ("주택임대차보호법",))
    item_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.params
        assert p["serviceKey"] == "k"
        if request.url.path.endswith("getMaskMAnswerAreaList") and p["getGbn"] == "1":
            return httpx.Response(200, json=_resp([
                {"onhunqueSeq": "10", "onhunqnaAstSeq": "84", "onhunqueCatNm": "주택임대차"},
                {"onhunqueSeq": "11", "onhunqnaAstSeq": "84", "onhunqueCatNm": "농지 이용"},
            ]))
        if request.url.path.endswith("getMaskMAnswerAreaList"):
            return httpx.Response(200, json=_resp([
                {"onhunqueSeq": "20", "onhunqnaAstSeq": "90", "onhunqueCts": "<b>전세</b>보증금을 못 받았어요"},
                {"onhunqueSeq": "21", "onhunqnaAstSeq": "90", "onhunqueCts": "상가 보증금을 못 받았어요", "onhunansCts": "주택임대차와 달리"},
                {"onhunqueSeq": "22", "onhunqnaAstSeq": "90", "onhunqueCts": "장애인 고용 지원금"},
            ]))
        if request.url.path.endswith("getMaskMAnswerLawNameList"):
            return httpx.Response(200, json=_resp([{"onhunqueSeq": "10", "onhunqnaAstSeq": "84"}]))
        item_calls.append(p["onhunqueSeq"])
        if p["onhunqueSeq"] == "20":
            return httpx.Response(200, json={"response": {"header": {"resultCode": "03", "resultMsg": "데이터 없음"}}})
        return httpx.Response(200, json=_resp([{
            "onhunqueSeq": "10", "onhunqnaAstSeq": "84", "onhunqnaAstNm": "부동산/임대차", "onhunqueCatNm": "주택임대차",
            "onhunqueSubjNm": "재계약", "onhunqueCts": "계약은 어떻게 되나요?", "onhunansCts": "<p>갱신된 것으로 봅니다.</p>",
            "onhunansServiceDt": "2021-01-05 10:30:59.000",
            "MaskMAnswerAreaLawListItem": [{"onhunqueConLsiNm": "주택임대차보호법 제4조"}],
            "MaskMAnswerAreaInfoListItem": [{"csmTtl": "주택임대차", "cciNm": "임대차계약 갱신", "cnpClsNm": "갱신", "linkUrl": "https://www.easylaw.go.kr/x"}],
        }]))

    client = PublicDataClient(Settings(_env_file=None, public_data_api_key="k"), apis={}, transport=httpx.MockTransport(handler))
    manifest = asyncio.run(qna.collect(client, tmp_path))

    assert sorted(item_calls) == ["10", "20"]  # 농지 이용(11)·질문에 전세·주택 언급 없음(21, 22)은 거르고, 10은 한 번만 조회
    records = [json.loads(line) for line in (tmp_path / "easylaw_qna.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1 == manifest["count"]
    r = records[0]
    assert r["id"] == "qna:10"
    assert r["answer"] == "갱신된 것으로 봅니다."
    assert r["related_laws"] == ["주택임대차보호법 제4조"]
    assert r["related_guides"][0]["title"] == "주택임대차 > 임대차계약 갱신 > 갱신"
    assert r["found_by"] == ["분류:주택임대차", "법령:주택임대차보호법"]
    assert r["service_date"] == "2021-01-05"
    assert "serviceKey" not in json.dumps(r)
    assert manifest["failed"] and manifest["failed"][0].startswith("20:")
