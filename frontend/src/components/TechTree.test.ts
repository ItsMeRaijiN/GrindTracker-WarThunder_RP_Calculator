import { describe, expect, it } from 'vitest'
import {
  buildRankUnlockOperation,
  canUndoRankUnlock,
  incompleteResearchTargets,
  isResearchTarget,
  isResearchTreeVehicle,
  isReserveVehicle,
  isVehicleComplete,
  rankResetUpdates,
} from '../lib/vehicles'
import type { TreeResponse, Vehicle } from '../types'
import { buildParentMap, collectAncestorIds } from './TechTree'

function vehicle(id: number, overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    id,
    name: `Vehicle ${id}`,
    nation: 'germany',
    class: 'army',
    rank: 1,
    type: 'tree',
    is_reserve: false,
    ...overrides,
  }
}

describe('research tree state', () => {
  it('combines research and folder parents without duplicates', () => {
    const tree = {
      nodes: [vehicle(1), vehicle(2, { folder_of: 1 })],
      edges: [{ parent: 1, child: 2 }],
    } as TreeResponse

    expect(buildParentMap(tree).get(2)).toEqual([1])
  })

  it('collects the selected route and terminates on a malformed cycle', () => {
    const parents = new Map<number, number[]>([
      [1, [2]],
      [2, [1]],
    ])

    expect(collectAncestorIds(1, parents)).toEqual(new Set([1, 2]))
  })

  it('treats a fully researched vehicle as complete even before the done flag is synced', () => {
    expect(isVehicleComplete(vehicle(1, { rp_cost: 10_000 }), { rp: 10_000, done: false })).toBe(true)
    expect(isVehicleComplete(vehicle(1, { rp_cost: 10_000 }), { rp: 9_999, done: false })).toBe(false)
  })

  it('treats reserve vehicles as unlocked without stored progress', () => {
    const reserve = vehicle(1, { is_reserve: true, rp_cost: null })

    expect(isReserveVehicle(reserve)).toBe(true)
    expect(isResearchTarget(reserve)).toBe(false)
    expect(isResearchTreeVehicle(reserve)).toBe(true)
    expect(isVehicleComplete(reserve, { rp: 0, done: false })).toBe(true)
  })

  it('selects only incomplete research targets for a rank-wide unlock', () => {
    const vehicles = [
      vehicle(1, { rp_cost: 2_900 }),
      vehicle(2, { rp_cost: 4_000 }),
      vehicle(3, { rp_cost: null, is_reserve: true }),
      vehicle(4, { rp_cost: 1_000, type: 'premium' }),
    ]
    const progress = new Map([[2, { rp: 4_000, done: true }]])

    expect(incompleteResearchTargets(vehicles, (id) => progress.get(id) || { rp: 0, done: false }))
      .toEqual([vehicles[0]])
  })

  it('can restore the exact progress from before a rank-wide unlock', () => {
    const vehicles = [
      vehicle(1, { rp_cost: 2_900 }),
      vehicle(2, { rp_cost: 4_000 }),
      vehicle(3, { rp_cost: null, is_reserve: true }),
    ]
    const before = new Map([
      [1, { rp: 700, done: false }],
      [2, { rp: 4_000, done: true }],
    ])
    const operation = buildRankUnlockOperation(vehicles, (id) => before.get(id) || { rp: 0, done: false })

    expect(operation.unlock).toEqual([{ vehicle: vehicles[0], rp: 2_900, done: true }])
    expect(operation.undo).toEqual([{ vehicle: vehicles[0], rp: 700, done: false }])
    expect(canUndoRankUnlock(operation, () => ({ rp: 2_900, done: true }))).toBe(true)
    expect(rankResetUpdates(vehicles)).toEqual([
      { vehicle: vehicles[0], rp: 0, done: false },
      { vehicle: vehicles[1], rp: 0, done: false },
    ])
  })
})
