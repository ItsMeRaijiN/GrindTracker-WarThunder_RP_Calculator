import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import contract from '../../backend/tests/fixtures/calculator-contract.json'
import type { CalcPayload } from './types'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_DATA_MODE', 'static')
  vi.stubEnv('BASE_URL', '/GrindTracker-WarThunder_RP_Calculator/')
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(contract.catalog))))
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('standalone Pages data access', () => {
  it('uses one bundled catalog for nations, trees and calculations without calling an API', async () => {
    const { api, AUTH_ENABLED } = await import('./api')
    expect(AUTH_ENABLED).toBe(false)
    await Promise.all([api.nations(), api.classes(), api.tree('usa', 'army')])
    expect(await api.estimate(contract.cases[0].payload as CalcPayload)).toEqual(contract.cases[0].expected)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith('/GrindTracker-WarThunder_RP_Calculator/data/catalog.json', expect.objectContaining({
      credentials: 'omit',
    }))
  })

  it('preserves cancellation without making a network request', async () => {
    const { api } = await import('./api')
    const controller = new AbortController()
    controller.abort()
    await expect(api.estimate({ vehicle_id: 1 }, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('can retry after a failed catalog request', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('unavailable', { status: 503 }))
    const { api } = await import('./api')
    await expect(api.nations()).rejects.toThrow('Could not load')
    expect(await api.nations()).toEqual(contract.catalog.nations)
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('rejects an incompatible catalog instead of presenting an empty tree', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ ...contract.catalog, schema_version: 2 })))
    const { api } = await import('./api')
    await expect(api.nations()).rejects.toThrow('incomplete')
  })

  it('returns an empty tree for a nation without a selected vehicle class', async () => {
    const { api } = await import('./api')
    const result = await api.tree('usa', 'helicopter')
    expect(result.nodes).toEqual([])
    expect(result.edges).toEqual([])
    expect(result.meta?.vehicle_count).toBe(0)
  })
})
