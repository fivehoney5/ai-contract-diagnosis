import type { Grade } from '../types/analysis'
import { toneOfGrade } from '../utils/format'

interface GradeSealProps {
  grade: Grade | null
  size?: 'lg' | 'sm'
}

/**
 * 등급 도장. 첫 시연 범위에는 총점이 없어서(docs/analysis-result.md) 점수 계기판 대신
 * 서류에 찍는 인주 도장 모양으로 등급만 보여 준다.
 */
export function GradeSeal({ grade, size = 'lg' }: GradeSealProps) {
  const tone = toneOfGrade(grade)
  const label = grade ?? '알 수 없음'
  return (
    <div className={`seal seal--${size} seal--${tone}`} role="img" aria-label={`등급 ${label}`}>
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r="54" className="seal__ring" />
        <circle cx="60" cy="60" r="46" className="seal__ring seal__ring--inner" />
      </svg>
      <span className="seal__text" aria-hidden="true">
        {label}
      </span>
    </div>
  )
}
