import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: Vite serves the frontend on 5173 and proxies /api (+ SSE) to the
// FastAPI backend on 8000. In production the built dist is served by FastAPI
// itself, so no proxy is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})