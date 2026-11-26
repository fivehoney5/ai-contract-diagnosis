# 분석 결과 형식 초안

업로드를 처리하는 서비스 서버와 분석 엔진이 주고받을 형식을 논의하기 위한 문서입니다. 예시는 모두 가상 데이터입니다.

## 역할

- 문서 분석 엔진(document/)은 숫자 계산과 위험 신호 판정을 합니다. 등급(`grade`), 항목별 신호(`flags`), 가격 카드, 특약 구역 텍스트를 만듭니다.
- AI 모듈(ai/)은 특약 구역 텍스트에서 특약 후보 문장을 고르고 의미·누락 여부를 검토하며, 각 신호에 검색 근거와 설명을 붙입니다.
- 서비스 서버(backend/)는 결과 조회 API를 제공하고, 프론트엔드는 이 형식에 맞춰 표시합니다.
- 첫 시연 화면에는 총점을 넣지 않고 등급과 신호 목록을 먼저 보여줍니다.

## 공통 규칙

- 금액은 원 단위 정수입니다.
- 비율은 0~1 소수이며, 계산에 필요한 값이 없으면 `null`입니다.
- 필드 이름은 snake_case입니다.
- 주소 키는 `"법정동코드(10자리)-본번(4자리)-부번(4자리)"` 문자열입니다.

## 예시

- [정상 분석](examples/analysis-result-ok.json)
- [시세·특약 추출 실패](examples/analysis-result-failed.json)

## 필드

| 필드 | 설명 |
| --- | --- |
| `grade` | 전체 등급. `안전`, `주의`, `위험`, `판단보류` |
| `data_status.overall` | `complete` 또는 `incomplete` (하나라도 실패하면 incomplete) |
| `data_status.items[]` | 부분별 상태. `part`는 `price`, `registry`, `special_terms`, `status`는 `ok`, `failed`, `not_provided` |
| `data_status.items[].reason_code` | 실패 코드. `ADDRESS_NOT_FOUND`, `NO_TRADES`, `API_UNAVAILABLE`, `PARSE_FAILED` |
| `property.housing_type` | 주택 유형. `아파트`, `오피스텔`, `연립다세대` |
| `price_card.deposit` | 보증금 |
| `price_card.senior_amount_used` | 선순위 계산에 실제 사용한 금액 (근저당은 채권최고액) |
| `price_card.estimated_price` | 추정 시세. 못 구하면 `null` |
| `price_card.sample_count` | 시세 산정에 쓴 거래 건수 |
| `price_card.method`, `method_label` | 시세 산정 방식 코드와 설명 |
| `price_card.base_date`, `trade_period` | 시세 기준일과 조회한 거래 기간 |
| `price_card.confidence` | 시세 신뢰도. `높음`, `중간`, `낮음` |
| `price_card.jeonse_ratio` | 보증금 / 시세 |
| `price_card.senior_burden_ratio` | (선순위 금액 + 보증금) / 시세 |
| `flags[]` | 신호 하나당 객체 하나. `code`, `level`(`안전`, `주의`, `위험`, `확인필요`), `value`, `threshold`, `source` |
| `special_terms.extraction_status` | 특약 구역 추출 상태. `ok`, `failed`. 실패하면 AI는 누락 대신 판단 보류로 처리 |
| `special_terms.section_text` | 마스킹을 마친 특약 구역 텍스트. 실패하면 `null` |

## 등급 정하는 방법 (초안)

- 시세를 못 구해서 비율을 계산할 수 없고 `위험` 신호도 없으면 `판단보류`입니다.
- 그 밖에는 `flags`에서 가장 높은 `level`이 등급입니다. `확인필요`는 등급에 반영하지 않습니다.
