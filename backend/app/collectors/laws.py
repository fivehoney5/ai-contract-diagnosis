"""국가법령정보 API로 법령 조문을 모아 data/knowledge_base/laws/에 JSONL로 저장합니다.

실행 (backend 폴더에서):
    python -m app.collectors.laws            # LAW_TARGETS 전부
    python -m app.collectors.laws 민법        # 이름에 '민법'이 들어간 대상만

한 줄 = 조문 하나. 항·호·목은 조문 text 안에 줄바꿈으로 이어 붙입니다.
API 응답의 상세 링크에는 OC(신청자 아이디)가 들어 있어서 저장하지 않고, 공개 주소를 따로 만듭니다.
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.clients.law import LawApiClient
from app.collectors.law_targets import LAW_TARGETS, LawTarget
from app.core.config import get_settings

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "knowledge_base" / "laws"


class LawNotFoundError(Exception):
    pass


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _clean(text: Any) -> list[str]:
    """API는 내용을 문자열 또는 문자열 목록으로 주고, 앞뒤에 탭·줄바꿈이 붙어 있습니다."""
    parts = text if isinstance(text, list) else [text]
    lines: list[str] = []
    for part in parts:
        if isinstance(part, list):
            lines.extend(_clean(part))
        elif isinstance(part, str):
            lines.extend(line.strip() for line in part.splitlines() if line.strip())
    return lines


def _date(yyyymmdd: str) -> str | None:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}" if len(yyyymmdd or "") == 8 else None


def article_label(unit: dict) -> str:
    branch = unit.get("조문가지번호")
    return f"제{unit['조문번호']}조" + (f"의{branch}" if branch else "")


def article_text(unit: dict) -> str:
    lines = _clean(unit.get("조문내용"))
    for para in _as_list(unit.get("항")):
        lines += _clean(para.get("항내용"))
        for item in _as_list(para.get("호")):
            lines += _clean(item.get("호내용"))
            for sub in _as_list(item.get("목")):
                lines += _clean(sub.get("목내용"))
    return "\n".join(lines)


def _is_deleted(text: str) -> bool:
    # 예: "제5조 삭제 <2008.3.21>"
    first = text.split("\n", 1)[0]
    return "삭제" in first and len(first) < 40 and "\n" not in text


def _in_range(unit: dict, ranges: tuple[tuple[int, int], ...] | None) -> bool:
    if ranges is None:
        return True
    number = int(unit["조문번호"])
    return any(start <= number <= end for start, end in ranges)


def build_records(detail: dict, target: LawTarget, collected_at: str) -> list[dict]:
    law = detail["법령"]
    info = law["기본정보"]
    law_id = info["법령ID"]
    law_name = info["법령명_한글"]
    law_type = info.get("법종구분", {}).get("content") if isinstance(info.get("법종구분"), dict) else None

    records: list[dict] = []
    chapter: str | None = None
    for unit in _as_list(law.get("조문", {}).get("조문단위")):
        if unit.get("조문여부") != "조문":  # 편·장·절 제목
            chapter = " ".join(_clean(unit.get("조문내용"))) or chapter
            continue
        if not _in_range(unit, target.articles):
            continue
        text = article_text(unit)
        label = article_label(unit)
        # 삭제된 조문, 다른 조로 옮겨져 번호만 남은 조문은 뺍니다.
        if not text or text == label or _is_deleted(text):
            continue
        records.append(
            {
                "id": f"law:{law_id}:{label}",
                "source_type": "law",
                "law_id": law_id,
                "law_name": law_name,
                "law_type": law_type,
                "chapter": chapter,
                "article": label,
                "article_title": unit.get("조문제목") or None,
                "text": text,
                "effective_date": _date(info.get("시행일자", "")),
                "promulgation_date": _date(info.get("공포일자", "")),
                "promulgation_no": info.get("공포번호"),
                "url": f"https://www.law.go.kr/법령/{quote(law_name)}/{quote(label)}",
                "collected_at": collected_at,
            }
        )
    return records


def pick_current_law(search_result: dict, name: str) -> dict:
    items = _as_list(search_result.get("LawSearch", {}).get("law"))
    for item in items:
        if item.get("법령명한글") == name and item.get("현행연혁코드", "현행") == "현행":
            return item
    found = ", ".join(i.get("법령명한글", "?") for i in items) or "없음"
    raise LawNotFoundError(f"'{name}'과 이름이 정확히 같은 현행 법령이 없습니다 (검색 결과: {found})")


def _file_name(law_name: str) -> str:
    return law_name.replace(" ", "_") + ".jsonl"


async def collect(client: LawApiClient, targets: tuple[LawTarget, ...], output_dir: Path) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    collected_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    summary: list[dict] = []
    for target in targets:
        found = pick_current_law(await client.search(target.name, display=100), target.name)
        detail = await client.detail(found["법령ID"])
        records = build_records(detail, target, collected_at)
        path = output_dir / _file_name(target.name)
        with path.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        summary.append(
            {
                "law_name": target.name,
                "law_id": found["법령ID"],
                "file": path.name,
                "articles": len(records),
                "article_range": [list(r) for r in target.articles] if target.articles else None,
                "effective_date": records[0]["effective_date"] if records else _date(found.get("시행일자", "")),
                "reason": target.reason,
                "collected_at": collected_at,
            }
        )
        print(f"  {target.name}: 조문 {len(records)}개 → {path.name}")
    return summary


def _write_manifest(output_dir: Path, summary: list[dict]) -> None:
    manifest_path = output_dir / "manifest.json"
    existing = {}
    if manifest_path.exists():
        existing = {e["law_name"]: e for e in json.loads(manifest_path.read_text(encoding="utf-8"))["laws"]}
    for entry in summary:
        existing[entry["law_name"]] = entry
    manifest = {
        "source": "국가법령정보 공동활용 Open API (https://open.law.go.kr)",
        "license": "법령은 저작권법 제7조에 따라 보호 대상이 아닌 저작물",
        "laws": sorted(existing.values(), key=lambda e: e["law_name"]),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    settings = get_settings()
    client = LawApiClient(settings)
    if not client.configured:
        print("LAW_API_OC가 .env에 없습니다. 저장소 루트 .env를 확인하세요.")
        return 1
    keyword = argv[0] if argv else None
    targets = tuple(t for t in LAW_TARGETS if keyword is None or keyword in t.name)
    if not targets:
        print(f"'{keyword}'에 맞는 대상이 없습니다. law_targets.py를 확인하세요.")
        return 1
    print(f"법령 {len(targets)}개 수집 → {OUTPUT_DIR}")
    summary = asyncio.run(collect(client, targets, OUTPUT_DIR))
    _write_manifest(OUTPUT_DIR, summary)
    print(f"완료: 조문 {sum(s['articles'] for s in summary)}개, manifest.json 갱신")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
