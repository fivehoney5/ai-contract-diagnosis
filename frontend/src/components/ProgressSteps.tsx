import { useEffect, useState } from 'react'

interface ProgressStepsProps {
  title: string
  steps: string[]
  /** 한 단계를 보여 주는 시간(ms). 서버가 진행 상태를 주지 않아 시간으로 넘긴다. */
  stepMs?: number
  /** 서버 응답이 오기 전까지는 마지막 단계에서 기다린다 */
  finished: boolean
  note?: string
}

/** 분석이 어디까지 왔는지 단계별로 보여준다. 단계는 서버가 실제로 처리하는 순서다. */
export function ProgressSteps({ title, steps, stepMs = 1500, finished, note }: ProgressStepsProps) {
  const [current, setCurrent] = useState(0)
  const shown = finished ? steps.length : current

  useEffect(() => {
    if (finished || current >= steps.length - 1) return
    const t = window.setTimeout(() => setCurrent((c) => c + 1), stepMs)
    return () => window.clearTimeout(t)
  }, [current, steps.length, stepMs, finished])

  return (
    <section className="progress" aria-live="polite">
      <h2>{title}</h2>
      <ol>
        {steps.map((step, i) => {
          const state = i < shown ? 'done' : i === shown ? 'active' : 'waiting'
          return (
            <li key={step} className={`progress__step is-${state}`}>
              <span className="progress__mark" aria-hidden="true">
                {i < shown ? '✓' : i + 1}
              </span>
              <span>{step}</span>
              {state === 'done' && <span className="visually-hidden">완료</span>}
            </li>
          )
        })}
      </ol>
      {note && <p className="side-note">{note}</p>}
    </section>
  )
}
