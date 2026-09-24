import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Every API client falls back to http://localhost:8000, which is correct for a
// bare local run. On a hosted build that fallback points at the *viewer's*
// machine, so the whole app fails with nothing in the logs to say why. Vercel
// sets VERCEL=1 on its own builds, which keeps this check off local builds.
if (process.env.VERCEL && !process.env.VITE_API_BASE_URL) {
  throw new Error(
    'Set VITE_API_BASE_URL to the public origin of the reporting API before deploying. '
    + 'Without it the deployed frontend requests http://localhost:8000 from each visitor. '
    + 'See docs/deploying.md.',
  )
}

export default defineConfig(({ command }) => ({
  plugins: [react()],
  // The dev server serves the app and proxies /api, so development runs on one
  // origin exactly as a deployment does.
  //
  // This is not only tidiness. The session cookie is SameSite=Lax, and a page on
  // 127.0.0.1:5173 calling an API on localhost:8000 counts as a different site,
  // so the browser drops the cookie and every report returns 401 while the login
  // appears to succeed. One origin removes the whole class of problem, and CORS
  // stops mattering locally as well.
  define: command === 'serve' && !process.env.VITE_API_BASE_URL
    ? { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('') }
    : undefined,
  server: {
    proxy: {
      '/api': {
        target: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
