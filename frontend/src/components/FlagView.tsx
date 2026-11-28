import type { Flag } from '../types/analysis'
import { formatPercent, toneOfLevel } from '../utils/format'
import { flagText } from '../utils/labels'

function measure(flag: Flag, unit: 'ratio' | 'count' | 'days' | undefined): string | null {
  if (flag.value === null || flag.value === undefined) return null
  if (unit === 'ratio') {
    const th = flag.threshold !== null ? ` (기준 ${formatPercent(flag.threshold)})` : ''
    return `${formatPercent(flag.value)}${th}`
  }
  if (unit === 'count') return `${flag.value}건`
  if (unit === 'days') return `발급 후 ${flag.value}일`
  return null
}

/** 위험 신호 하나. 제목 앞 네모 표식의 색이 level, 출처는 아래에 작게. */
export function FlagView({ flag }: { flag: Flag }) {
  const tone = toneOfLevel(flag.level)
  const text = flagText(flag.code)
  const m = measure(flag, text.unit)
  return (
    <article className={`risk-item risk-item--${tone}`}>
      <header className="risk-item__head">
        <h3>
          <span className="risk-item__mark" aria-hidden="true" />
          {text.title}
        </h3>
        <span className={`tag tag--${tone}`}>{flag.level}</span>
      </header>
      {m && <p className="risk-item__reason flag__value">{m}</p>}
      {text.action && (
        <p className="risk-item__action">
          <strong>할 일</strong>
          {text.action}
        </p>
      )}
      <p className="flag__source">
        <cite>{flag.source}</cite>
      </p>
    </article>
  )
}
