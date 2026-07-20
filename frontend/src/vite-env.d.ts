interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  readonly VITE_AUTH_ENABLED?: 'true' | 'false'
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
