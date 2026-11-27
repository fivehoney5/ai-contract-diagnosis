"""계약서 줄 목록에서 특약사항 칸을 찾아 기본특약(인쇄된 ①-⑥)과 직접 쓴 특약(※ 기타 아래)으로 나눈다.

주택임대차표준계약서(2023.10 개정) 특약사항 칸 모양:
    [특약사항]
    ① ... ⑥            <- 양식에 인쇄된 기본특약 (빈칸·체크박스만 채움)
    ※ 기타              <- 이 아래가 당사자가 직접 쓴 특약
    1. ...
    본 계약을 증명하기 위하여 ...   <- 서명란 (칸 끝)

특약 해석(유리·불리, 누락 판단)은 하지 않는다. AI 모듈이 custom_terms와 section_text를 받아 판단한다.
"""

from __future__ import annotations

import re

from .reader import Line

# 칸 시작: 공백을 지운 줄이 이것으로 시작
SECTION_HEADERS = ("[특약사항]", "【특약사항】", "<특약사항>", "특약사항", "[특약]", "특약")
# 칸 끝: 공백을 지운 줄에 이것이 있으면 그 줄부터 칸 밖
END_MARKERS = ("본계약을증명하기", "이의없음을확인", "서명또는날인", "서명및날인")
# 직접 쓴 특약 시작 표시 (공백 지운 뒤). OCR이 ※를 *, ※를 빼먹는 경우도 받는다
CUSTOM_MARKER = re.compile(r"^[※*＊·.\-]?\s*기타(?![가-힣])")
# 기본특약 번호
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
CIRCLED_RE = re.compile(rf"^\s*([{CIRCLED}])\s*")
# 원문자를 숫자로 읽은 기본특약 번호 ("2임대인이"). 직접 쓴 특약 "1."과 달리 마침표 없이 한글이 바로 붙는다
OCR_DIGIT_NO_RE = re.compile(r"^([1-6])\s?(?=[가-힣])")
# 직접 쓴 특약 번호: "1.", "1)", "(1)", "가." 등
CUSTOM_NO_RE = re.compile(r"^\s*(?:\(?(\d{1,2})[.)]|-|•|·)\s*")
# 쪽 번호 "- 2 / 4 -"
PAGE_FOOTER_RE = re.compile(r"^-?\s*\d+\s*/\s*\d+\s*-?$")

# 기본특약을 번호 없이도 알아보기 위한 핵심 문구 (공백 지운 뒤 비교). 2023.10 개정 표준계약서 기준
BASE_TERM_KEYS = {
    1: ("주택을인도받은임차인",),
    2: ("위특약에위반",),
    3: ("선순위임대차정보",),
    4: ("주택임대차분쟁조정위원회에조정을",),
    5: ("철거또는재건축",),
    6: ("상세주소부여",),
}
# 체크박스 선택지 (기본특약 번호별)
BASE_TERM_CHOICES = {4: ("동의", "미동의"), 5: ("없음", "있음"), 6: ("동의", "미동의")}
CHECKED = "■☑☒▣✔✓√"
UNCHECKED = "□☐"

# 양식에 인쇄된 안내 문구 (직접 쓴 특약이 아님). 공백 지운 뒤 포함 여부로 지운다 [추측: 양식 판본마다 다를 수 있음]
GUIDE_PHRASES = (
    "약정할사항이있으면기재",
    "대항력과우선변제권확보관련예시",
    "당사자사이합의에의한특약가능",
)

LOW_OCR_SCORE = 0.80

PARSE_FAILED = "PARSE_FAILED"


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def join_lines(texts: list[str]) -> str:
    """한 항목이 여러 줄로 나뉜 것을 잇는다. 표준계약서는 글자 단위로 줄을 바꿔서('약정|일자') 대부분 붙여 쓴다."""
    out = ""
    for t in texts:
        t = t.strip()
        if not t:
            continue
        if out and (out[-1] in ".,):;!?" or t[0] in "(※"):
            out += " "
        out += t
    return out


def _is_header(line: Line) -> bool:
    n = norm(line.text)
    return any(n.startswith(h) for h in SECTION_HEADERS) and len(n) <= len(SECTION_HEADERS[0]) + 6 \
        and not n.startswith("특약사항을") and "조" not in n[:3]


def find_section(lines: list[Line]) -> tuple[int, int, bool] | None:
    """(시작 줄 다음 인덱스, 끝 인덱스(제외), 끝 표시를 찾았는지). 머리말을 못 찾으면 None."""
    start = next((i for i, ln in enumerate(lines) if _is_header(ln)), None)
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        n = norm(lines[j].text)
        if any(m in n for m in END_MARKERS):
            return start + 1, j, True
    return start + 1, len(lines), False


def _base_no(text: str) -> int | None:
    m = CIRCLED_RE.match(text)
    if m:
        return CIRCLED.index(m.group(1)) + 1
    n = norm(text)[:40]
    for no, keys in BASE_TERM_KEYS.items():
        if all(k in n for k in keys):
            return no
    return None


def read_choice(text: str, no: int) -> tuple[str | None, str]:
    """체크박스 선택. (선택값, 상태) 상태는 selected / none_selected / unreadable.

    사진 OCR은 ■□를 거의 읽지 못하므로 unreadable이 흔하다. 이때 선택값을 추측하지 않는다.
    """
    options = BASE_TERM_CHOICES.get(no)
    if not options:
        return None, "not_applicable"
    n = norm(text)
    for opt in sorted(options, key=len, reverse=True):  # "미동의"를 "동의"보다 먼저
        if re.search(rf"[{CHECKED}]{opt}", n):
            return opt, "selected"
    if all(re.search(rf"[{UNCHECKED}]{opt}", n) for opt in options):
        return None, "none_selected"
    return None, "unreadable"


def split_base_terms(lines: list[Line]) -> list[dict]:
    """※ 기타 위쪽 줄들을 ①-⑥ 항목으로 나눈다. 번호 없이 시작하는 ※ 안내 줄은 앞 항목의 note로 붙인다."""
    items: list[dict] = []
    for ln in lines:
        t = ln.text.strip()
        no = _base_no(t)
        m = OCR_DIGIT_NO_RE.match(t)
        if no is None and m:
            # 사진 OCR이 ②·③을 "2임대인이…"처럼 숫자로 읽는 경우. 다음 차례 번호일 때만 원문자로 본다
            expected = (items[-1]["no"] or 0) + 1 if items else 1
            if int(m.group(1)) == expected:
                no, t = expected, t[m.end():]
        elif no is not None and m and int(m.group(1)) == no:  # 낱말로 번호를 찾았어도 앞 숫자는 뗀다
            t = t[m.end():]
        if no is not None and (not items or no != items[-1]["no"]):
            items.append({"no": no, "lines": [CIRCLED_RE.sub("", t)], "notes": []})
        elif items:
            if norm(t).startswith("※"):
                items[-1]["notes"].append(t)
            else:
                items[-1]["lines"].append(t)
        else:
            items.append({"no": None, "lines": [t], "notes": []})
    out = []
    for it in items:
        text = join_lines(it["lines"])
        # ⑤ 줄의 "※공사시기"처럼 항목 안에 붙은 ※는 그대로 둔다. 별도 줄의 ※ 안내만 note
        choice, choice_status = read_choice(text, it["no"]) if it["no"] else (None, "not_applicable")
        out.append({
            "no": it["no"],
            "text": text,
            "note": join_lines(it["notes"]) or None,
            "choice": choice,
            "choice_status": choice_status,
        })
    return out


def _strip_guide(lines: list[str]) -> list[str]:
    """※ 기타 아래 양식 안내·예시 문구를 지운다. 예시는 '[대항력과…예시]'부터 '특약 가능'까지."""
    out, in_example = [], False
    for t in lines:
        n = norm(t)
        if "대항력과우선변제권확보관련예시" in n:
            in_example = "특약가능" not in n
            continue
        if in_example:
            if "특약가능" in n:
                in_example = False
            continue
        if any(p in n for p in GUIDE_PHRASES):
            continue
        out.append(t)
    return out


def split_custom_terms(lines: list[str]) -> list[dict]:
    """직접 쓴 특약을 번호(1. 2. …) 기준으로 나눈다. 번호가 없으면 문장 끝(…다.)에서 나눈다."""
    lines = [t.strip() for t in lines if t.strip()]
    if not lines:
        return []
    numbered = any(CUSTOM_NO_RE.match(t) for t in lines)
    groups: list[list[str]] = []
    nos: list[int | None] = []
    for t in lines:
        m = CUSTOM_NO_RE.match(t)
        if numbered:
            if m or not groups:
                groups.append([t])
                nos.append(int(m.group(1)) if m and m.group(1) else None)
            else:
                groups[-1].append(t)
        else:
            if groups and not re.search(r"(다|함|음|것)\.?$", groups[-1][-1]):
                groups[-1].append(t)
            else:
                groups.append([t])
                nos.append(None)
    out = []
    for i, (g, no) in enumerate(zip(groups, nos), start=1):
        out.append({"no": no if no is not None else i, "text": join_lines(g)})
    return out


def extract_special_terms(lines: list[Line]) -> dict:
    """줄 목록 → 특약 구역 결과(실패 필드 제외). 특약사항 칸이 없으면 None."""
    lines = [ln for ln in lines if not PAGE_FOOTER_RE.match(ln.text.strip())]
    sec = find_section(lines)
    if sec is None:
        return None
    a, b, end_found = sec
    body = lines[a:b]
    warnings = []
    if not end_found:
        warnings.append("END_MARKER_NOT_FOUND")

    marker = next((i for i, ln in enumerate(body) if CUSTOM_MARKER.match(norm(ln.text))), None)
    if marker is not None:
        base_lines = body[:marker]
        rest = CUSTOM_MARKER.sub("", norm(body[marker].text))
        # OCR이 "※기타 1.임차인은…"처럼 한 줄로 붙인 경우 마커 뒤 글자를 살린다
        first = re.sub(r"^\s*[※*＊·.\-]?\s*기\s*타\s*", "", body[marker].text.strip()) if rest else ""
        custom_raw = ([first] if first else []) + [ln.text for ln in body[marker + 1:]]
    else:
        base_lines, custom_raw = body, []
        warnings.append("CUSTOM_MARKER_NOT_FOUND")

    base_terms = split_base_terms(base_lines)
    found_nos = {t["no"] for t in base_terms if t["no"]}
    is_standard = len(found_nos & set(BASE_TERM_KEYS)) >= 3
    if marker is None and not found_nos:
        # 표준계약서가 아닌 계약서: 칸 전체를 직접 쓴 특약으로 본다
        custom_raw, base_terms = [ln.text for ln in body], []
    elif is_standard and len(found_nos & set(BASE_TERM_KEYS)) < len(BASE_TERM_KEYS):
        warnings.append("BASE_TERMS_INCOMPLETE")

    custom_terms = split_custom_terms(_strip_guide(custom_raw))

    section_lines = []
    for t in base_terms:
        prefix = CIRCLED[t["no"] - 1] + " " if t["no"] else ""
        section_lines.append(prefix + t["text"])
        if t["note"]:
            section_lines.append(t["note"])
    if marker is not None:
        section_lines.append("※ 기타")
    section_lines += [c["text"] for c in custom_terms]

    scores = [ln.score for ln in body if ln.score is not None]
    ocr_score = round(sum(scores) / len(scores), 4) if scores else None
    if ocr_score is not None and ocr_score < LOW_OCR_SCORE:
        warnings.append("LOW_OCR_CONFIDENCE")
    if not custom_terms:
        warnings.append("NO_CUSTOM_TERMS")

    pages = sorted({ln.page for ln in lines[a - 1:b]})
    # 구역별 상태: read(읽음) / empty(비어 있음) / failed(추출 실패). OCR 실패가 "특약 없음"으로 보이지 않게
    # 직접 쓴 특약이 비었어도 ※ 기타를 못 찾았거나 OCR 신뢰도가 낮거나 칸 끝을 못 찾았으면 비었다고 단정하지 않는다
    if custom_terms:
        custom_status = "read"
    elif marker is not None and not {"LOW_OCR_CONFIDENCE", "END_MARKER_NOT_FOUND"} & set(warnings):
        custom_status = "empty"
    else:
        custom_status = "failed"
    if base_terms:
        base_status = "failed" if "BASE_TERMS_INCOMPLETE" in warnings else "read"
    else:
        base_status = "empty"
    return {
        "section_text": "\n".join(section_lines),
        "page": pages[0] if pages else None,
        "pages": pages,
        "form": "standard_2023" if is_standard else "unknown",
        "base_terms": base_terms,
        "section_status": {"base_terms": base_status, "custom_terms": custom_status},
        "custom_marker_found": marker is not None,
        "custom_terms": custom_terms,
        "custom_terms_text": "\n".join(c["text"] for c in custom_terms) or None,
        "ocr_score": ocr_score,
        "warnings": warnings,
    }
