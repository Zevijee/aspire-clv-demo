import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiProxyTarget = process.env.API_PROXY_TARGET

// Every API client falls back to http://localhost:8000, which is correct for local
// development and for the container, where the browser reaches the published API
// port directly. On a hosted build that fallback points at the *viewer's* machine,
// so the whole app fails with nothing in the logs to say why. Vercel sets VERCEL=1
// on its own builds, which keeps this check off the local and Docker builds.
if (process.env.VERCEL && !process.env.VITE_API_BASE_URL) {
  throw new Error(
    'Set VITE_API_BASE_URL to the public origin of the reporting API before deploying. '
    + 'Without it the deployed frontend requests http://localhost:8000 from each visitor. '
    + 'See docs/deploying.md.',
  )
}

export default defineConfig({
  plugins: [react()],
  server: {
    // Set API_PROXY_TARGET to serve the app and the API on one origin, which is
    // what a hosted deployment does. Without it the API clients call
    // http://localhost:8000 directly, which is the local default.
    proxy: apiProxyTarget
      ? { '/api': { target: apiProxyTarget, changeOrigin: true } }
      : undefined,
  },
})
