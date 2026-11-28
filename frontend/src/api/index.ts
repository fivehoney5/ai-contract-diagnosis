// 화면에서 서버를 부르는 입구. backend/app/api/routes/analyses.py의 세 API만 쓴다.
// 개발 중에는 vite.config.ts의 프록시가 /api를 FastAPI로 넘긴다.
import type { AnalysisListItem, AnalysisRecord, AnalysisRequest } from '../types/analysis'

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${BASE}/api${path}`, init)
  } catch {
    throw new ApiError(0, '서버에 연결하지 못했어요. 서비스 서버(backend)가 켜져 있는지 확인해 주세요.')
  }
  if (!res.ok) {
    throw new ApiError(res.status, await errorMessage(res))
  }
  return (await res.json()) as T
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    // FastAPI 입력 검증 오류(422)는 목록으로 온다
    if (Array.isArray(detail) && detail.length > 0) {
      return detail.map((d: { msg?: string }) => d.msg ?? '').filter(Boolean).join(' / ')
    }
  } catch {
    // 본문이 JSON이 아님
  }
  if (res.status === 502 || res.status === 504) {
    return '서버에 연결하지 못했어요. 서비스 서버(backend)가 켜져 있는지 확인해 주세요.'
  }
  return `요청을 처리하지 못했어요 (${res.status})`
}

export function createAnalysis(req: AnalysisRequest, signal?: AbortSignal): Promise<AnalysisRecord> {
  const form = new FormData()
  form.append('address', req.address)
  form.append('property_type', req.property_type)
  form.append('deposit', String(req.deposit))
  if (req.area_m2 !== undefined) form.append('area_m2', String(req.area_m2))
  if (req.dong_nm) form.append('dong_nm', req.dong_nm)
  if (req.ho_nm) form.append('ho_nm', req.ho_nm)
  req.registry_files.forEach((f) => form.append('registry_file', f))
  req.contract_files.forEach((f) => form.append('contract_files', f))
  return request<AnalysisRecord>('/analyses', { method: 'POST', body: form, signal })
}

export function getAnalysis(id: string): Promise<AnalysisRecord> {
  return request<AnalysisRecord>(`/analyses/${encodeURIComponent(id)}`)
}

export function listAnalyses(limit = 50): Promise<AnalysisListItem[]> {
  return request<AnalysisListItem[]>(`/analyses?limit=${limit}`)
}
