# 서비스 서버

인증, 업로드·분석 요청 API, 결과 저장과 분석 이력, 알림 일정 및 등기부 버전 비교를 담당합니다. 법령·판례 수집 연동도 이 역할에 포함됩니다.

## 구조

```
backend/
├── app/
│   ├── main.py          # FastAPI 앱 생성, CORS, 라우터 등록
│   ├── core/config.py   # 환경변수 설정 (저장소 루트 .env)
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

Python 3.11 이상이 필요합니다. 아래 명령은 `backend/` 폴더에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp ../.env.example ../.env   # 처음 한 번, 값은 로컬에서만 채움
uvicorn app.main:app --reload
```

- 헬스체크: http://localhost:8000/api/health
- API 문서(Swagger): http://localhost:8000/docs

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
- `GET /api/external/public-data/{이름}?...`: 등록된 공공데이터 API 호출, 예: `apt_rent?LAWD_CD=11110&DEAL_YMD=202410`

### 공공데이터 API 추가

활용신청한 API는 [public_data.py](app/clients/public_data.py)의 `PUBLIC_DATA_APIS`에 이름과 요청 경로를 추가합니다. 경로는 API 상세 페이지의 요청주소에서 `https://apis.data.go.kr` 뒤 부분입니다. `serviceKey`는 자동으로 붙습니다.

```python
"qna": PublicDataApi(path="/기관코드/서비스명/오퍼레이션", description="설명"),
```

코드에서는 `await client.call("qna", pageNo=1)`처럼 호출합니다.

## 테스트

```bash
pytest
```
