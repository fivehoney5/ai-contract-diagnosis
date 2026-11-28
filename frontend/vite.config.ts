import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// /api 요청은 개발 서버가 FastAPI(backend/, 기본 8000번)로 넘긴다. 다른 주소면 VITE_API_PROXY로 바꾼다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
