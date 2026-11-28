# AI 및 RAG

지식베이스 정제, 근거 검색, 특약 분석과 수정안, 리포트 설명 및 답변 품질 평가를 담당합니다.

## 특약 확인 카드

팀의 분석 결과에서 `SPECIAL_TERMS_CHECK_NEEDED`가 있으면 특약 원본 확인을 안내합니다.
이 카드의 판단은 문서 추출 결과에서 오므로 공개 근거 목록은 비어 있습니다.
잔금 전 등기부 확인 안내는 별도 항목에서 다룹니다.

```powershell
Get-Content -Raw -Encoding UTF8 docs/examples/analysis-result-failed.json | python -X utf8 -m ai.report_cards
```

서버에서는 `build_report(analysis)["report_cards"]`를 분석 결과에 추가할 수 있습니다.
[가상 응답 예시](examples/first-report-example.json)를 참고하세요.

## 서버 연동

분석 결과 저장 전에 두 카드가 `result.report_cards`에 추가됩니다. 이전 결과에서 필드가 없으면 빈 목록으로 표시합니다.
