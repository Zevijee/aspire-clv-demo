import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider } from 'antd'
import { BrowserRouter } from 'react-router-dom'
import 'antd/dist/reset.css'
import './index.css'
import App from './app/App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      theme={{
        token: {
          borderRadius: 6,
          colorBgBase: 'var(--color-canvas)',
          colorBgContainer: 'var(--color-surface)',
          colorBgElevated: 'var(--color-surface)',
          colorBorder: 'var(--color-border)',
          colorFillAlter: 'var(--color-surface-subtle)',
          colorInfo: 'var(--color-info)',
          colorPrimary: 'var(--color-primary)',
          colorPrimaryBg: 'var(--color-primary-subtle)',
          colorSplit: 'var(--color-border)',
          colorText: 'var(--color-text)',
          colorTextPlaceholder: 'var(--color-text-subtle)',
          colorTextSecondary: 'var(--color-text-muted)',
          controlItemBgActive: 'var(--color-primary-subtle)',
          controlOutline: 'var(--color-primary-subtle)',
          fontFamily:
            'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </StrictMode>,
)
