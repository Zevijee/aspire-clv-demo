import { mergeConfig } from 'vite'
import config from './vite.config'

export default mergeConfig(config, {
  define: { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('') },
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    hmr: false,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
