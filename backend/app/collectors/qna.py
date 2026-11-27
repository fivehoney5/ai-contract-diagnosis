"""법제처 백문백답(찾기쉬운 생활법령정보)을 모아 data/knowledge_base/qna/에 JSONL로 저장합니다.

실행 (backend 폴더에서):
    python -m app.collectors.qna

1. 분류별 목록 API로 "부동산/임대차" 분류의 질문 목록을 받고, 관련 중분류만 남깁니다.
2. 검색어·법령명 검색 API로 다른 분류에 있는 관련 질문을 더합니다.
3. 항목 조회 API로 질문마다 답변 전문, 관련 법령, 관련 생활법령 해설 링크를 받습니다.

공공데이터포털 개발계정은 API마다 하루 1,000건까지라서, 한 번 돌리면 항목 조회를 백여 건 씁니다.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.clients.base import ExternalApiError
from app.clients.public_data import PublicDataClient
from app.collectors.text import html_to_text
from app.core.config import get_settings

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge_base" / "qna"

LIST_PATH = "/1170000/MaskMAnswerAreaListService/getMaskMAnswerAreaList"
LAW_NAME_PATH = "/1170000/MaskMAnswerLawNameListService/getMaskMAnswerLawNameList"
ITEM_PATH = "/1170000/MaskMAnswerAreaItemService/getMaskMAnswerAreaItem"
WEB_URL = "https://www.easylaw.go.kr/CSP/csp1/lifeLawDetail/getOnhunqueDetail.do?onhunqnaAstSeq={ast}&onhunqueSeq={que}"

# 수집 대상. 바꾸면 수집을 다시 돌립니다.
CATEGORY_SEQ = "84"  # 대분류 "부동산/임대차"
SUBCATEGORIES = (  # 위 대분류 안에서 남길 중분류
    "주택임대차",
    "전세사기 피해자 지원",
    "부동산등기",
    "부동산 경매",
    "공인중개사 1",
    "공인중개사 2",
)
KEYWORDS = ("전세", "보증금")  # 다른 분류에 있는 질문을 찾을 검색어
# 검색어로만 찾은 질문은 "질문"에 아래 말이 있을 때만 남깁니다. 답변까지 보면 상가·창업 질문이 섞입니다.
KEYWORD_MUST_MENTION = ("전세", "주택임대차", "임차주택", "확정일자", "전입신고")
# 검색어 목록 응답에는 중분류가 비어 있어서, 답변을 받은 뒤 이 중분류를 한 번 더 거릅니다.
EXCLUDED_SUBCATEGORIES = ("상가임대차",)
LAW_NAMES = ("주택임대차보호법", "전세사기피해자 지원 및 주거안정에 관한 특별법")  # 이 법령과 연결된 질문


def _items(result: dict) -> list[dict]:
    body = (result.get("response") or {}).get("body") or {}
    items = (body.get("items") or {}).get("item") or []
    return items if isinstance(items, list) else [items]


def _total(result: dict) -> int:
    return int(((result.get("response") or {}).get("body") or {}).get("totalCount") or 0)


async def _list_all(client: PublicDataClient, path: str, **params: Any) -> list[dict]:
    collected: list[dict] = []
    page = 1
    while True:
        result = await client.get(path, type="json", numOfRows=100, pageNo=page, **params)
        items = _items(result)
        collected += items
        if not items or len(collected) >= _total(result):
            return collected
        page += 1


async def find_questions(client: PublicDataClient) -> dict[str, dict]:
    """수집할 질문을 {백문일련번호: {"ast": 분류번호, "found_by": [...]}}로 모읍니다."""
    found: dict[str, dict] = {}

    def add(item: dict, reason: str) -> None:
        entry = found.setdefault(item["onhunqueSeq"], {"ast": item["onhunqnaAstSeq"], "found_by": []})
        if reason not in entry["found_by"]:
            entry["found_by"].append(reason)

    for item in await _list_all(client, LIST_PATH, getGbn=1, onhunqnaAstSeq=CATEGORY_SEQ):
        if item.get("onhunqueCatNm") in SUBCATEGORIES:
            add(item, f"분류:{item['onhunqueCatNm']}")
    for keyword in KEYWORDS:
        for item in await _list_all(client, LIST_PATH, getGbn=2, txtQuery=keyword):
            question = html_to_text(item.get("onhunqueCts"))
            if item.get("onhunqueSeq") in found or any(word in question for word in KEYWORD_MUST_MENTION):
                add(item, f"검색어:{keyword}")
    for law_name in LAW_NAMES:
        for item in await _list_all(client, LAW_NAME_PATH, txtQuery=law_name):
            add(item, f"법령:{law_name}")
    return found


def build_record(item: dict, found_by: list[str], collected_at: str) -> dict:
    ast, que = item["onhunqnaAstSeq"], item["onhunqueSeq"]
    laws = [law["onhunqueConLsiNm"].strip() for law in item.get("MaskMAnswerAreaLawListItem") or [] if law.get("onhunqueConLsiNm")]
    guides = [
        {"title": " > ".join(filter(None, [g.get("csmTtl"), g.get("cciNm"), g.get("cnpClsNm")])), "url": g.get("linkUrl")}
        for g in item.get("MaskMAnswerAreaInfoListItem") or []
        if g.get("linkUrl")
    ]
    return {
        "id": f"qna:{que}",
        "source_type": "qna",
        "question": html_to_text(item.get("onhunqueCts")),
        "answer": html_to_text(item.get("onhunansCts")),
        "category": item.get("onhunqnaAstNm"),
        "subcategory": item.get("onhunqueCatNm") or None,
        "subject": item.get("onhunqueSubjNm") or None,
        "related_laws": laws,
        "related_guides": guides,
        "url": WEB_URL.format(ast=ast, que=que),
        "service_date": (item.get("onhunansServiceDt") or "")[:10] or None,
        "found_by": found_by,
        "collected_at": collected_at,
    }


async def collect(client: PublicDataClient, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    collected_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    questions = await find_questions(client)
    print(f"  질문 {len(questions)}개 찾음, 답변 받는 중...")

    records: list[dict] = []
    failed: list[str] = []
    for que, info in sorted(questions.items(), key=lambda kv: int(kv[0])):
        try:
            items = _items(await client.get(ITEM_PATH, type="json", onhunqnaAstSeq=info["ast"], onhunqueSeq=que))
        except ExternalApiError as exc:
            failed.append(f"{que}: {exc.message}")
            continue
        if not items:
            failed.append(f"{que}: 빈 응답")
            continue
        record = build_record(items[0], info["found_by"], collected_at)
        keyword_only = all(reason.startswith("검색어:") for reason in info["found_by"])
        if keyword_only and record["subcategory"] in EXCLUDED_SUBCATEGORIES:
            continue
        if record["question"] and record["answer"]:
            records.append(record)

    path = output_dir / "easylaw_qna.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    manifest = {
        "source": "법제처 찾기쉬운 생활법령정보 백문백답 (공공데이터포털 법제처_분류별백문백답 목록·백문백답항목·백문백답법령명검색 조회 서비스)",
        "license": "공공데이터포털 이용허락범위 제한 없음",
        "file": path.name,
        "count": len(records),
        "criteria": {
            "category_seq": CATEGORY_SEQ,
            "subcategories": list(SUBCATEGORIES),
            "keywords": list(KEYWORDS),
            "keyword_must_mention": list(KEYWORD_MUST_MENTION),
            "excluded_subcategories": list(EXCLUDED_SUBCATEGORIES),
            "law_names": list(LAW_NAMES),
        },
        "failed": failed,
        "collected_at": collected_at,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    client = PublicDataClient(get_settings(), apis={})
    if not client.configured:
        print("PUBLIC_DATA_API_KEY가 .env에 없습니다. 저장소 루트 .env를 확인하세요.")
        return 1
    print(f"백문백답 수집 → {OUTPUT_DIR}")
    manifest = asyncio.run(collect(client, OUTPUT_DIR))
    print(f"완료: {manifest['count']}개 저장, 실패 {len(manifest['failed'])}개")
    for line in manifest["failed"]:
        print(f"  실패 {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
