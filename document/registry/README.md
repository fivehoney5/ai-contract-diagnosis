# 등기부 권리정보 추출

인터넷등기소에서 발급한 등기사항전부증명서(집합건물) PDF에서 표제부·갑구·을구를 읽고, 말소된 등기를 가려낸 뒤 선순위 금액과 위험 신호를 만듭니다. 결과는 [분석 결과 형식 초안](../../docs/analysis-result.md)의 조각이고, 신호 규칙은 [리스크 규칙표](../../docs/risk-rules.md)를 따릅니다.

## 설치와 실행

```bash
pip install -r document/registry/requirements.txt
python -m unittest discover -s document/registry/tests -v   # 저장소 루트에서
```

- `reportlab`은 테스트에서 가상 등기부 PDF를 만들 때만 씁니다.
- PDF 테스트는 한글 TTF 글꼴이 필요합니다. Windows는 맑은 고딕을 자동으로 찾고, 다른 환경은 `KOREAN_TTF` 환경변수에 글꼴 경로를 넣습니다. 글꼴이나 라이브러리가 없으면 PDF 테스트만 건너뜁니다.
- 테스트는 모두 지어낸 데이터입니다. 실제 등기부 PDF는 저장소에 올리지 않습니다(.gitignore가 `*.pdf`를 막음).

## 사용법

```python
from document.registry import analyze_registry
from document.price import analyze_price

reg = analyze_registry("등기부.pdf")          # 경로, bytes, 파일 객체 모두 가능
price = analyze_price(..., senior_amount_used=reg["senior_amount_used"])
```

`analyze_registry`는 예외를 내지 않습니다. 읽지 못하면 `data_status_item`이 `PARSE_FAILED`이고 `senior_amount_used`는 `None`입니다.

| 상황 | reason_code | reason 예 |
| --- | --- | --- |
| 글자 층이 없는 스캔 PDF | `PARSE_FAILED` | "글자 층이 없습니다 (스캔 이미지로 보임). OCR 연동 전이라 읽지 못합니다" |
| PDF가 아니거나 손상·암호화 | `PARSE_FAILED` | "PDF를 열 수 없습니다" |
| 등기부 표(표제부·갑구·을구)가 없음 | `PARSE_FAILED` | "등기부 표를 찾지 못했습니다" |

## 결과

| 키 | 내용 |
| --- | --- |
| `data_status_item` | `part: "registry"` 상태 |
| `property` | 표시용 주소(쪽 머리의 `[집합건물]` 줄), 도로명주소, 호수, 전유 면적(㎡), 구조 |
| `senior_amount_used` | 선순위 합계(원). 시세 모듈 `analyze_price(senior_amount_used=...)`에 넣으면 `senior_burden_ratio`가 계산됨 |
| `registry_card` | 선순위 내역, 권리 종류별 건수, 소유권 이력(이름 마스킹), 가장 빠른 담보물권 접수일, 열람일 |
| `flags` | 등기부 신호 (아래 표) |
| `detail.entries` | 갑구·을구 항목 전체. 순위번호, 종류, 금액, `status`(active/cancelled), `cancel_basis` |

### 말소 판정

둘 중 하나라도 해당하면 `cancelled`입니다. `cancel_basis`에 근거를 남깁니다.

- `strike`: 행 글자의 50% 이상을 가로선이 지나감. 글자 높이 25-80% 사이를 지나는 선만 취소선으로 보므로 표 테두리는 걸리지 않습니다.
- `note`: 같은 구에 "N번…말소" 등기가 있음 (예: `1번근저당권설정등기말소`).
- `parent`: 부기등기(N-M)의 원 등기가 말소됨.

### 선순위 합계

말소되지 않은 근저당권 채권최고액 + 저당권 채권액 + 전세권 전세금 + 주택임차권 임차보증금. 근저당권변경(부기) 등기에 채권최고액이 있으면 그 금액으로 바꿉니다. 질권 등은 근저당과 겹치므로 더하지 않습니다.

### 신호

| code | level | value / threshold | 조건 |
| --- | --- | --- | --- |
| `OWNERSHIP_RESTRICTED` | 위험 | 건수 / 1 | 말소되지 않은 압류·가압류·가처분·경매개시결정 |
| `PROVISIONAL_REGISTRATION` | 위험 | 건수 / 1 | 말소되지 않은 가등기 |
| `TRUST_REGISTERED` | 위험 `[초안]` | 건수 / 1 | 말소되지 않은 신탁 (`trust_level` 인자로 바꿀 수 있음) |
| `LEASE_RIGHT_REGISTERED` | 위험 | 건수 / 1 | 말소되지 않은 주택임차권등기 |
| `JEONSE_RIGHT_EXISTS` | 주의 | 건수 / 1 | 말소되지 않은 전세권 |
| `LAND_RIGHT_CHECK_NEEDED` | 확인필요 | - | 집합건물인데 대지권 표시 없음, 또는 "별도등기 있음" |
| `REGISTRY_OUTDATED` | 주의 `[초안]` | 경과 일수 / 7 | 열람일이 분석일보다 7일 이상 전 (`max_age_days`) |
| `SENIOR_AMOUNT_UNREADABLE` (신규) | 확인필요 | 건수 / 1 | 살아 있는 근저당권·전세권·임차권인데 금액을 못 읽음. 선순위 합계가 실제보다 적을 수 있음 |

선순위 부담률 신호(`SENIOR_BURDEN_HIGH`, 0.7 이상 주의 / 0.8 초과 위험)는 시세가 필요하므로 여기서 내지 않습니다.

## 개인정보

- 권리자 칸 원문은 결과에 넣지 않습니다. 대표 권리자 이름만 남기고, 개인은 `***`, 법인·기관(은행, 주식회사, 공단 등)은 이름을 그대로 둡니다.
- 주민등록번호와 주소는 결과에 남기지 않습니다.

## 아직 안 한 것

- 스캔 PDF OCR (지금은 `PARSE_FAILED`).
- 소유자·임대인 일치(`OWNER_MISMATCH`): 계약서 임대인란과 메모리에서만 비교하는 함수가 필요합니다.
- 최우선변제(`PRIORITY_REPAYMENT_INFO`): `earliest_security_date`는 내보내지만 지역·기간별 금액 표가 아직 없습니다.
- 집합건물 실제 등기부로 확인 (지금까지는 일반건물 실제 등기부 1건과 가상 집합건물 PDF로 확인).
- 일반건물(다가구 등)은 전유부분이 없어서 `exclusive_area_m2`가 `None`이고 구조만 채웁니다.

## 실제 등기부 확인 (2026-11-26)

인터넷등기소에서 발급한 일반건물 등기부 1건(4쪽)을 로컬에서만 읽어 확인했습니다. 파일과 내용은 저장소에 없습니다.

- 취소선은 빨간색 `line` 객체로 그려지고, 표 테두리는 검은 선입니다. 글꼴은 BatangChe 내장이라 글자 층이 그대로 읽힙니다.
- 을구 말소 4건(전세권 3, 주택임차권 1)이 모두 취소선과 말소 등기 둘 다로 잡혔습니다.
- 표시변경·근저당권변경으로 일부 줄만 그어진 행(약 30%)은 살아 있는 등기로 남았습니다.
- `1(전2)`처럼 옛 등기부에서 옮겨 온 순위번호 표시를 떼도록 고쳤습니다.
