import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { listAnalyses } from '../api'
import { GradeSeal } from '../components/GradeSeal'
import { formatDateTime } from '../utils/format'
import type { AnalysisListItem } from '../types/analysis'

export function HistoryPage() {
  const [items, setItems] = useState<AnalysisListItem[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    listAnalyses()
      .then((r) => alive && setItems(r))
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="history">
      <header className="page-head">
        <h1>분석 이력</h1>
        <p className="lede">지금까지 분석한 계약이에요. 같은 집을 다시 분석하면 새 줄로 남아요.</p>
      </header>

      {error ? (
        <div className="empty">
          <p className="form-error">{error}</p>
        </div>
      ) : items === null ? (
        <div className="empty" aria-busy="true">
          <p>이력을 불러오고 있어요…</p>
        </div>
      ) : items.length === 0 ? (
        <div className="empty">
          <p>아직 분석한 계약이 없어요.</p>
          <Link to="/" className="btn btn--primary">
            첫 서류 올리기
          </Link>
        </div>
      ) : (
        <ul className="history__list">
          {items.map((a) => (
            <li key={a.analysis_id}>
              <Link to={`/analyses/${a.analysis_id}`} className="history__row">
                <GradeSeal grade={a.grade} size="sm" />
                <span className="history__main">
                  <span className="history__addr">{a.address ?? '주소 없음'}</span>
                  <span className="history__meta">등급 {a.grade ?? '알 수 없음'}</span>
                </span>
                <time dateTime={a.created_at}>{formatDateTime(a.created_at)}</time>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
