import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="narrow empty">
      <h1>찾는 화면이 없어요</h1>
      <p>주소가 바뀌었거나 지워진 분석이에요. 분석 이력에서 다시 찾아보세요.</p>
      <Link to="/history" className="btn btn--primary">
        분석 이력 보기
      </Link>
    </div>
  )
}
