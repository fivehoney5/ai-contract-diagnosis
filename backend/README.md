# 서비스 서버

인증, 업로드·분석 요청 API, 결과 저장과 분석 이력, 알림 일정 및 등기부 버전 비교를 담당합니다. 법령·판례 수집 연동도 이 역할에 포함됩니다.

## 구조

```
backend/
├── app/
│   ├── main.py          # FastAPI 앱 생성, CORS, 라우터 등록
│   ├── core/config.py   # 환경변수 설정 (저장소 루트 .env)
│   ├── collectors/      # 지식베이스 수집 (laws.py: 법령 조문, qna.py: 백문백답)
│   ├── services/        # 분석 실행(analysis_engine.py)과 결과 저장(analysis_store.py)
│   ├── clients/         # 외부 API 클라이언트
│   │   ├── law.py           # 국가법령정보 공동활용
│   │   └── public_data.py   # 공공데이터포털 (API 등록 목록 포함)
│   └── api/
│       ├── router.py    # 라우터 모음
│       ├── deps.py      # 클라이언트 주입
│       └── routes/      # 기능별 API (health.py, external.py, ...)
├── tests/               # 서버 단위 테스트
├── requirements.txt
└── requirements-dev.txt # 테스트 도구 포함
```

새 API는 `app/api/routes/`에 파일을 추가하고 `app/api/router.py`에 등록합니다.

## 실행

Python 3.11 이상이 필요합니다. 아래 명령은 `backend/` 폴더에서 실행합니다. `requirements.txt`에 `document/` 분석 모듈이 쓰는 패키지도 들어 있습니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # 처음 한 번, 값은 로컬에서만 채움
uvicorn app.main:app --reload
```

- 헬스체크: http://localhost:8000/api/health
- API 문서(Swagger): http://localhost:8000/docs

## 분석 요청 API

업로드한 등기부·계약서와 입력값으로 `document/` 모듈을 순서대로 돌려 [분석 결과 형식](../docs/analysis-result.md) 하나를 만들고 저장합니다.

| API | 하는 일 |
| --- | --- |
| `POST /api/analyses` | 분석 실행 후 결과 저장 (multipart/form-data) |
| `GET /api/analyses/{analysis_id}` | 저장된 결과 조회 |
| `GET /api/analyses` | 최근 분석 목록 (id, 시각, 등급, 주소) |

`POST /api/analyses` 입력:

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `address` | O | 주소. 동·호까지 쓰면 등기부 호수와 비교함 |
| `property_type` | O | `아파트`, `오피스텔`, `연립다세대` |
| `deposit` | O | 보증금(원) |
| `area_m2` |  | 전용면적(㎡). 없으면 등기부 전용면적을 씀 |
| `dong_nm`, `ho_nm` |  | 주소에 동·호가 없을 때 |
| `registry_file` |  | 등기사항전부증명서 PDF |
| `contract_files` |  | 계약서 PDF 또는 사진, 여러 장 가능 |

처리 순서는 주소 → 등기부 → 시세(등기부의 선순위 금액과 전용면적 사용) → 특약 → 위험 등급입니다. 빠진 입력이나 실패한 단계는 결과의 `data_status`에 남고, 왜 건너뛰었는지는 응답의 `notes`에 적습니다.

- 원본 파일은 저장하지 않고, 입력 요약과 결과만 `backend/var/analyses.db`(SQLite)에 저장합니다. DB가 정해지면 `analysis_store.py`만 바꿉니다.
- 특약 모듈(`document/contract`)이 아직 없으면 계약서는 읽지 않고 `notes`에 안내합니다.
- 주소는 `JUSO_API_KEY`, 시세는 국토교통부 실거래가·건축물대장 API를 활용신청한 `PUBLIC_DATA_API_KEY`가 있어야 합니다. 없으면 해당 부분이 `API_UNAVAILABLE`로 실패하고 등급은 `판단보류`가 됩니다.

## 외부 API 키 등록

저장소 루트의 `.env`에 넣습니다. 형식은 [.env.example](../.env.example)을 참고하세요.

| 변수 | 값 |
| --- | --- |
| `LAW_API_OC` | 국가법령정보 공동활용(open.law.go.kr) 신청 시 등록한 이메일의 `@` 앞부분 |
| `PUBLIC_DATA_API_KEY` | 공공데이터포털 마이페이지의 일반 인증키 중 **Decoding** 키 |

서버를 켜고 http://localhost:8000/docs 에서 확인합니다.

- `GET /api/external/status`: 키가 들어갔는지(값은 표시하지 않음)와 등록된 공공데이터 API 목록
- `GET /api/external/law/search?query=주택임대차보호법`: 법령 검색 (`target=prec`이면 판례)
- `GET /api/external/law/{ID}`: 법령·판례 본문
- `GET /api/external/public-data/{이름}?...`: 등록된 공공데이터 API 호출 (쿼리 파라미터는 그대로 전달)

### 공공데이터 API 추가

실거래가·건축물대장은 `document/price`가 직접 호출하므로 등록하지 않습니다. 그 밖에 서버에서 부를 API는 [public_data.py](app/clients/public_data.py)의 `PUBLIC_DATA_APIS`에 이름과 요청 경로를 추가합니다. 경로는 API 상세 페이지의 요청주소에서 `https://apis.data.go.kr` 뒤 부분입니다. `serviceKey`는 자동으로 붙습니다.

```python
"qna": PublicDataApi(path="/기관코드/서비스명/오퍼레이션", description="설명"),
```

코드에서는 `await client.call("qna", pageNo=1)`처럼 호출합니다.

## 지식베이스 수집

법령 조문과 백문백답을 모아 `data/knowledge_base/`에 저장합니다. 형식과 대상은 [지식베이스 README](../data/knowledge_base/README.md)를 참고하세요.

```bash
python -m app.collectors.laws   # 법령 조문 (LAW_API_OC 필요)
python -m app.collectors.qna    # 백문백답 (PUBLIC_DATA_API_KEY 필요)
```

## 테스트

```bash
pytest
```
