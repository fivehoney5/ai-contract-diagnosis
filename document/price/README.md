# 시세 산정 모듈 (document/price)

국토교통부 매매 실거래가(공공데이터포털)로 집의 시세를 추정하고, 보증금과 비교해 전세가율과 선순위 부담 비율을 계산합니다. 결과는 [분석 결과 형식](../../docs/analysis-result.md)의 가격 카드, 부분 상태(`data_status`), 신호(`flags`) 모양으로 돌려줍니다.

지원 유형은 아파트, 오피스텔, 연립다세대(빌라)입니다. LLM은 쓰지 않습니다.

- 금액은 모두 **원 단위 정수**입니다. API의 거래금액 `"63,400"`(만원)은 `634000000`원으로 바꿉니다.
- 비율은 **0-1 소수**(소수점 4자리)이고, 계산할 수 없으면 `null`입니다.

## 파일 구성

| 파일 | 하는 일 |
| --- | --- |
| `rtms_client.py` | 실거래가 API를 불러 거래 목록으로 바꿈 (해제된 거래 제외, 실패하면 한 번 재시도) |
| `building_register.py` | 건축물대장 API로 건축년도(사용승인일), 주용도, 호별 용도를 가져옴 |
| `estimator.py` | 거래 목록으로 시세 추정 (내부 결과 `PriceEstimate`) |
| `analysis_result.py` | 추정 결과를 팀 분석 결과 형식으로 바꿈 (`analyze_price`) |
| `tests/` | 인터넷 없이 도는 테스트와 실제 API 확인 스크립트(`live_check.py`) |

## 준비

1. Python 3.10 이상을 씁니다 (3.12에서 확인).
2. 저장소 루트에서 패키지를 설치합니다.

```powershell
python -m pip install -r document/price/requirements.txt
```

3. 저장소 루트의 `.env`에 공공데이터포털 Decoding 키를 넣습니다. `.env`는 깃에 올라가지 않습니다. 키는 채팅이나 코드에 붙여넣지 않습니다.

```
PUBLIC_DATA_API_KEY=여기에_Decoding_키
```

## 테스트 실행

저장소 루트에서 실행합니다. 인터넷과 키 없이 돕니다.

```powershell
python -m unittest discover -s document/price/tests -v
```

실제 API로 확인 (키 필요, 예: 강남구 대치동 은마 76.79㎡, 보증금 15억):

```powershell
python document/price/tests/live_check.py --type 아파트 --lawd 11680 --dong 대치동 --building 은마 --area 76.79 --deposit 1500000000
```

- `--lawd`: 법정동코드 앞 5자리 (시군구, 예: 11680 = 서울 강남구)
- `--dong`: 법정동 이름 (행정동 "역삼1동"이 아니라 "역삼동")
- `--building`: 건물명 또는 지번 (예: "316")
- `--area`: 전용면적(㎡), `--deposit`: 보증금(원)
- `--bjdong`, `--jibun`, `--dong-nm`, `--ho`: 건축물대장 조회용 (아래 참고)

## 코드에서 쓰는 법

```python
from document.price import analyze_price

r = analyze_price(
    "연립다세대", "11500", "화곡동", "355-14", 41.5,
    deposit=200_000_000,
    senior_amount_used=24_000_000,  # 등기부에서 계산한 선순위 금액 (모르면 생략 -> 비율 null)
    bjdong_cd="1150010300",         # 넣으면 건축물대장으로 건축년도·용도 확인
    dong_nm="A동", ho_nm="401",
)
r["data_status_item"]  # data_status.items[]에 넣을 price 부분 상태
r["property"]          # address_key, housing_type, exclusive_area_m2, build_year
r["price_card"]        # 가격 카드
r["flags"]             # 시세·건물 신호
r["detail"]            # 내부 추정 결과 전체 (세부 이유 코드, 근거 거래, notes). 확인용
```

API 오류도 예외 대신 `data_status_item`의 실패 코드로 돌려줍니다. 등급(`grade`)과 선순위 비율 신호(`SENIOR_BURDEN_HIGH`)는 위험 점수 모듈에서 정합니다.

### 가격 카드 (`price_card`)

| 칸 | 뜻 |
| --- | --- |
| `deposit` | 보증금(원) |
| `senior_amount_used` | 선순위 계산에 쓴 금액(원). 넣지 않으면 `null` |
| `estimated_price` | 추정 시세(원). 못 구하면 `null` |
| `sample_count` | 시세 산정에 쓴 거래 건수 |
| `method`, `method_label` | 아래 "시세를 정하는 방법"의 기준 코드와 설명 |
| `base_date` | 조회한 날 |
| `trade_period` | 조회한 거래 기간 (`from`: 12개월 전 달의 1일, `to`: 조회한 날) |
| `confidence` | `높음`, `중간`, `낮음` |
| `jeonse_ratio` | 보증금 / 시세 |
| `senior_burden_ratio` | (선순위 금액 + 보증금) / 시세 |

### 실패 코드 (`data_status_item.reason_code`)

| 팀 코드 | 언제 | 세부 코드 (`detail.reason_code`) |
| --- | --- | --- |
| `NO_TRADES` | 시세에 쓸 거래가 없거나 부족함 | `NO_TRADES_IN_REGION`, `NO_TRADES_IN_DONG`, `ONLY_BULK_TRADES`, `INSUFFICIENT_SAMPLES`, `NO_BUILDING_TRADES`, `BUILD_YEAR_UNKNOWN` |
| `ADDRESS_NOT_FOUND` | 시군구코드가 올바르지 않거나, 건물명이 여러 건물에 걸려 어느 건물인지 모름 | `BUILDING_NOT_IDENTIFIED` |
| `API_UNAVAILABLE` | 연결 실패, 서버 오류, 인증키 오류, `.env`에 키 없음 | 없음 (`detail`은 `null`) |
| `PARSE_FAILED` | API 응답이 XML이 아니라 읽지 못함 | 없음 (`detail`은 `null`) |

세부 코드 뜻:

| 코드 | 뜻 |
| --- | --- |
| `NO_TRADES_IN_REGION` | 시군구에 조회 기간 동안 거래가 없음 |
| `NO_TRADES_IN_DONG` | 시군구에는 있지만 그 동에 거래가 없음 (동 이름 확인) |
| `ONLY_BULK_TRADES` | 그 동 거래가 모두 일괄거래로 제외됨 |
| `NO_BUILDING_TRADES` | 신축(3년 이내)인데 같은 건물 거래가 0건 ("신축 등으로 시세 확인 불가") |
| `BUILD_YEAR_UNKNOWN` | 같은 건물 거래가 0건이고 건축년도도 몰라 신축인지 판단 불가 |
| `BUILDING_NOT_IDENTIFIED` | 건물명에 해당하는 건물이 여러 곳이고 건축년도도 몰라 추정 불가 (지번을 넣으면 해결) |
| `INSUFFICIENT_SAMPLES` | 거래가 있지만 필요한 거래 수를 못 채움 |

### 신호 (`flags`)

| code | level | 언제 |
| --- | --- | --- |
| `NO_BUILDING_TRADES` | 주의 | 신축인데 같은 건물 거래가 없음 (`value` 0, `threshold` 1) |
| `PRICE_INFLATION_SUSPECTED` | 주의 (임시) | 신축 ㎡당 가격이 같은 동 비슷한 면적·연식 거래보다 30% 넘게 높음 (`value`는 초과 비율) |
| `NON_RESIDENTIAL` | 주의 (임시) | 건축물대장 주용도 또는 해당 호 용도가 주거용이 아님 |
| `UNIT_PURPOSE_CHECK_NEEDED` | 확인필요 | `ho_nm`으로 조회한 같은 호수가 여러 건(보통 다른 동)이고 주거용 여부가 갈림. 첫 결과로 판정하지 않음. `dong_nm`을 넣으면 해결 |
| `VIOLATION_BUILDING_CHECK_NEEDED` | 확인필요 | 항상. 공공데이터 API에는 위반건축물 항목이 없어 열람본으로 확인해야 함 |

## 시세를 정하는 방법

최근 12개월 매매 거래에서 아래 순서로 처음 맞는 기준을 씁니다. 평균이 아니라 **중앙값**을 씁니다.

| 순서 | 기준 (`method`) | 계산 | 필요한 거래 수 |
| --- | --- | --- | --- |
| 1 | 같은 건물 + 비슷한 면적(±5%) (`same_building_similar_area`) | 거래금액 중앙값 | 1건 이상 |
| 2 | 같은 건물, 면적 무관 (`same_building_any_area`) | ㎡당 단가 중앙값 × 면적 | 3건 이상 |
| 3 | 같은 동 + 비슷한 면적(±10%) + 비슷한 건축년도(±5년) (`same_dong_similar_area`) | 거래금액 중앙값 | 3건 이상 |
| 4 | 같은 동 + 비슷한 건축년도(±5년), 면적 무관 (`same_dong_any_area`) | ㎡당 단가 중앙값 × 면적 | 3건 이상 |

**같은 건물 거래가 0건일 때** (일괄거래로 빠져서 남은 거래가 없는 경우 포함)

| 경우 | 결과 |
| --- | --- |
| 신축 (준공 3년 이내) | 시세 없음, `NO_BUILDING_TRADES` |
| 구축 (준공 3년 초과) | 3·4단계(같은 동·비슷한 연식)로 추정, 신뢰도 "낮음" |
| 건축년도 모름 | 시세 없음, `BUILD_YEAR_UNKNOWN` (`bjdong_cd`로 건축물대장을 조회하거나 `build_year`를 넣으면 다시 추정) |

**같은 건물 찾기**: 지번을 넣으면 지번으로 찾습니다. 건물명은 정확히 같은 이름을 먼저 찾고, 없으면 부분 일치를 보는데 건물이 하나만 걸릴 때만 인정합니다. 여러 건물이 걸리거나 이름은 같은데 지번이 다르면(예: 화곡동 "위하우스" 163-7은 2026년, 355-14는 2015년) 1·2단계를 건너뛰고 `detail.building_candidates`에 후보를 남깁니다.

**빼는 거래**
- 해제된 거래
- 일괄거래로 보이는 거래: 같은 건물·같은 날 3건 이상이면서 직거래나 법인 거래가 섞인 묶음
- 직거래이면서 매수·매도인이 모두 법인인 거래 (1건이어도 뺌, 여러 호실을 한 건으로 신고한 경우가 있어서)
- 매수자가 공공기관(LH 등)인 거래는 위 조건에 걸려도 빼지 않습니다.
- 가격만 보고 거르는 이상치 필터는 넣지 않았습니다.

**신뢰도**: 높음은 같은 건물·비슷한 면적 2건 이상(신축은 3건 이상), 중간은 같은 건물 ㎡당 환산이거나 신축인데 같은 건물 거래 1-2건, 낮음은 같은 동 기준이거나 근거가 1건(신축 제외)입니다.

**신축 부풀림 비교**: 준공 3년 이내 건물을 같은 건물 거래로 추정했으면 ㎡당 가격을 같은 동·비슷한 면적(±10%)·비슷한 연식(±3년) 거래(같은 건물 제외, 3건 이상)의 ㎡당 중앙값과 비교합니다. 30%를 넘게 높으면 `PRICE_INFLATION_SUSPECTED`입니다. 근거 거래가 모두 공공기관 매수면 비교하지 않습니다. 기준은 `inflation_threshold`, 연식 범위는 `inflation_year_tol`로 바꿀 수 있습니다.

## 건축물대장 연결

`bjdong_cd`(10자리 법정동코드)를 넣으면 건축물대장 표제부를 조회해서 건축년도(사용승인 연도)와 주용도를 가져옵니다.

- `build_year`를 직접 넣지 않았으면 건축물대장의 사용승인 연도를 씁니다 (`detail.build_year_source`: `input`, `building_register`, `trades`).
- 지번은 `jibun` → `building`이 지번이면 그것 → 같은 건물 거래의 지번 순으로 찾습니다.
- 동마다 사용승인일이 다르면 가장 늦은 날짜를 씁니다.
- 건축물대장 조회가 실패해도 시세 추정은 계속하고 `detail.notes`에 이유를 남깁니다.
- 1층만 근린생활시설인 빌라가 많아서 계약서의 동·호를 `dong_nm`, `ho_nm`으로 넣는 것이 정확합니다.
- 동 없이 호만 넣었는데 같은 호수가 여러 동에 있으면: 용도가 모두 같으면 그대로 판정하고, 다르면 판정하지 않고 `UNIT_PURPOSE_CHECK_NEEDED`를 남깁니다.

## 나중에 붙일 기능과 연결 지점

지금은 만들지 않았고, 붙일 때 아래 입력과 연결 지점을 쓰면 됩니다.

- **주소 → 법정동코드 변환 (도로명주소 API)**: 계약서 주소에서 `lawd_cd`(앞 5자리), `bjdong_cd`(10자리), 법정동 이름(`dong`, 실거래가의 `umdNm`과 같은 이름), 지번(`jibun`, 예: "355-14", 산 여부 포함), 건물명, 동·호(`dong_nm`, `ho_nm`)를 돌려주면 `analyze_price`에 그대로 넣을 수 있습니다. 변환에 실패하면 `ADDRESS_NOT_FOUND`로 돌려주면 됩니다.
- **조회 결과 캐시 (SQLite)**: `estimate_price`와 `analyze_price`는 `fetcher(ptype, lawd_cd, months, today)`와 `building_fetcher(bjdong_cd, jibun, sigungu_cd=, dong_nm=, ho_nm=)`를 바꿔 끼울 수 있습니다. 캐시는 이 두 함수를 감싸서 (유형, 시군구, 년월)과 (법정동코드, 지번)을 키로 저장하면 됩니다. 이번 달 거래는 신고가 늦게 들어오므로 짧게 보관하는 것이 좋습니다.

## 사용하는 API

| 이름 | 요청주소 |
| --- | --- |
| 아파트 매매 | `https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade` |
| 오피스텔 매매 | `https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade` |
| 연립다세대 매매 | `https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade2/getRTMSDataSvcRHTrade2` |
| 건축물대장 표제부 | `https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo` |
| 건축물대장 전유공용면적 | `https://apis.data.go.kr/1613000/BldRgstHubService/getBrExposPubuseAreaInfo` |

모든 주소는 2026-11-25에 실제 키로 응답을 확인했습니다.

**강서구 법정동코드 (확인함)**: 염창동 1150010100, 등촌동 10200, 화곡동 10300, 가양동 10400, 마곡동 10500, 내발산동 10600, 외발산동 10700, 공항동 10800, 방화동 10900, 개화동 11000 (앞 5자리 11500 동일).
