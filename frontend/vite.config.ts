import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiProxyTarget = process.env.API_PROXY_TARGET
const usePolling = /^(1|true)$/i.test(process.env.WATCH_POLLING ?? '')

export default defineConfig({
  plugins: [react()],
  server: {
    // Container clients use one origin. Local development keeps its current
    // direct-to-localhost API behavior when this variable is absent.
    proxy: apiProxyTarget
      ? { '/api': { target: apiProxyTarget, changeOrigin: true } }
      : undefined,
    watch: usePolling ? { usePolling: true, interval: 500 } : undefined,
  },
})
