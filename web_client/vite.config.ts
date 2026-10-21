import process from 'node:process'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 开发代理目标：默认指向本机 Go 参考服务，可用 PRIVRELAY_API 覆盖。
// 例如：PRIVRELAY_API=http://192.168.1.10:8787 npm run dev
const apiTarget = process.env.PRIVRELAY_API ?? 'http://127.0.0.1:8787'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // REST 与 WebSocket 一并代理，浏览器侧保持同源，绕开服务端无 CORS 头的限制
      '/api': { target: apiTarget, changeOrigin: true, ws: true },
      '/healthz': { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1600,
  },
})
