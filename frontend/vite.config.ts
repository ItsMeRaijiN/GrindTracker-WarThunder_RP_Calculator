import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const configuredApiBase = (env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
  const apiBase = configuredApiBase || 'http://127.0.0.1:8000'
  const isPages = process.env.GITHUB_PAGES === 'true'
  const repo = process.env.GITHUB_REPOSITORY?.split('/')[1] ?? ''
  const base = isPages && mode === 'production' ? `/${repo}/` : '/'
  const authEnabled = env.VITE_AUTH_ENABLED !== 'false'
  if (isPages && mode === 'production') {
    if (!configuredApiBase) throw new Error('GitHub Pages builds require the API_BASE_URL repository variable.')
    const parsedApiBase = new URL(configuredApiBase)
    if (parsedApiBase.protocol !== 'https:') throw new Error('GitHub Pages requires an HTTPS API_BASE_URL.')
    if (authEnabled) throw new Error('GitHub Pages builds must set VITE_AUTH_ENABLED=false. Host the web app same-site with the API to enable account sync.')
  }

  const connectSources = new Set(["'self'"])
  if (configuredApiBase) connectSources.add(new URL(configuredApiBase).origin)
  if (command === 'serve') {
    connectSources.add('http://localhost:*')
    connectSources.add('http://127.0.0.1:*')
    connectSources.add('ws://localhost:*')
    connectSources.add('ws://127.0.0.1:*')
  }
  const contentSecurityPolicy = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    `connect-src ${[...connectSources].join(' ')}`,
    "img-src 'self' data:",
    "font-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "worker-src 'none'",
  ].join('; ')

  return {
    base,
    plugins: [
      react(),
      {
        name: 'grindtracker-content-security-policy',
        transformIndexHtml: {
          order: 'pre',
          handler: () => [{
            tag: 'meta',
            attrs: { 'http-equiv': 'Content-Security-Policy', content: contentSecurityPolicy },
            injectTo: 'head-prepend',
          }],
        },
      },
    ],
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target: apiBase, changeOrigin: true } }
    },
    preview: {
      port: 5173,
      proxy: { '/api': { target: apiBase, changeOrigin: true } }
    }
  }
})
