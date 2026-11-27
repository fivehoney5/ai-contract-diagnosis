"""특약 구역 텍스트의 개인정보를 가린다. AI 모듈·화면에는 가린 텍스트만 넘긴다.

가리는 것:
    - 주민등록번호·외국인등록번호 (앞 6자리-뒤 7자리)  -> ******-*******
    - 전화번호 (휴대폰, 지역번호)                      -> ***-****-****
    - 계좌번호처럼 보이는 숫자 묶음 (하이픈으로 나뉜 숫자 10자리 이상) -> [계좌번호]
    - 전자우편                                         -> [전자우편]
    - 계약서 당사자란(성명 칸)에서 읽은 이름이 특약에 나오면 -> ***

당사자란에 없는 이름(특약에만 처음 나오는 사람 이름)은 알아볼 방법이 없어 가리지 못한다 [한계].
금액(360,000,000원), 날짜(2027.1.29, 2027-01-29), 조항 번호는 건드리지 않는다.

masked는 "마스킹 처리를 했다"는 뜻일 뿐 개인정보가 하나도 없다는 보장이 아니다.
외부 LLM 전송 여부는 external_send_allowed로 따로 판단한다: 가린 뒤에도 주소나 이름으로 보이는 글자가 남으면
False이고, 남은 것의 종류를 masking.residual_risks에 적는다 (리뷰 반영, 실제 문서 연동 전 안전장치).
"""

from __future__ import annotations

import re

RRN_RE = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-8]\d{6}(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(?:01[016789]|0[2-6][0-9]?|070)\s*[-.)]\s*\d{3,4}\s*[-.]\s*\d{4}(?!\d)")
PHONE_PLAIN_RE = re.compile(r"(?<!\d)01[016789]\d{7,8}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ACCOUNT_RE = re.compile(r"(?<![\d-])\d{2,6}(?:-\d{2,8}){2,3}(?![\d-])")
DATE_RE = re.compile(r"^(19|20)\d{2}-\d{1,2}-\d{1,2}$")

# 당사자란 "성 명 김가람" / "성명: 김가람" / "대 표 박중개"
NAME_FIELD_RE = re.compile(r"(?:성\s*명|대\s*표)\s*[:：]?\s*([가-힣]{2,4})(?![가-힣])")
NOT_NAMES = {"서명", "날인", "주소", "전화", "주민", "등록번호", "또는", "및", "임대인", "임차인", "대리인", "성명"}


def party_names(texts: list[str]) -> list[str]:
    """계약서 전체 줄에서 당사자·중개사 이름을 모은다."""
    names = set()
    for t in texts:
        for m in NAME_FIELD_RE.finditer(t):
            name = m.group(1)
            if name not in NOT_NAMES and not name.startswith(("서명", "주민", "전화")):
                names.add(name)
    return sorted(names, key=lambda n: (-len(n), n))  # 긴 이름부터 가림


# 가린 뒤 남은 개인정보 의심 문구 (보수적으로 잡는다. 잘못 잡으면 전송만 막히고 결과는 그대로)
ADDRESS_RES = (
    # 도로명주소: 동일로 1414, 마들로 999. "보증금으로 1,000만원"처럼 숫자 뒤에 단위가 붙으면 주소가 아님
    re.compile(r"[가-힣]{1,10}(?:로|길)\s*\d+(?:-\d+)?"
               r"(?![\d,.]*\s*(?:원|개|년|월|일|%|만|천|억|회|명|대|층|평|㎡|시|분|건|번째|차|기|주))"),
    re.compile(r"\d+\s*동\s*\d+\s*호"),  # 101동 707호
    re.compile(r"(?<![가-힣])[가-힣]{1,6}(?:동|리|가)\s*\d+(?:-\d+)?\s*번지"),  # 지번: 상계동 123-4번지
    re.compile(r"(?:특별시|광역시|특별자치시|특별자치도|경기도|강원도|충청북도|충청남도|전라남도|경상북도|경상남도)"
               r"\s*[가-힣]{1,5}(?:시|군|구)"),  # 서울특별시 노원구
)
# 역할 이름 뒤에 띄어 쓴 2-4글자 + 조사 (예: "임차인 이하늘은"). OCR이 붙여 쓴 "임대인은임차인에게"는 잡지 않는다
ROLE_NAME_RE = re.compile(
    r"(?:임대인|임차인|대리인|소유자|중개사|보증인|매도인|매수인)(?:\s+|\s*[:(]\s*)([가-힣]{2,4}?)"
    r"(?=\s*(?:은|는|이|가|의|에게|께|님|씨|\)|,|$))")
NOT_PERSON = {"본인", "모두", "각각", "소유", "명의", "부담", "측", "쌍방", "전원", "상호", "본인은", "변경", "동의", "서명",
              "날인", "주소", "연락처", "또는", "및", "등", "모두가", "각자", "책임", "요청", "통지", "부담으로", "사정", "과실", "귀책", "의무", "권리", "보증금"}


def residual_risks(text: str | None) -> list[str]:
    """가린 텍스트에 남은 주소·이름 의심 문구의 종류. 비어 있으면 외부 전송 가능."""
    if not text:
        return []
    risks = []
    if any(r.search(text) for r in ADDRESS_RES):
        risks.append("ADDRESS")
    if any(m.group(1) not in NOT_PERSON and m.group(1) != "***" for m in ROLE_NAME_RE.finditer(text)):
        risks.append("POSSIBLE_NAME")
    return risks


def _mask_account(m: re.Match) -> str:
    s = m.group(0)
    if DATE_RE.match(s) or sum(ch.isdigit() for ch in s) < 10:
        return s
    return "[계좌번호]"


def mask_text(text: str | None, names: list[str], counts: dict) -> str | None:
    if not text:
        return text

    def sub(pattern, repl, s, key):
        def f(m):
            out = repl(m) if callable(repl) else repl
            if out != m.group(0):
                counts[key] = counts.get(key, 0) + 1
            return out
        return pattern.sub(f, s)

    text = sub(RRN_RE, "******-*******", text, "resident_no")
    text = sub(EMAIL_RE, "[전자우편]", text, "email")
    text = sub(PHONE_RE, "***-****-****", text, "phone")
    text = sub(PHONE_PLAIN_RE, "***-****-****", text, "phone")
    text = sub(ACCOUNT_RE, _mask_account, text, "account")
    for name in names:
        text = sub(re.compile(re.escape(name)), "***", text, "name")
    return text


def mask_special_terms(result: dict, all_texts: list[str]) -> dict:
    """analyze_contract 결과(성공)의 텍스트 칸을 모두 가리고 masked=True로 바꾼다."""
    names = party_names(all_texts)
    counts: dict = {}
    out = dict(result)
    out["section_text"] = mask_text(result.get("section_text"), names, counts)
    out["custom_terms_text"] = mask_text(result.get("custom_terms_text"), names, {})
    out["base_terms"] = [
        {**t, "text": mask_text(t["text"], names, {}), "note": mask_text(t.get("note"), names, {})}
        for t in result.get("base_terms", [])
    ]
    out["custom_terms"] = [{**t, "text": mask_text(t["text"], names, {})} for t in result.get("custom_terms", [])]
    out["masked"] = True
    risks = residual_risks(out["section_text"])
    out["masking"] = {"counts": counts, "party_names_found": len(names), "residual_risks": risks}
    # 외부 LLM 전송은 남은 위험이 없을 때만 허용. AI 모듈은 masked가 아니라 이 값을 본다
    out["external_send_allowed"] = not risks
    return out
