import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { ApiError, getAnalysis } from '../api'
import { FlagView } from '../components/FlagView'
import { GradeSeal } from '../components/GradeSeal'
import { formatDate, formatDateTime, formatKRW, formatPercent } from '../utils/format'
import { PART_LABEL, REASON_LABEL, TERMS_WARNING_LABEL, flagText } from '../utils/labels'
import type { AnalysisRecord, DataStatusItem, Grade, SpecialTerms } from '../types/analysis'
import { NotFoundPage } from './NotFoundPage'

const SUMMARY: Record<Grade, string> = {
  위험: '이대로 계약하면 보증금을 잃을 수 있어요. 아래 위험 신호가 해결되기 전에는 계약을 다시 생각해 보세요.',
  주의: '확인하고 고쳐야 할 부분이 있어요. 아래 할 일을 마친 뒤 계약하세요.',
  안전: '큰 위험 신호는 찾지 못했어요. 그래도 「직접 확인할 것」은 빠뜨리지 말고 챙기세요.',
  판단보류: '판단에 필요한 정보가 모자라 등급을 정하지 못했어요. 아래 빠진 부분을 채워 다시 분석해 주세요.',
}

export function ReportPage() {
  const { id = '' } = useParams()
  const location = useLocation()
  const passed = location.state as AnalysisRecord | null
  // 분석 직후에는 업로드 화면이 넘겨준 결과를 바로 쓰고, 이력에서 열면 서버에서 불러온다.
  // id가 바뀌면 key 때문에 새로 그려져 상태가 처음부터 시작된다.
  return <ReportLoader key={id} id={id} initial={passed && passed.analysis_id === id ? passed : null} />
}

function ReportLoader({ id, initial }: { id: string; initial: AnalysisRecord | null }) {
  const [record, setRecord] = useState<AnalysisRecord | null>(initial)
  const [error, setError] = useState<ApiError | null>(null)
  const needFetch = initial === null

  useEffect(() => {
    if (!needFetch) return
    let alive = true
    getAnalysis(id)
      .then((r) => alive && setRecord(r))
      .catch((e: unknown) => alive && setError(e instanceof ApiError ? e : new ApiError(0, String(e))))
    return () => {
      alive = false
    }
  }, [id, needFetch])

  if (error?.status === 404) return <NotFoundPage />
  if (error) {
    return (
      <div className="narrow empty">
        <h1>리포트를 불러오지 못했어요</h1>
        <p>{error.message}</p>
        <Link to="/history" className="btn btn--primary">
          분석 이력 보기
        </Link>
      </div>
    )
  }
  if (!record) {
    return (
      <div className="narrow empty" aria-busy="true">
        <p>리포트를 불러오고 있어요…</p>
      </div>
    )
  }
  return <Report record={record} />
}

function Report({ record }: { record: AnalysisRecord }) {
  const r = record.result
  const input = record.input
  const prop = r.property
  const card = r.price_card
  const reg = r.registry_summary
  const signals = r.flags.filter((f) => f.level !== '확인필요')
  const checks = r.flags.filter((f) => f.level === '확인필요')
  const missing = r.data_status.items.filter((i) => i.status !== 'ok')
  const priceItem = r.data_status.items.find((i) => i.part === 'price')

  return (
    <article className="report">
      <header className="report__head">
        <div className="report__title">
          <p className="report__date">{formatDateTime(r.analyzed_at ?? record.created_at)} 분석</p>
          <h1>{prop?.address_display ?? input.address}</h1>
          <dl className="report__facts">
            <div>
              <dt>보증금</dt>
              <dd>{formatKRW(input.deposit)}</dd>
            </div>
            <div>
              <dt>유형</dt>
              <dd>{prop?.housing_type ?? input.property_type}</dd>
            </div>
            {(prop?.exclusive_area_m2 ?? input.area_m2) && (
              <div>
                <dt>전용면적</dt>
                <dd>{prop?.exclusive_area_m2 ?? input.area_m2}㎡</dd>
              </div>
            )}
            {prop?.build_year && (
              <div>
                <dt>준공</dt>
                <dd>{prop.build_year}년</dd>
              </div>
            )}
          </dl>
          <p className="report__summary">{SUMMARY[r.grade]}</p>
        </div>
        <GradeSeal grade={r.grade} />
      </header>

      <div className="report__body">
        <div className="report__main">
          {r.grade === '판단보류' && (
            <section className="notice notice--hold">
              <h2>등급을 정하지 못한 이유</h2>
              <ul>
                {missing.map((i) => (
                  <li key={i.part}>
                    <strong>{PART_LABEL[i.part]}</strong>: {partReason(i)}
                  </li>
                ))}
                {r.flags.some((f) => f.code === 'REGISTRY_ADDRESS_MISMATCH') && (
                  <li>
                    <strong>주소</strong>: {flagText('REGISTRY_ADDRESS_MISMATCH').title}
                  </li>
                )}
                {r.flags.some((f) => f.code === 'HIDDEN_SENIOR_CLAIM_CHECK_NEEDED') && (
                  <li>
                    <strong>선순위</strong>: 다가구 등은 다른 세대 보증금을 알아야 선순위 부담률을 계산할 수 있어요.
                  </li>
                )}
                {missing.length === 0 && card?.senior_burden_ratio === null && (
                  <li>
                    <strong>선순위</strong>: 선순위 금액을 몰라 부담률을 계산하지 못했어요.
                  </li>
                )}
              </ul>
            </section>
          )}

          <section className="report__section" aria-labelledby="signals">
            <h2 id="signals">위험 신호 {signals.length}개</h2>
            {signals.length === 0 ? (
              <p className="empty">찾은 위험 신호가 없어요.</p>
            ) : (
              <div className="stack">
                {signals.map((f) => (
                  <FlagView key={f.code} flag={f} />
                ))}
              </div>
            )}
          </section>

          {checks.length > 0 && (
            <section className="report__section" aria-labelledby="checks">
              <h2 id="checks">직접 확인할 것 {checks.length}개</h2>
              <p className="section-lede">서류만으로는 알 수 없어 직접 확인해야 하는 항목이에요. 등급에는 넣지 않았어요.</p>
              <div className="stack">
                {checks.map((f) => (
                  <FlagView key={f.code} flag={f} />
                ))}
              </div>
            </section>
          )}

          <SpecialTermsSection terms={r.special_terms} contractPages={input.contract_pages} />

          {record.notes.length > 0 && (
            <section className="report__section" aria-labelledby="notes">
              <h2 id="notes">분석 메모</h2>
              <ul className="notes">
                {record.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <aside className="report__side">
          <section className="side-block">
            <h2>시세와 비율</h2>
            {card && card.estimated_price !== null ? (
              <>
                <dl className="figures">
                  <div>
                    <dt>추정 시세</dt>
                    <dd>{formatKRW(card.estimated_price)}</dd>
                  </div>
                  <div>
                    <dt>전세가율 (보증금 ÷ 시세)</dt>
                    <dd>{card.jeonse_ratio !== null ? formatPercent(card.jeonse_ratio) : '계산 못 함'}</dd>
                  </div>
                  <div className="is-key">
                    <dt>(선순위 + 보증금) ÷ 시세</dt>
                    <dd>{card.senior_burden_ratio !== null ? formatPercent(card.senior_burden_ratio) : '계산 못 함'}</dd>
                  </div>
                </dl>
                {card.confidence_label && <p className="tag tag--caution side-tag">{card.confidence_label}</p>}
                <p className="side-note">
                  {card.method_label ?? '시세 산정'}
                  {card.sample_count ? `, 거래 ${card.sample_count}건` : ''}
                  {card.confidence ? `, 신뢰도 ${card.confidence}` : ''}
                  {card.trade_period ? ` (${formatDate(card.trade_period.from)}–${formatDate(card.trade_period.to)})` : ''}
                </p>
                <p className="side-note">70% 이상 주의, 80% 초과 위험</p>
              </>
            ) : (
              <p className="side-note">{priceItem ? partReason(priceItem) : '시세를 구하지 못했어요.'}</p>
            )}
            {priceItem?.data_source === 'stale_cache' && (
              <p className="field__warn">
                공공 API가 응답하지 않아
                {priceItem.data_saved_at ? ` ${formatDateTime(priceItem.data_saved_at)}에` : ''} 저장해 둔 거래 자료로
                계산했어요.
              </p>
            )}
          </section>

          <section className="side-block">
            <h2>선순위 권리</h2>
            {reg ? (
              <>
                <dl className="figures">
                  <div className="is-key">
                    <dt>선순위 금액 합계</dt>
                    <dd>{reg.senior_amount_total !== null ? formatKRW(reg.senior_amount_total) : '모름'}</dd>
                  </div>
                  {card?.senior_amount_used !== null && card?.senior_amount_used !== undefined && (
                    <div>
                      <dt>계산에 쓴 금액</dt>
                      <dd>{formatKRW(card.senior_amount_used)}</dd>
                    </div>
                  )}
                </dl>
                <p className="side-note">{reg.summary_label}</p>
                {reg.senior_amount_missing_count > 0 && (
                  <p className="field__warn">금액을 읽지 못한 등기 {reg.senior_amount_missing_count}건이 있어요.</p>
                )}
                <p className="side-note">근저당은 채권최고액 기준이에요.</p>
              </>
            ) : (
              <p className="side-note">
                {input.registry_uploaded ? '등기부를 읽지 못했어요.' : '등기부를 올리지 않았어요.'}
              </p>
            )}
          </section>

          <section className="side-block">
            <h2>분석에 쓴 자료</h2>
            <ul className="parts">
              {r.data_status.items.map((i) => (
                <li key={i.part} className={`parts__item is-${i.status}`}>
                  <span className="parts__name">{PART_LABEL[i.part]}</span>
                  <span className="parts__state">{statusLabel(i)}</span>
                </li>
              ))}
            </ul>
          </section>

          <Link to="/" className="btn btn--quiet btn--small">
            다른 서류 분석하기
          </Link>
        </aside>
      </div>
    </article>
  )
}

function statusLabel(i: DataStatusItem): string {
  if (i.status === 'ok') return '읽음'
  if (i.status === 'not_provided') return '안 올림'
  return i.reason_code ? (REASON_LABEL[i.reason_code] ?? '실패') : '실패'
}

function partReason(i: DataStatusItem): string {
  if (i.reason) return i.reason
  if (i.status === 'not_provided') {
    if (i.part === 'registry') return '등기부를 올리지 않았어요.'
    if (i.part === 'special_terms') return '계약서를 올리지 않았어요.'
    return '시세를 계산하지 않았어요.'
  }
  return statusLabel(i)
}

function SpecialTermsSection({ terms, contractPages }: { terms: SpecialTerms | null; contractPages: number }) {
  return (
    <section className="report__section" aria-labelledby="terms">
      <h2 id="terms">계약서 특약</h2>
      {!terms ? (
        <p className="empty">
          {contractPages > 0 ? '계약서에서 특약을 확인하지 못했어요.' : '계약서를 올리지 않아 특약은 보지 않았어요.'}
        </p>
      ) : terms.extraction_status === 'failed' ? (
        <div className="notice notice--caution">
          <h3>특약 칸을 읽지 못했어요</h3>
          <p>특약이 없다는 뜻이 아니에요. 계약서 원본의 특약사항 칸을 직접 확인하거나, 더 선명한 사진으로 다시 올려 주세요.</p>
        </div>
      ) : (
        <TermsBody terms={terms} />
      )}
    </section>
  )
}

function TermsBody({ terms }: { terms: SpecialTerms }) {
  const base = terms.base_terms ?? []
  const custom = terms.custom_terms ?? []
  const st = terms.section_status
  const hasStructured = base.length > 0 || custom.length > 0 || terms.custom_terms_text !== undefined

  return (
    <div className="terms">
      <p className="section-lede">
        {terms.page ? `계약서 ${terms.page}쪽부터 읽었어요. ` : ''}
        {terms.masked ? '이름·주민등록번호·연락처·계좌는 가렸어요.' : ''}
        {terms.form === 'standard_2023' ? ' 2023년 개정 표준계약서 양식이에요.' : ''}
      </p>

      {hasStructured ? (
        <>
          <div className="terms__block">
            <h3>기본특약 ①-⑥ (양식에 인쇄된 문구)</h3>
            {st.base_terms === 'failed' ? (
              <p className="field__warn">기본특약 칸을 읽지 못했어요.</p>
            ) : base.length === 0 ? (
              <p className="side-note">기본특약이 없는 양식이에요.</p>
            ) : (
              <ol className="terms__list">
                {base.map((t) => (
                  <li key={String(t.no)}>
                    <p className="doc-text">{t.text}</p>
                    {t.choice_status === 'selected' && t.choice && <span className="tag tag--safe">선택: {t.choice}</span>}
                    {t.choice_status === 'none_selected' && <span className="tag tag--caution">선택한 칸 없음</span>}
                    {t.choice_status === 'unreadable' && <span className="tag tag--caution">선택 여부를 읽지 못함</span>}
                    {t.note && <p className="side-note">{t.note}</p>}
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div className="terms__block">
            <h3>※ 기타 (당사자가 직접 쓴 특약)</h3>
            {st.custom_terms === 'failed' ? (
              <p className="field__warn">직접 쓴 특약 칸을 읽지 못했어요. 특약이 없다는 뜻은 아니에요.</p>
            ) : st.custom_terms === 'empty' || custom.length === 0 ? (
              <p className="side-note">직접 쓴 특약이 없어요.</p>
            ) : (
              <ol className="terms__list">
                {custom.map((t) => (
                  <li key={String(t.no)}>
                    <p className="doc-text">{t.text}</p>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </>
      ) : (
        terms.section_text && <p className="doc-text terms__raw">{terms.section_text}</p>
      )}

      {terms.warnings && terms.warnings.filter((w) => w !== 'NO_CUSTOM_TERMS').length > 0 && (
        <ul className="notes">
          {terms.warnings
            .filter((w) => w !== 'NO_CUSTOM_TERMS')
            .map((w) => (
              <li key={w}>{TERMS_WARNING_LABEL[w] ?? w}</li>
            ))}
        </ul>
      )}
    </div>
  )
}
