import { describe, expect, it } from 'vitest'
import {
  applyProgressUpdates,
  isMigrationConfirmed,
  mergeHydratedProgress,
  mergeGuestProgress,
  reconcileSynchronizedProgress,
  removeProgressEntries,
  type ProgressMap,
} from './useProgress'

describe('guest progress migration', () => {
  it('merges into the account without mutating either source and marks rows pending', () => {
    const account: ProgressMap = { 1: { rp: 100, done: false } }
    const guest: ProgressMap = {
      1: { rp: 250, done: false },
      2: { rp: 500, done: true },
    }

    const merged = mergeGuestProgress(account, guest)

    expect(merged).toEqual({
      1: { rp: 250, done: false, dirty: true },
      2: { rp: 500, done: true, dirty: true },
    })
    expect(account).toEqual({ 1: { rp: 100, done: false } })
    expect(guest).toEqual({ 1: { rp: 250, done: false }, 2: { rp: 500, done: true } })
  })

  it('keeps the migration backup until every row is confirmed by the API', () => {
    const pending: ProgressMap = { 1: { rp: 100, done: false, dirty: true } }
    expect(isMigrationConfirmed(pending, pending)).toBe(false)
    expect(isMigrationConfirmed({ 1: { rp: 100, done: false } }, pending)).toBe(true)
    expect(isMigrationConfirmed({}, pending)).toBe(false)
  })
})

describe('progress synchronization reconciliation', () => {
  it('applies a whole-rank unlock as one immutable progress update', () => {
    const current: ProgressMap = { 1: { rp: 100, done: false } }

    const updated = applyProgressUpdates(current, [
      { vehicleId: 1, rp: 2_900, done: true, total: 2_900 },
      { vehicleId: 2, rp: 4_000, done: true, total: 4_000 },
      { vehicleId: 3, rp: 0, done: true, total: 0 },
    ], true)

    expect(updated).toEqual({
      1: { rp: 2_900, done: true, dirty: true },
      2: { rp: 4_000, done: true, dirty: true },
    })
    expect(current).toEqual({ 1: { rp: 100, done: false } })
  })

  it('removes only server-rejected rows so valid dirty progress can retry', () => {
    const current: ProgressMap = {
      1: { rp: 100, done: false, dirty: true },
      2: { rp: 200, done: false, dirty: true },
    }

    expect(removeProgressEntries(current, [1, 999])).toEqual({
      2: { rp: 200, done: false, dirty: true },
    })
  })

  it('merges a guest migration only after server hydration without reducing server progress', () => {
    const pending: ProgressMap = { 1: { rp: 100, done: false, dirty: true } }

    expect(mergeHydratedProgress({}, pending, [
      { vehicle_id: 1, rp_earned: 5_000, done: false },
    ])).toEqual({ 1: { rp: 5_000, done: false } })
    expect(mergeHydratedProgress({}, pending, [
      { vehicle_id: 1, rp_earned: 50, done: false },
    ])).toEqual({ 1: { rp: 100, done: false, dirty: true } })
  })

  it('recognizes a dirty copy left by the previous migration flow', () => {
    const pending: ProgressMap = { 1: { rp: 100, done: false, dirty: true } }

    expect(mergeHydratedProgress(pending, pending, [
      { vehicle_id: 1, rp_earned: 5_000, done: false },
    ])).toEqual({ 1: { rp: 5_000, done: false } })
  })

  it('does not let an older response clear a newer local edit', () => {
    const sent: ProgressMap = { 1: { rp: 100, done: false, dirty: true } }
    const current: ProgressMap = { 1: { rp: 200, done: false, dirty: true } }

    expect(reconcileSynchronizedProgress(current, sent, [
      { vehicle_id: 1, rp_earned: 100, done: false },
    ])).toEqual(current)
  })

  it('clears dirty only when the confirmed row still matches the sent value', () => {
    const sent: ProgressMap = { 1: { rp: 100, done: false, dirty: true } }

    expect(reconcileSynchronizedProgress(sent, sent, [
      { vehicle_id: 1, rp_earned: 100, done: false },
    ])).toEqual({ 1: { rp: 100, done: false } })
  })
})
