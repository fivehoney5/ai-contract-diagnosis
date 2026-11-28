"""Build report cards from the document analysis result."""
import json
import sys


def build_report(analysis):
    cards = []
    for flag in analysis.get("flags", []):
        if flag["code"] == "SPECIAL_TERMS_CHECK_NEEDED":
            cards.append({
                "code": flag["code"],
                "level": flag["level"],
                "title": "특약 확인 필요",
                "description": "계약서의 특약 중 읽지 못한 부분이 있어 내용을 확인할 수 없었어요.",
                "actions": ["계약서 원본에서 읽지 못한 특약을 확인해 주세요."],
                "evidence": [],
            })
            break

    return {
        "analysis_id": analysis["analysis_id"],
        "grade": analysis["grade"],
        "report_cards": cards,
    }


if __name__ == "__main__":
    report = build_report(json.loads(sys.stdin.buffer.read()))
    sys.stdout.buffer.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
