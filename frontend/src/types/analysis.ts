// 서비스 서버(backend/)가 돌려주는 형식. docs/analysis-result.md를 그대로 옮겼다.
// 필드 이름은 백엔드와 맞추기 위해 snake_case를 유지한다.

export type Grade = '안전' | '주의' | '위험' | '판단보류'
export type FlagLevel = '안전' | '주의' | '위험' | '확인필요'
export type HousingType = '아파트' | '오피스텔' | '연립다세대'

export type PartName = 'price' | 'registry' | 'special_terms'
export type PartStatus = 'ok' | 'failed' | 'not_provided'

export interface DataStatusItem {
  part: PartName
  status: PartStatus
  reason_code: string | null
  reason: string | null
  /** price 항목만 */
  data_source?: 'api' | 'cache' | 'stale_cache' | null
  data_saved_at?: string | null
}

export interface PropertyInfo {
  address_key: string | null
  address_display: string | null
  housing_type: HousingType | null
  exclusive_area_m2: number | null
  build_year: number | null
}

export interface PriceCard {
  deposit: number
  senior_amount_used: number | null
  estimated_price: number | null
  sample_count: number | null
  method: string | null
  method_label: string | null
  base_date: string | null
  trade_period: { from: string; to: string } | null
  confidence: '높음' | '중간' | '낮음' | null
  jeonse_ratio: number | null
  senior_burden_ratio: number | null
  other_tenant_deposits: number | null
  confidence_label: string | null
}

export interface RegistrySummary {
  senior_amount_total: number | null
  senior_amount_complete?: boolean
  senior_counts: {
    mortgage: number
    hypothec: number
    jeonse_right: number
    lease_right: number
  }
  senior_amount_missing_count: number
  summary_label: string
}

export interface Flag {
  code: string
  level: FlagLevel
  value: number | null
  threshold: number | null
  source: string
}

export type SectionStatus = 'read' | 'empty' | 'failed'
export type ChoiceStatus = 'selected' | 'none_selected' | 'unreadable' | 'not_applicable'

export interface BaseTerm {
  no: number | string
  text: string
  note?: string | null
  choice?: string | null
  choice_status?: ChoiceStatus
}

export interface CustomTerm {
  no: number | string
  text: string
}

export interface SpecialTerms {
  extraction_status: 'ok' | 'failed'
  masked: boolean
  external_send_allowed: boolean
  page: number | null
  section_text: string | null
  section_status: { base_terms: SectionStatus; custom_terms: SectionStatus }
  form?: 'standard_2023' | 'unknown'
  base_terms?: BaseTerm[]
  custom_terms?: CustomTerm[]
  custom_terms_text?: string | null
  warnings?: string[]
}

export interface AnalysisResult {
  analysis_id: string
  analyzed_at: string
  grade: Grade
  data_status: { overall: 'complete' | 'incomplete'; items: DataStatusItem[] }
  property: PropertyInfo | null
  price_card: PriceCard | null
  registry_summary: RegistrySummary | null
  flags: Flag[]
  special_terms: SpecialTerms | null
}

export interface InputSummary {
  address: string
  property_type: HousingType
  deposit: number
  area_m2: number | null
  dong_nm: string | null
  ho_nm: string | null
  registry_uploaded: boolean
  registry_pages: number
  contract_pages: number
}

/** POST /api/analyses, GET /api/analyses/{id} 응답 */
export interface AnalysisRecord {
  analysis_id: string
  created_at: string
  input: InputSummary
  result: AnalysisResult
  notes: string[]
}

/** GET /api/analyses 목록 한 줄 */
export interface AnalysisListItem {
  analysis_id: string
  created_at: string
  grade: Grade | null
  address: string | null
}

export interface AnalysisRequest {
  address: string
  property_type: HousingType
  deposit: number
  area_m2?: number
  dong_nm?: string
  ho_nm?: string
  registry_files: File[]
  contract_files: File[]
}
