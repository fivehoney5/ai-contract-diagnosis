import { useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'

export function Layout() {
  const { pathname } = useLocation()
  // 화면이 바뀌면 맨 위부터 보이게 한다 (업로드 화면에서 내려간 스크롤이 리포트에 남지 않게)
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        본문으로 건너뛰기
      </a>
      <header className="topbar">
        <div className="topbar__inner">
          <NavLink to="/" className="brand">
            <svg viewBox="0 0 32 32" aria-hidden="true">
              <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="3" />
              <circle cx="16" cy="16" r="9.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
              <rect x="11" y="14.5" width="10" height="3" rx="1" fill="currentColor" />
            </svg>
            <span>
              전세 계약 리스크 분석 <small>가칭</small>
            </span>
          </NavLink>
          <nav aria-label="주 메뉴">
            <NavLink to="/" end>
              새 분석
            </NavLink>
            <NavLink to="/history">분석 이력</NavLink>
          </nav>
        </div>
      </header>
      <main id="main" className="page">
        <Outlet />
      </main>
      <footer className="footer">
        <p>
          참고용 분석이며 법률 자문이 아니에요. 위험 판정을 받았다면 전세피해지원센터의 안전계약 컨설팅을 받아
          보세요.
        </p>
        <p className="footer__note">시연용 화면입니다. 실제 계약서·등기부 대신 가상 자료로 시험해 주세요.</p>
      </footer>
    </div>
  )
}
