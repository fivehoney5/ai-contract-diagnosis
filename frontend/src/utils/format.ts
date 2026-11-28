import type { FlagLevel, Grade } from '../types/analysis'

/** 200000000 → "2억 원", 230000000 → "2억 3,000만 원", 70000000 → "7,000만 원" */
export function formatKRW(value: number): string {
  const eok = Math.floor(value / 100_000_000)
  const man = Math.round((value % 100_000_000) / 10_000)
  const parts: string[] = []
  if (eok > 0) parts.push(`${eok}억`)
  if (man > 0) parts.push(`${man.toLocaleString('ko-KR')}만`)
  if (parts.length === 0) return value > 0 ? `${value.toLocaleString('ko-KR')}원` : '0원'
  return `${parts.join(' ')} 원`
}

/** 0.7467 → "74.7%". 서버 값은 소수 넷째 자리 표시값이라 소수 첫째 자리까지 보여 준다. */
export function formatPercent(ratio: number): string {
  const pct = Math.round(ratio * 1000) / 10
  return `${pct.toLocaleString('ko-KR')}%`
}

/** "2026-12-20" 또는 ISO 시각 → "2026. 12. 20." */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${y}. ${Number(m)}. ${Number(d)}.`
}

/** ISO 시각 → "2026. 11. 28. 14:05" */
export function formatDateTime(iso: string): string {
  const time = iso.length > 10 ? iso.slice(11, 16) : ''
  return time ? `${formatDate(iso)} ${time}` : formatDate(iso)
}

export type Tone = 'safe' | 'caution' | 'danger' | 'hold'

export function toneOfGrade(grade: Grade | null): Tone {
  if (grade === '위험') return 'danger'
  if (grade === '주의') return 'caution'
  if (grade === '안전') return 'safe'
  return 'hold'
}

export function toneOfLevel(level: FlagLevel): Tone {
  if (level === '위험') return 'danger'
  if (level === '주의') return 'caution'
  if (level === '안전') return 'safe'
  return 'hold'
}
