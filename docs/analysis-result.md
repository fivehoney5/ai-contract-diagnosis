# 분석 결과 형식 초안

업로드를 처리하는 서비스 서버와 분석 엔진이 주고받을 형식을 논의하기 위한 문서입니다. 예시는 모두 가상 데이터입니다.

## 역할

- 문서 분석 엔진(document/)은 숫자 계산과 위험 신호 판정을 합니다. 등급(`grade`), 항목별 신호(`flags`), 가격 카드, 특약 구역 텍스트를 만듭니다.
- AI 모듈(ai/)은 특약 구역 텍스트에서 특약 후보 문장을 고르고 의미·누락 여부를 검토하며, 각 신호에 검색 근거와 설명을 붙입니다.
- 서비스 서버(backend/)는 결과 조회 API를 제공하고, 프론트엔드는 이 형식에 맞춰 표시합니다.
- 첫 시연 화면에는 총점을 넣지 않고 등급과 신호 목록을 먼저 보여줍니다.

## 공통 규칙

- 금액은 원 단위 정수입니다.
- 비율은 0-1 소수이며, 계산에 필요한 값이 없으면 `null`입니다.
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
| `data_status.items[].data_source` | `price` 항목만. 공공 API(실거래가·건축물대장) 응답을 어디서 받았는지. `api`(새로 조회, 일부만 캐시여도 api), `cache`(모두 만료 전 캐시), `stale_cache`(API가 실패해 만료된 저장본 사용), API를 부르지 않았으면 `null`. `stale_cache`이고 `status`가 `ok`이면 `reason`에 저장 시각 안내가 들어갑니다. 화면에서 "저장된 데이터 기준"으로 표시할 수 있습니다 |
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
| `price_card.other_tenant_deposits` | 다가구 등에서 사용자가 입력한 다른 세대 보증금 합계. 넣으면 `senior_amount_used`에 더해짐. 안 넣으면 `null` |
| `price_card.confidence_label` | 시세 신뢰도가 `낮음`이면 `"추정 시세 기준 · 신뢰도 낮음"`, 아니면 `null`. 가격 카드에 그대로 표시 |
| `registry_summary` | 선순위 합계 카드용 요약. 등기부를 못 읽었거나 안 냈으면 `null` |
| `registry_summary.senior_amount_total` | 읽은 선순위 금액 합계 |
| `registry_summary.senior_counts` | 종류별 건수. `mortgage`(근저당), `hypothec`(저당권), `jeonse_right`(전세권), `lease_right`(임차권) |
| `registry_summary.summary_label` | 한 줄 요약. 예: `"근저당 2건 · 전세권 1건"`, 없으면 `"선순위 등기 없음"` |
| `registry_summary.senior_amount_missing_count` | 금액을 못 읽은 선순위 등기 건수. 1 이상이면 화면에 따로 표시 |
| `flags[]` | 신호 하나당 객체 하나. `code`, `level`(`안전`, `주의`, `위험`, `확인필요`), `value`, `threshold`, `source` |
| `special_terms.extraction_status` | 특약 구역 추출 상태. `ok`, `failed`. 실패하면 AI는 누락 대신 판단 보류로 처리 |
| `special_terms.section_text` | 마스킹을 마친 특약 구역 텍스트. 실패하면 `null` |
| `special_terms.masked` | 개인정보(주민번호·전화·계좌·전자우편·당사자 이름) 마스킹 처리를 했는지. 개인정보가 하나도 없다는 보장은 아님 |
| `special_terms.external_send_allowed` | 특약 텍스트를 외부 LLM에 보내도 되는지. 실제 계약서는 기본 `false`이고, 시연용 가상 계약서(`is_demo_data`)이면서 마스킹 뒤 주소나 이름으로 보이는 글자가 없을 때만 `true`. AI 모듈은 `masked`가 아니라 이 값을 보고 보냄 |
| `special_terms.masking` | `counts`(종류별로 가린 개수), `residual_risks`(남은 위험: `ADDRESS`, `POSSIBLE_NAME`), `is_demo_data`, `external_send_blocked_by`(`REAL_DOCUMENT`, `RESIDUAL_RISK`, 허용이면 `null`). 성공일 때만 |
| `special_terms.page` | 특약 칸이 시작하는 쪽 |
| `special_terms.form` | `standard_2023`(2023.10 개정 표준계약서 기본특약 확인) 또는 `unknown`. 성공일 때만 |
| `special_terms.base_terms[]` | 양식에 인쇄된 기본특약 ①-⑥. `no`, `text`, `note`, `choice`(체크박스 선택), `choice_status`(`selected`, `none_selected`, `unreadable`, `not_applicable`). 성공일 때만 |
| `special_terms.custom_terms[]` | `※ 기타` 아래 당사자가 직접 쓴 특약. `no`, `text`. AI 모듈의 특약 검토 대상. 성공일 때만 |
| `special_terms.custom_terms_text` | 직접 쓴 특약만 이은 텍스트. 없으면 `null`. 성공일 때만 |
| `special_terms.section_status` | 구역별 상태. `base_terms`(기본특약 ①-⑥), `custom_terms`(※ 기타). 값은 `read`(읽음), `empty`(비어 있음), `failed`(추출 실패). 추출에 실패하면 둘 다 `failed` |
| `special_terms.warnings[]` | `CUSTOM_MARKER_NOT_FOUND`, `BASE_TERMS_INCOMPLETE`, `NO_CUSTOM_TERMS`, `LOW_OCR_CONFIDENCE`, `END_MARKER_NOT_FOUND`. 자세한 뜻은 [document/contract](../document/contract/README.md). 성공일 때만 |

## 등급 정하는 방법 (팀 합의 2026-11-27)

- 주의 구간은 70/80입니다. 전세가율·선순위 부담률이 70% 이상이면 주의, 80% 초과면 위험입니다.
- 입력 주소와 등기부 주소가 다르면 `판단보류`입니다.
- `위험` 신호가 하나라도 있으면 `위험`입니다.
- 시세를 못 구했거나, 등기부를 못 읽었거나, 선순위 금액을 모르면 `판단보류`입니다.
- 등기부를 스캔본·사진(OCR)으로 읽었을 때 취소선만 있고 말소 등기가 없는 등기는 살아 있는 것으로 계산하고 `STRIKE_WITHOUT_CANCEL_ENTRY`(확인필요)를 띄웁니다.
- 다가구 등 집합건물이 아니면 `HIDDEN_SENIOR_CLAIM_CHECK_NEEDED`("다른 세대의 선순위 보증금 확인 필요")를 띄웁니다. 다른 세대 보증금 합계(`other_tenant_deposits`)를 모르면 `판단보류`이고, 입력하면 선순위에 더해 계산합니다.
- 시세 신뢰도가 `낮음`이면 가격 신호만 `주의`까지 낮추고, 가격 카드에 `confidence_label`을 붙입니다. 단, 비율이 100% 이상이면 신뢰도와 관계없이 `위험`입니다.
- 비율 구간 판정은 반올림 전 금액(보증금, 선순위, 시세)으로 합니다. `price_card`의 비율과 신호 `value`는 소수 넷째 자리로 반올림한 표시값이라, 예를 들어 0.80001은 0.8로 보이지만 80% 초과라 `위험`입니다.
- 그 밖에는 `flags`에서 가장 높은 `level`이 등급입니다. `확인필요`는 등급에 반영하지 않습니다.

## 특약 표시 (팀 합의 2026-11-27)

- 특약 추출에 실패하면 특약 부분만 판단보류이고, 전체 등급은 바뀌지 않습니다.
- 대신 `flags`에 `SPECIAL_TERMS_CHECK_NEEDED`(확인필요, "특약 확인 필요")를 넣어 전체 요약에 보이게 합니다. 기본특약·직접 쓴 특약 중 어느 구역이든 `failed`이면 넣습니다.
- 어느 구역이든 `failed`이면 `data_status`의 `special_terms`도 `failed`(전체 `incomplete`)입니다. 읽은 구역의 텍스트는 그대로 넘기고, 어느 구역을 못 읽었는지는 `section_status`로 구분합니다.
- 화면에서 "특약 없음"은 `special_terms.section_status.custom_terms`가 `empty`일 때만 씁니다. `failed`는 "특약 없음"으로 보여 주지 않습니다.
