import { Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { HistoryPage } from './pages/HistoryPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ReportPage } from './pages/ReportPage'
import { UploadPage } from './pages/UploadPage'

// 화면은 서버(backend/)에 구현된 API만큼만 만든다:
//   POST /api/analyses → 새 분석,  GET /api/analyses/{id} → 리포트,  GET /api/analyses → 분석 이력
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<UploadPage />} />
        <Route path="analyses/:id" element={<ReportPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
