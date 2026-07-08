import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Point at a local backend during dev (set VITE_API_TARGET=http://localhost:8000),
  // falls back to the hosted Render instance otherwise.
  const target = env.VITE_API_TARGET || 'https://fpl-optimizer-api-irgc.onrender.com'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 3000,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          secure: true,
        },
      },
    },
  }
})
