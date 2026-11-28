import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { createAnalysis } from '../api'
import { DropZone } from '../components/DropZone'
import { ProgressSteps } from '../components/ProgressSteps'
import { ACCEPTED_TYPES } from '../utils/files'
import { formatKRW } from '../utils/format'
import type { HousingType } from '../types/analysis'

// backend/app/services/analysis_engine.py의 실제 처리 순서
const STEPS = [
  '주소를 찾고 있어요',
  '등기부에서 선순위 권리를 읽고 있어요',
  '실거래가로 시세를 계산하고 있어요',
  '계약서 특약 칸을 읽고 개인정보를 가리고 있어요',
  '위험 등급을 정하고 있어요',
]

const HOUSING_TYPES: HousingType[] = ['연립다세대', '오피스텔', '아파트']

function checkFiles(label: string, files: File[]): string | null {
  const heic = files.find((f) => /\.hei[cf]$/i.test(f.name) || f.type === 'image/heic' || f.type === 'image/heif')
  if (heic) return `${label}: 아이폰 HEIC 사진은 읽지 못해요. JPG로 바꿔서 올려 주세요.`
  const bad = files.find((f) => !ACCEPTED_TYPES.includes(f.type))
  if (bad) return `${label}: ${bad.name}은(는) 받지 않는 형식이에요. PDF, JPG, PNG, WEBP만 올려 주세요.`
  return null
}

export function UploadPage() {
  const navigate = useNavigate()
  const [registry, setRegistry] = useState<File[]>([])
  const [contract, setContract] = useState<File[]>([])
  const [address, setAddress] = useState('')
  const [housingType, setHousingType] = useState<HousingType>('연립다세대')
  const [depositMan, setDepositMan] = useState('')
  const [area, setArea] = useState('')
  const [dong, setDong] = useState('')
  const [ho, setHo] = useState('')
  const [sending, setSending] = useState(false)
  const [finished, setFinished] = useState(false)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  const depositWon = Number(depositMan) * 10_000
  const depositValid = depositMan.trim() !== '' && Number.isFinite(depositWon) && depositWon > 0

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!address.trim()) return setError('집 주소를 입력해 주세요.')
    if (!depositValid) return setError('보증금을 만 원 단위 숫자로 입력해 주세요. 예: 2억 원이면 20000')
    const areaNum = area.trim() === '' ? undefined : Number(area)
    if (areaNum !== undefined && !(areaNum > 0)) return setError('전용면적은 0보다 큰 숫자로 입력해 주세요.')
    const fileError = checkFiles('등기부등본', registry) ?? checkFiles('임대차계약서', contract)
    if (fileError) return setError(fileError)

    setError('')
    setFinished(false)
    setSending(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const record = await createAnalysis(
        {
          address: address.trim(),
          property_type: housingType,
          deposit: Math.round(depositWon),
          area_m2: areaNum,
          dong_nm: dong.trim() || undefined,
          ho_nm: ho.trim() || undefined,
          registry_files: registry,
          contract_files: contract,
        },
        controller.signal,
      )
      setFinished(true)
      window.setTimeout(() => navigate(`/analyses/${record.analysis_id}`, { state: record }), 400)
    } catch (err) {
      if (controller.signal.aborted) return
      setSending(false)
      setError(err instanceof Error ? err.message : '분석하지 못했어요. 잠시 뒤 다시 시도해 주세요.')
    }
  }

  if (sending) {
    return (
      <div className="narrow">
        <ProgressSteps
          title="서류를 분석하고 있어요"
          steps={STEPS}
          finished={finished}
          note="사진은 글자 인식 때문에 시간이 더 걸려요. 처음 실행할 때는 인식 모델을 내려받느라 1분 넘게 걸릴 수 있어요."
        />
      </div>
    )
  }

  return (
    <div className="upload">
      <section className="upload__intro">
        <h1>계약서에 도장 찍기 전에, 서류부터 같이 읽어요</h1>
        <p className="lede">
          등기부등본과 계약서를 올리면 선순위 권리, 시세 대비 보증금 비율, 특약을 살펴 위험 신호와 등급을 알려
          드려요.
        </p>
        <ul className="upload__facts">
          <li>원본 파일은 저장하지 않고, 분석 결과만 남겨요.</li>
          <li>계약서 특약은 이름·주민등록번호·연락처·계좌를 가린 뒤에 읽어요.</li>
          <li>시세는 국토교통부 실거래가로 자동으로 계산해요.</li>
        </ul>
      </section>

      <form className="upload__form" onSubmit={submit} noValidate>
        <h2 className="visually-hidden">서류 올리기</h2>
        <DropZone
          label="등기부등본"
          description="PDF, 스캔본 또는 사진. 여러 장이면 쪽 순서대로 함께 골라 주세요"
          files={registry}
          onChange={setRegistry}
        />
        <DropZone
          label="임대차계약서"
          description="PDF 또는 사진. 특약사항 칸이 보이게 찍어 주세요"
          files={contract}
          onChange={setContract}
        />
        <p className="field__help">
          등기부가 없으면 선순위 권리를 확인하지 못해 등급이 「판단보류」로 나와요. 계약서가 없으면 특약은 보지
          않아요.
        </p>

        <div className="field">
          <label htmlFor="address">집 주소</label>
          <input
            id="address"
            type="text"
            placeholder="예: 서울 강서구 화곡동 123-4 201호"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            autoComplete="street-address"
            required
          />
          <p className="field__help">동·호까지 쓰면 등기부의 호수와 같은 집인지 비교해요.</p>
        </div>

        <div className="grid-2">
          <div className="field">
            <label htmlFor="type">주택 유형</label>
            <select id="type" value={housingType} onChange={(e) => setHousingType(e.target.value as HousingType)}>
              {HOUSING_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t === '연립다세대' ? '연립·다세대 (빌라)' : t}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="deposit">보증금 (만 원)</label>
            <input
              id="deposit"
              type="number"
              inputMode="numeric"
              min={1}
              placeholder="예: 20000"
              value={depositMan}
              onChange={(e) => setDepositMan(e.target.value)}
              required
            />
            <p className="field__help">{depositValid ? formatKRW(Math.round(depositWon)) : '2억 원이면 20000'}</p>
          </div>

          <div className="field">
            <label htmlFor="area">
              전용면적 (㎡) <span className="field__badge">선택</span>
            </label>
            <input
              id="area"
              type="number"
              inputMode="decimal"
              min={0}
              step="0.01"
              placeholder="예: 29.8"
              value={area}
              onChange={(e) => setArea(e.target.value)}
            />
            <p className="field__help">비워 두면 등기부의 전용면적을 써요.</p>
          </div>

          <div className="field">
            <label htmlFor="dong">
              동·호 <span className="field__badge">선택</span>
            </label>
            <div className="field__pair">
              <input
                id="dong"
                type="text"
                placeholder="동"
                aria-label="동"
                value={dong}
                onChange={(e) => setDong(e.target.value)}
              />
              <input
                id="ho"
                type="text"
                placeholder="호"
                aria-label="호"
                value={ho}
                onChange={(e) => setHo(e.target.value)}
              />
            </div>
            <p className="field__help">주소에 동·호를 쓰지 않았을 때만 채워 주세요.</p>
          </div>
        </div>

        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}

        <div className="upload__actions">
          <button type="submit" className="btn btn--primary">
            서류 분석하기
          </button>
        </div>
      </form>
    </div>
  )
}
