# AI 및 RAG

지식베이스 정제, 근거 검색, 특약 분석과 수정안, 리포트 설명 및 답변 품질 평가를 담당합니다.

## 첫 리포트 카드

저장소 루트에서 가상 분석 예시로 확인합니다. 별도 패키지와 API 키가 필요하지 않습니다.

```powershell
Get-Content -Raw -Encoding UTF8 docs/examples/analysis-result-failed.json | python -X utf8 -m ai.report_cards
```

서버 연동 시 애플리케이션 시작 단계에서 공개 근거를 읽고, 분석 결과를 받으면 카드만 응답에 추가합니다.

```python
from ai.report_cards import build_report, load_knowledge_base

records = load_knowledge_base()
# analysis는 문서 분석 엔진 결과입니다.
analysis["report_cards"] = build_report(analysis, records)["report_cards"]
```

[가상 응답 예시](examples/first-report-example.json)의 `report_cards`를 화면에 표시합니다.
`SPECIAL_TERMS_CHECK_NEEDED` 신호가 없으면 목록은 비어 있습니다. 검색 근거가
없어도 특약 확인 카드는 유지됩니다. 검색은 공개 자료에만 수행하며 전체 등급은 유지합니다.
