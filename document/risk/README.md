# 위험 등급 모듈 (document/risk)

주소·시세·등기부·특약 모듈이 돌려준 부분 결과를 합쳐서 팀 분석 결과 전체([분석 결과 형식](../../docs/analysis-result.md))를 만듭니다. 등급(`grade`), 합친 신호(`flags`), 부분별 데이터 상태(`data_status`)를 정합니다. 표준 라이브러리만 쓰고 네트워크·LLM 호출은 없습니다. 총점은 첫 시연 범위에서 빠져서 만들지 않습니다.

## 파일 구성

| 파일 | 하는 일 |
| --- | --- |
| `config.py` | 기준값과 등급·level 이름. 팀 합의 전 값은 모두 여기서만 바꿉니다 |
| `grader.py` | 비율 신호 만들기, 신호 합치기, 등급 정하기, 결과 조립 (`build_analysis_result`) |
| `tests/` | 가상 입력만 쓰는 테스트. `docs/examples`의 JSON 2개를 그대로 만들어 내는지 확인 |

## 테스트 실행

저장소 루트에서 실행합니다.

```powershell
python -m unittest discover -s document/risk/tests -v
```

## 코드에서 쓰는 법

각 모듈 결과 dict를 그대로 넘깁니다. 없는 부분은 넘기지 않으면 `not_provided`가 됩니다.

```python
from document.risk import build_analysis_result

result = build_analysis_result(
    address=addr_result,          # document/address resolve_address() 결과
    price=price_result,           # document/price analyze_price() 결과
    registry=registry_result,     # document/registry analyze_registry() 결과
    special_terms=terms_result,   # 특약 구역 추출 결과 (작업 ⑥, 아래 참고)
    analysis_id="...",
)
result["grade"]   # 안전 / 주의 / 위험 / 판단보류
```

이 모듈은 다른 모듈을 import하지 않습니다. 주소(#7)·등기부(#8) 모듈이 병합되기 전에도 결과 모양만 맞으면 동작합니다.

## 규칙

### 비율 신호

| code | 값 | 주의 | 위험 |
| --- | --- | --- | --- |
| `JEONSE_RATIO_HIGH` | `price_card.jeonse_ratio` (보증금 / 시세) | 0.7 이상 | 0.8 초과 |
| `SENIOR_BURDEN_HIGH` | `price_card.senior_burden_ratio` ((선순위 + 보증금) / 시세) | 0.7 이상 | 0.8 초과 |

- `threshold`에는 걸린 level의 경계값을 넣습니다 (주의면 0.7, 위험이면 0.8).
- 0.8은 "초과"가 아니라서 주의입니다.
- `analyze_price`에 선순위 금액을 넣지 않았으면 등기부 결과의 `senior_amount_used`로 채우고 선순위 부담률을 다시 계산합니다. 시세 결과에 값이 있으면 그 값을 씁니다.

### 신호 합치기

- 시세 모듈·등기부 모듈 신호와 비율 신호를 모읍니다.
- 같은 `code`는 하나만 남깁니다. level이 높은 쪽, 같으면 먼저 들어온 쪽(비율 → 시세 → 등기부 순).
- level 높은 순(위험 → 주의 → 안전 → 확인필요)으로 정렬합니다.
- 시세 신뢰도가 `낮음`이면 시세 영역 신호(`JEONSE_RATIO_HIGH`, `SENIOR_BURDEN_HIGH`, `NO_BUILDING_TRADES`, `PRICE_INFLATION_SUSPECTED`)는 위험을 주의로 낮추고 `source` 끝에 "(시세 신뢰도 낮음: 주의까지만 반영)"을 붙입니다. 등기부 신호는 낮추지 않습니다.

### 등급

1. 위험 신호가 하나라도 있으면 `위험`입니다. 데이터 일부가 빠졌어도 이미 위험이 확인됐기 때문입니다.
2. 시세 또는 등기부가 `ok`가 아니면(실패, 미제출) `판단보류`입니다.
3. 그 밖에는 가장 높은 level이 등급입니다. `확인필요`는 반영하지 않고, 신호가 없으면 `안전`입니다.

### 데이터 상태

- `data_status.items`는 `price`, `registry`, `special_terms` 순서입니다.
- 주소를 못 찾아서 시세 결과가 없으면 `price` 항목에 주소 실패 코드(`ADDRESS_NOT_FOUND` 등)를 그대로 씁니다.
- 셋 다 `ok`일 때만 `overall`이 `complete`입니다.

### 특약 (작업 ⑥ 연결 지점)

`special_terms`에는 아래 모양을 넘깁니다. 특약 구역을 못 읽으면 특약 부분만 `failed`(판단 보류)가 되고, 전체 등급에는 반영하지 않습니다 (`config.py`의 `special_terms_failure_holds_grade`로 바꿀 수 있음).

```python
{"extraction_status": "ok",        # 또는 "failed"
 "section_text": "마스킹한 특약 구역 텍스트",
 "page": 2, "masked": True,
 "reason_code": "PARSE_FAILED",     # 실패일 때 (생략하면 PARSE_FAILED)
 "reason": "..."}                   # 실패일 때 (생략하면 기본 문구)
```

`extraction_status`가 `ok`라도 텍스트가 비어 있으면 실패로 봅니다.

## 팀 합의가 필요한 것

1. 70% 주의 구간: 70/80(지금 값)과 기준표 초안 60/70 중 무엇으로 갈지. `config.py`에서 바꿉니다.
2. 등기부 실패·미제출일 때 판단보류로 둘지 (지금은 판단보류).
3. 특약 추출 실패가 전체 등급을 판단보류로 만들지 (지금은 아님, 특약 부분만 판단 보류).
4. 시세 신뢰도 낮음일 때 낮추는 신호 범위 (지금은 시세 영역 4개, 선순위 부담률 포함).
5. `property.address_display` 우선순위: 주소 모듈 지번주소 → 도로명주소 → 등기부 표제부 주소 (지금 값).
6. `special_terms`를 넘기지 않으면 `special_terms` 칸이 `null`이고 상태가 `not_provided`입니다. 화면에서 이 경우를 어떻게 보여줄지.
7. 등기부 선순위 내역(`registry_card`)은 지금 결과 형식에 칸이 없어 넣지 않았습니다. 화면에 보여줄지.

## 남은 작업

- 주소(#7)·등기부(#8) 병합 후: 주소 → 시세 → 등기부 → 등급까지 한 번에 부르는 `analyze()` 추가 (등기부 `senior_amount_used`를 `analyze_price`에 바로 넣기).
- 특약 추출(작업 ⑥) 결과를 `special_terms`로 연결.
