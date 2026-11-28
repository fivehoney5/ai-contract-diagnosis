"""Build report cards from the document analysis result."""
import json
import sys

from .registry_evidence import load_registry_guides, search_registry_guides


def build_senior_burden_card(flag, price_card):
    ratio = price_card.get("senior_burden_ratio")
    if ratio is None:
        ratio = flag.get("value")
    description = "분석 결과에서 선순위 부담률에 대한 확인이 필요해요."
    if ratio is not None:
        description = (
            f"선순위 금액과 보증금의 합계가 추정 시세의 {ratio:.2%}예요."
        )
    deposit = price_card.get("deposit")
    senior = price_card.get("senior_amount_used")
    price = price_card.get("estimated_price")
    if all(amount is not None for amount in (deposit, senior, price)) and price > 0:
        description += f" 계산에 쓴 금액은 보증금 {deposit:,}원, 선순위 {senior:,}원, 추정 시세 {price:,}원이에요."
    confidence_label = price_card.get("confidence_label")
    if confidence_label:
        description += f" ({confidence_label})"
    return {
        "code": flag["code"],
        "level": flag["level"],
        "title": "선순위 부담률 확인",
        "description": description,
        "actions": ["분석에 사용된 선순위 금액과 시세 산정 근거를 확인해 주세요."],
        "evidence": [],
    }


def build_registry_card(flag, evidence):
    age = flag.get("value")
    description = "분석에 사용한 등기부의 발급·열람일이 서비스 기준보다 오래됐어요."
    if isinstance(age, int) and age >= 0:
        description = f"분석에 사용한 등기부의 발급·열람일은 {age}일 전이에요."
    actions = ["최신 등기부를 준비해 다시 확인해 주세요."]
    if evidence:
        actions.append("잔금 지급 직전에 등기부의 권리관계를 다시 확인해 주세요.")
        description += f" {evidence[0]['summary']}"
    return {
        "code": flag["code"],
        "level": flag["level"],
        "title": "등기부 재확인",
        "description": description,
        "actions": actions,
        "evidence": evidence,
    }


def build_report(analysis, *, registry_guides=None):
    cards = []
    seen = set()
    for flag in analysis.get("flags", []):
        code = flag["code"]
        if code in seen:
            continue
        seen.add(code)
        if code == "SENIOR_BURDEN_HIGH":
            cards.append(build_senior_burden_card(flag, analysis.get("price_card") or {}))
        elif code == "REGISTRY_OUTDATED":
            guides = load_registry_guides() if registry_guides is None else registry_guides
            cards.append(build_registry_card(flag, search_registry_guides(guides)))
        elif code == "SPECIAL_TERMS_CHECK_NEEDED":
            cards.append({
                "code": flag["code"],
                "level": flag["level"],
                "title": "특약 확인 필요",
                "description": "계약서의 특약 중 읽지 못한 부분이 있어 내용을 확인할 수 없었어요.",
                "actions": ["계약서 원본에서 읽지 못한 특약을 확인해 주세요."],
                "evidence": [],
            })

    return {
        "analysis_id": analysis["analysis_id"],
        "grade": analysis["grade"],
        "report_cards": cards,
    }


def enrich_analysis_result(analysis):
    """Add report cards before persisting the analysis."""
    return {**analysis, "report_cards": build_report(analysis)["report_cards"]}


if __name__ == "__main__":
    report = build_report(json.loads(sys.stdin.buffer.read()))
    sys.stdout.buffer.write((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
