import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

function installAbortableFetch() {
  vi.stubGlobal('window', {
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
  })
  vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => (
    new Promise<Response>((_resolve, reject) => {
      const signal = init?.signal
      if (signal?.aborted) {
        reject(signal.reason)
        return
      }
      signal?.addEventListener('abort', () => reject(signal.reason), { once: true })
    })
  )))
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('API request cancellation', () => {
  it('preserves caller cancellation instead of reporting a timeout', async () => {
    installAbortableFetch()
    const controller = new AbortController()
    const pending = api.estimate({ vehicle_id: 1 }, controller.signal)

    controller.abort()

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('does not let the timeout replace a caller cancellation at the deadline', async () => {
    vi.useFakeTimers()
    installAbortableFetch()
    const controller = new AbortController()
    const pending = api.estimate({ vehicle_id: 1 }, controller.signal)
    const assertion = expect(pending).rejects.toMatchObject({ name: 'AbortError' })

    await vi.advanceTimersByTimeAsync(19_999)
    controller.abort()
    await vi.advanceTimersByTimeAsync(1)

    await assertion
  })

  it('keeps the request timeout when a caller does not cancel', async () => {
    vi.useFakeTimers()
    installAbortableFetch()
    const pending = api.estimate({ vehicle_id: 1 })
    const assertion = expect(pending).rejects.toEqual(new ApiError('The API request timed out.', 0))

    await vi.advanceTimersByTimeAsync(20_000)

    await assertion
  })
})
