import type {
  CalcPayload,
  CascadeResult,
  EstimateResult,
  Nation,
  TreeResponse,
  User,
  VehicleClass,
} from './types'

const ROOT = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')
const API = ROOT.endsWith('/api') ? ROOT : `${ROOT}/api`
export const AUTH_ENABLED = import.meta.env.VITE_AUTH_ENABLED !== 'false'
let csrfToken: string | null = null

type AuthResponse = { csrf_token: string; user: User }
type RemoteProgress = { vehicle_id: number; rp_earned: number; done: boolean }
type RemoteProgressPayload = Record<number, { rp_earned: number; done: boolean }>

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly rejectedVehicleIds: number[] = [],
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function setCsrfToken(token: string | null) {
  csrfToken = token
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  const method = (init.method || 'GET').toUpperCase()
  if (csrfToken && !['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('X-CSRF-Token', csrfToken)
  const controller = new AbortController()
  let timedOut = false
  const timeout = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, 20_000)
  const externalSignal = init.signal
  const abortFromExternalSignal = () => {
    window.clearTimeout(timeout)
    controller.abort(externalSignal?.reason)
  }
  if (externalSignal?.aborted) abortFromExternalSignal()
  else externalSignal?.addEventListener('abort', abortFromExternalSignal, { once: true })
  let response: Response
  try {
    response = await fetch(`${API}${path}`, {
      ...init,
      headers,
      credentials: AUTH_ENABLED ? 'include' : 'omit',
      signal: controller.signal,
    })
  } catch (error) {
    if (timedOut) throw new ApiError('The API request timed out.', 0)
    throw error
  } finally {
    window.clearTimeout(timeout)
    externalSignal?.removeEventListener('abort', abortFromExternalSignal)
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let rejectedVehicleIds: number[] = []
    try {
      const body = (await response.json()) as {
        error?: string
        detail?: string | { message?: string; vehicle_ids?: unknown }
        details?: Array<{ field?: string; message?: string }>
      }
      if (body.error) message = body.error
      else if (typeof body.detail === 'string') message = body.detail
      else if (body.detail?.message) message = body.detail.message
      if (body.detail && typeof body.detail === 'object') {
        rejectedVehicleIds = positiveIntegerList(body.detail.vehicle_ids)
      }
      const first = body.details?.[0]
      if (first?.message) message += ` ${first.field ? `${first.field}: ` : ''}${first.message}`
    } catch {}
    throw new ApiError(message, response.status, rejectedVehicleIds)
  }
  return (await response.json()) as T
}

function positiveIntegerList(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  return [...new Set(value.filter(
    (item): item is number => typeof item === 'number' && Number.isSafeInteger(item) && item > 0,
  ))]
}

function queryString(values: Record<string, string | number | boolean | undefined>) {
  const query = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, String(value))
  })
  return query.toString()
}

export const api = {
  nations: () => request<Nation[]>('/nations'),
  classes: () => request<VehicleClass[]>('/classes'),
  tree: (nation: string, vehicleClass: string) =>
    request<TreeResponse>(`/tree?${queryString({ nation, class: vehicleClass })}`),

  estimate: (payload: CalcPayload, signal?: AbortSignal) =>
    request<EstimateResult>('/calc/estimate', { method: 'POST', body: JSON.stringify(payload), signal }),
  cascade: (payload: CalcPayload, signal?: AbortSignal) =>
    request<CascadeResult>('/calc/cascade', { method: 'POST', body: JSON.stringify(payload), signal }),

  register: (email: string, password: string) =>
    request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<AuthResponse>('/auth/me'),
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),

  getProgress: () =>
    request<Array<{ vehicle_id: number; rp_earned: number; done: boolean }>>('/progress'),
  saveProgressBulk: (progress: RemoteProgressPayload) =>
    request<{ items: RemoteProgress[] }>('/progress', {
      method: 'PUT',
      body: JSON.stringify({ progress }),
    }),
}
