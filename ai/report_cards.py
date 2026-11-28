"""Build the first report-card prototype from the team's analysis JSON."""
import argparse
import json
import sys
from pathlib import Path

SEARCH_TERMS = ("잔금", "등기부", "근저당", "권리관계", "재확인")


def load_records(path):
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def load_knowledge_base(root=None):
    """Read public evidence records once at backend startup."""
    if root is None:
        root = Path(__file__).resolve().parents[1] / "data" / "knowledge_base"
    paths = [
        *sorted((root / "laws").glob("*.jsonl")),
        *sorted((root / "qna").glob("*.jsonl")),
        root / "guides" / "registry-recheck.jsonl",
    ]
    return [record for path in paths for record in load_records(path)]


def search_registry_evidence(records):
    matches = []
    for record in records:
        if not record.get("url"):
            continue
        # Match the passage that supports the action, then use its title for ranking.
        text = record.get("text") or record.get("answer") or ""
        passages = [
            line.strip()
            for line in text.splitlines()
            if all(term in "".join(line.split()) for term in ("잔금", "직전", "등기부", "확인"))
        ]
        if not passages:
            continue
        title = record.get("title") or record.get("question") or " ".join(
            record[key] for key in ("law_name", "article", "article_title") if record.get(key)
        )
        summary = passages[0]
        corpus = "".join((title + " " + summary).split())
        score = sum(term in corpus for term in SEARCH_TERMS)
        matches.append((score, {
            "id": record["id"],
            "title": title,
            "url": record["url"],
            "summary": summary,
        }))
    matches.sort(key=lambda match: (-match[0], match[1]["id"]))
    return [evidence for _, evidence in matches[:3]]


def build_report(analysis, records=()):
    cards = []
    for flag in analysis.get("flags", []):
        if flag["code"] == "SPECIAL_TERMS_CHECK_NEEDED":
            evidence = search_registry_evidence(records)
            actions = ["계약서 원본에서 읽지 못한 특약을 확인해 주세요."]
            if evidence:
                actions.append("잔금 송금 직전에 등기부를 다시 확인해 주세요.")
            cards.append({
                "code": flag["code"],
                "level": flag["level"],
                "title": "특약 확인 필요",
                "description": "계약서의 특약 중 읽지 못한 부분이 있어 내용을 확인할 수 없었어요.",
                "actions": actions,
                "evidence": evidence,
            })
            break

    return {
        "analysis_id": analysis["analysis_id"],
        "grade": analysis["grade"],
        "report_cards": cards,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, action="append", default=[], help="검색 자료 JSONL 경로")
    args = parser.parse_args()
    records = ([record for path in args.source for record in load_records(path)]
               if args.source else load_knowledge_base())
    report = build_report(json.loads(sys.stdin.buffer.read()), records)
    sys.stdout.buffer.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
