// 서버가 보내는 코드값을 화면 문구로 바꾸는 표. 코드 뜻은 docs/risk-rules.md, document/*/README.md 기준.
import type { PartName } from '../types/analysis'

interface FlagText {
  title: string
  /** 신호가 떴을 때 사용자가 할 일 */
  action: string
  /** value가 비율이면 ratio, 건수면 count, 일수면 days */
  unit?: 'ratio' | 'count' | 'days'
}

export const FLAG_TEXT: Record<string, FlagText> = {
  JEONSE_RATIO_HIGH: {
    title: '전세가율이 높아요',
    action: '보증금을 낮추거나, 전세보증보험에 가입할 수 있는지 먼저 확인하세요.',
    unit: 'ratio',
  },
  SENIOR_BURDEN_HIGH: {
    title: '선순위 채권과 보증금 합이 시세에 가까워요',
    action: '집이 경매로 넘어가면 보증금을 다 돌려받지 못할 수 있어요. 근저당 말소나 보증금 조정을 요구하세요.',
    unit: 'ratio',
  },
  NO_BUILDING_TRADES: {
    title: '같은 건물 매매 거래가 없어 시세를 알기 어려워요',
    action: '신축이라면 분양가·감정가가 부풀려졌을 수 있어요. 주변 비슷한 집 시세와 비교해 보세요.',
    unit: 'count',
  },
  PRICE_INFLATION_SUSPECTED: {
    title: '매매가가 부풀려졌을 수 있어요',
    action: '최근 거래가가 주변보다 높아요. 여러 거래와 공시가격을 함께 비교하세요.',
  },
  OWNERSHIP_RESTRICTED: {
    title: '압류·가압류·가처분·경매개시결정이 있어요',
    action: '말소되지 않은 권리 제한 등기가 있어요. 해결되기 전에는 계약을 미루세요.',
    unit: 'count',
  },
  PROVISIONAL_REGISTRATION: {
    title: '가등기가 있어요',
    action: '나중에 소유자가 바뀔 수 있어요. 가등기가 말소되기 전에는 계약을 미루세요.',
    unit: 'count',
  },
  TRUST_REGISTERED: {
    title: '신탁등기가 되어 있어요',
    action: '집주인이 아니라 신탁회사가 소유자예요. 신탁원부를 떼고 신탁회사의 동의서를 받으세요.',
    unit: 'count',
  },
  LEASE_RIGHT_REGISTERED: {
    title: '임차권등기가 있어요',
    action: '이전 세입자가 보증금을 돌려받지 못했다는 신호예요. 계약을 다시 생각해 보세요.',
    unit: 'count',
  },
  JEONSE_RIGHT_EXISTS: {
    title: '전세권이 남아 있어요',
    action: '이전 세입자의 전세권이면 잔금 전에 말소한다는 특약을 넣으세요.',
    unit: 'count',
  },
  SENIOR_AMOUNT_UNREADABLE: {
    title: '선순위 금액을 읽지 못한 등기가 있어요',
    action: '등기부 을구의 채권최고액을 직접 확인해 주세요.',
    unit: 'count',
  },
  LAND_RIGHT_CHECK_NEEDED: {
    title: '대지권·토지 별도등기를 확인해야 해요',
    action: '등기부 표제부의 대지권 표시와 토지 등기부를 확인하세요.',
  },
  STRIKE_WITHOUT_CANCEL_ENTRY: {
    title: '취소선만 있고 말소 등기가 없는 줄이 있어요',
    action: '사진·스캔본에서 읽은 줄이라 살아 있는 등기로 계산했어요. 등기부 원본에서 말소 여부를 확인하세요.',
    unit: 'count',
  },
  REGISTRY_OUTDATED: {
    title: '등기부 발급일이 오래됐어요',
    action: '계약 직전과 잔금 직전에 등기부를 새로 떼어 다시 확인하세요.',
    unit: 'days',
  },
  REGISTRY_ADDRESS_MISMATCH: {
    title: '입력한 주소와 등기부 주소가 달라요',
    action: '다른 집의 등기부일 수 있어요. 지번과 호수가 맞는 등기부를 다시 올려 주세요.',
  },
  HIDDEN_SENIOR_CLAIM_CHECK_NEEDED: {
    title: '다른 세대의 선순위 보증금 확인이 필요해요',
    action: '다가구 등은 다른 세대 보증금이 등기부에 나오지 않아요. 확정일자 부여현황과 전입세대 열람으로 확인하세요.',
  },
  VIOLATION_BUILDING_CHECK_NEEDED: {
    title: '위반건축물 여부를 확인해야 해요',
    action: '공공데이터에는 위반건축물 항목이 없어요. 정부24에서 건축물대장을 열람해 확인하세요.',
  },
  NON_RESIDENTIAL: {
    title: '건축물대장 용도가 주거용이 아니에요',
    action: '근린생활시설 등은 전입신고·보증보험이 어려울 수 있어요. 건축물대장 용도를 확인하세요.',
  },
  UNIT_PURPOSE_CHECK_NEEDED: {
    title: '같은 호수에 용도가 다른 기록이 있어요',
    action: '건축물대장 전유부에서 계약할 호수의 용도를 직접 확인하세요.',
  },
  SPECIAL_TERMS_CHECK_NEEDED: {
    title: '특약 확인이 필요해요',
    action: '계약서에서 특약 칸을 읽지 못했어요. 특약이 없다는 뜻이 아니니 원본의 특약사항 칸을 직접 확인하세요.',
  },
}

export function flagText(code: string): FlagText {
  return FLAG_TEXT[code] ?? { title: code, action: '' }
}

export const PART_LABEL: Record<PartName, string> = {
  price: '시세',
  registry: '등기부',
  special_terms: '특약',
}

export const REASON_LABEL: Record<string, string> = {
  ADDRESS_NOT_FOUND: '주소를 찾지 못함',
  NO_TRADES: '거래 없음',
  API_UNAVAILABLE: '공공 API 사용 불가',
  PARSE_FAILED: '문서를 읽지 못함',
}

export const TERMS_WARNING_LABEL: Record<string, string> = {
  CUSTOM_MARKER_NOT_FOUND: '「※ 기타」 표시를 찾지 못했어요',
  BASE_TERMS_INCOMPLETE: '기본특약 ①-⑥ 중 일부를 읽지 못했어요',
  NO_CUSTOM_TERMS: '직접 쓴 특약이 없어요',
  LOW_OCR_CONFIDENCE: '사진 글자 인식 신뢰도가 낮아요',
  END_MARKER_NOT_FOUND: '특약 칸이 끝나는 곳을 찾지 못했어요',
}
