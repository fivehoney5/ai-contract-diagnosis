# 프론트엔드

계약서·등기부 업로드, OCR 결과 확인·수정, 위험 리포트와 특약 수정안, 알림 화면을 개발하는 영역입니다.

## 지금 있는 화면

서비스 서버(`backend/`)에 구현된 API만큼만 화면을 만들었습니다. 디자인은 `frontend_2026-11-28.zip` 시안(종이·인주 톤, IBM Plex Sans KR / Noto Serif KR)을 그대로 씁니다.

| 화면 | 경로 | 쓰는 API |
| --- | --- | --- |
| 새 분석 (서류 올리기) | `/` | `POST /api/analyses` |
| 리포트 | `/analyses/:id` | `GET /api/analyses/{id}` (분석 직후에는 POST 응답을 바로 씀) |
| 분석 이력 | `/history` | `GET /api/analyses` |

리포트는 [분석 결과 형식](../docs/analysis-result.md)을 따릅니다. 등급 도장, 위험 신호(`flags`, 확인필요는 따로), 시세와 비율(`price_card`), 선순위 합계(`registry_summary`), 특약 구역(기본특약 ①-⑥ / ※ 기타, `section_status`), 자료 상태(`data_status`), 서버 메모(`notes`)를 보여 줍니다.

시안에 있지만 서버 기능이 아직 없어 넣지 않은 화면: 추출 결과 확인·수정, 점수 계기판·영역별 배점(총점은 첫 시연 범위 밖), 근거 인용·특약 수정안(AI 모듈), 계약 후 모니터링·알림, 로그인. 서버에 API가 생기면 시안 코드를 옮겨 붙입니다.

## 실행

Node.js 20.19 이상이 필요합니다. 서비스 서버를 먼저 켜 둡니다 ([backend/README.md](../backend/README.md)).

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173
```

개발 서버는 `/api` 요청을 `http://localhost:8000`(FastAPI)으로 넘깁니다. 서버 주소가 다르면 `VITE_API_PROXY=http://주소:포트 npm run dev`로 바꿉니다. 빌드 결과를 다른 곳에 올릴 때는 `VITE_API_BASE`에 서버 주소를 넣습니다.

```bash
npm run build      # 타입 검사 + dist/ 생성
npm run lint       # oxlint
```

## 구조

```
src/
├── api/index.ts        # 서버 호출 (fetch)
├── types/analysis.ts   # 서버 응답 타입 (docs/analysis-result.md)
├── utils/              # 금액·날짜 표시, 코드값 → 화면 문구, 받는 파일 형식
├── components/         # 등급 도장, 위험 신호 카드, 파일 올리기 칸, 진행 단계, 레이아웃
├── pages/              # 업로드, 리포트, 이력, 없는 화면
└── styles/app.css      # 시안 스타일 + 서버 연동 화면 추가분(파일 끝)
```

신호 코드의 화면 문구는 `src/utils/labels.ts`에 있습니다. 서버에 새 코드가 생기면 여기에 제목과 할 일을 더합니다. 없는 코드는 코드 이름이 그대로 보입니다.
