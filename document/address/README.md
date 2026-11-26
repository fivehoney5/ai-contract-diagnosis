# 주소 변환 모듈 (document/address)

사용자가 입력한 주소(도로명 또는 지번)를 행정안전부 도로명주소 검색 API로 찾아서 팀 주소 키로 바꿉니다. 시세 모듈(`document/price`)에 넣을 법정동코드, 지번, 동·호도 함께 돌려줍니다. LLM은 쓰지 않습니다.

- 주소 키: `"법정동코드(10자리)-본번(4자리)-부번(4자리)"` ([분석 결과 형식](../../docs/analysis-result.md)), 예: `1168010100-0123-0000`
- 실패해도 예외를 던지지 않고 팀 실패 코드를 돌려줍니다.

## 파일 구성

| 파일 | 하는 일 |
| --- | --- |
| `juso_client.py` | 도로명주소 검색 API 호출 (연결 실패·서버 오류면 한 번 재시도) |
| `resolver.py` | 주소 문자열 → 주소 키·법정동코드·지번·동·호 (`resolve_address`), 시세 모듈 인자로 바꾸기 (`to_price_args`) |
| `cache.py` | 검색 결과 캐시. `get`/`save` 인터페이스와 SQLite 구현 |
| `tests/` | 인터넷 없이 도는 테스트와 실제 API 확인 스크립트(`live_check.py`) |

## 준비

1. 패키지는 시세 모듈과 같습니다 (`requests`, `python-dotenv`).
2. 저장소 루트 `.env`에 도로명주소 검색 API 승인키를 넣습니다. 키는 채팅이나 코드에 붙여넣지 않습니다.

```
JUSO_API_KEY=여기에_승인키
```

## 테스트 실행

저장소 루트에서 실행합니다. 인터넷과 키 없이 돕니다.

```powershell
python -m unittest discover -s document/address/tests -v
```

실제 API로 확인 (키 필요, 키 값은 출력하지 않음):

```powershell
python document/address/tests/live_check.py "서울 강남구 테헤란로 152" "서울 강서구 화곡동 355-14 B동 401호"
```

## 코드에서 쓰는 법

```python
from document.address import resolve_address, to_price_args, SQLiteAddressCache
from document.price import analyze_price

r = resolve_address("서울 강서구 화곡동 355-14 B동 401호", cache=SQLiteAddressCache())
if r["status"] == "ok":
    a = r["address"]
    a["address_key"]   # "1150010300-0355-0014"
    price = analyze_price("연립다세대", area=41.5, deposit=200_000_000, **to_price_args(a))
else:
    r["reason_code"]   # ADDRESS_NOT_FOUND / API_UNAVAILABLE / PARSE_FAILED
    r["candidates"]    # 후보가 여러 개일 때 최대 5개
```

## 결과 모양

| 칸 | 뜻 |
| --- | --- |
| `status` | `ok` 또는 `failed` |
| `reason_code`, `reason` | 실패 코드와 한글 설명. 성공이면 `null` |
| `input` | 입력한 주소 그대로 |
| `address` | 아래 주소 정보. 실패면 `null` |
| `candidates` | 후보가 여러 개라 못 정했을 때 후보 목록 (`address_key`, `road_address`, `jibun_address`, `building_name`, `is_mountain`) |
| `notes` | 참고 문구 (같은 지번에 건물 여러 개, 산 지번, 다시 찾은 검색어 등) |
| `source` | 출처 |

`address` 칸:

| 칸 | 예 | 뜻 |
| --- | --- | --- |
| `address_key` | `1150010300-0355-0014` | 팀 주소 키. **산 지번이면 `null`** |
| `bjdong_cd` | `1150010300` | 법정동코드 10자리 (시세 모듈 `bjdong_cd`) |
| `sigungu_cd` | `11500` | 시군구코드 5자리 (시세 모듈 `lawd_cd`) |
| `plat_gb` | `0` | 대지 `0`, 산 `1` (건축물대장 `platGbCd`) |
| `is_mountain` | `false` | 산 지번인지 |
| `bun`, `ji` | `0355`, `0014` | 본번, 부번 (4자리) |
| `jibun` | `355-14` | 시세 모듈 `jibun` 형식. 산이면 `산 81-24` |
| `legal_dong_name` | `화곡동` | 법정동 이름 (시세 모듈 `dong`) |
| `ri_name` | `null` | 리 이름 (읍·면 지역만) |
| `road_address`, `jibun_address` | | 도로명주소, 지번주소 전체 |
| `zip_code`, `building_name`, `building_mgmt_no` | | 우편번호, 건물명, 건물관리번호 |
| `is_apartment_complex` | `false` | 공동주택 여부 (API `bdKdcd`) |
| `dong_nm`, `ho_nm` | `B동`, `401` | 주소 끝에서 읽은 동·호 (인자로 넣으면 그 값). 시세 모듈 형식과 같음 |

## 실패 코드

| 코드 | 언제 |
| --- | --- |
| `ADDRESS_NOT_FOUND` | 일치하는 주소가 없음, 후보가 여러 지번에 걸림(`candidates` 참고), 검색어 문제(시도명만 입력, 한 글자 등, API 오류 E0005-E0015) |
| `API_UNAVAILABLE` | 연결 실패, 서버 오류(HTTP 5xx, -999), 승인키 오류(E0001, E0014), `.env`에 키 없음 |
| `PARSE_FAILED` | 응답이 JSON이 아니거나 모양이 다름, 법정동코드·본번 값이 이상함 |

## 규칙

- **동·호 읽기**: 주소 끝의 `101동 1203호`, `B동 401호`, `제1동 제201호`, `401호`를 떼어서 `dong_nm`, `ho_nm`에 넣고 검색어에서는 뺍니다. 동은 숫자·영문이나 한 글자(`가동`)만 인정합니다. `화곡동 401호`의 화곡동은 법정동 이름이라 동으로 보지 않습니다.
- **검색어 정리**: 괄호 내용, `3층`, 쉼표, API가 거부하는 특수문자를 지웁니다. 결과가 0건이면 `...로 12-3` 또는 `...동 산 12-3`까지만 잘라서 한 번 더 찾습니다(뒤에 붙은 건물명 때문에 못 찾는 경우).
- **후보 여러 개**: 결과가 모두 같은 지번(같은 주소 키)이면 성공으로 보고 `notes`에 남깁니다. 지번이 다르면 `ADDRESS_NOT_FOUND`와 후보 최대 5개를 돌려줍니다.
- **산 지번**: 법정동코드·본번·부번·`plat_gb`는 채우고 `address_key`만 `null`입니다. 지금 주소 키 형식에 산을 표시할 칸이 없기 때문입니다 (팀 확인 필요). 건물이 없는 산 지번은 도로명주소 API에 없어서 `ADDRESS_NOT_FOUND`가 됩니다.
- **캐시**: 정상 응답(0건 포함)만 저장하고 API 오류는 저장하지 않습니다. 기본 위치는 `data/local/address_cache.sqlite`(깃에 안 올라감), 30일 지나면 다시 조회합니다. 다른 저장소를 쓰려면 `get(keyword)`, `save(keyword, total, juso)`만 맞춘 객체를 `cache=`로 넘깁니다.
