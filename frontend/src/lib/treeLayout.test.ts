import { describe, expect, it } from 'vitest'
import { buildTechTreeLayout, groupVehicles } from './treeLayout'
import type { Vehicle } from '../types'

function vehicle(id: number, name: string, overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    id,
    name,
    nation: 'germany',
    class: 'army',
    rank: 1,
    type: 'tree',
    is_reserve: false,
    tree_column: 0,
    tree_order: id,
    ...overrides,
  }
}

describe('WT-like research tree layout', () => {
  it('keeps every source lane aligned across ranks and preserves special columns', () => {
    const layout = buildTechTreeLayout([
      vehicle(1, 'Line one'),
      vehicle(2, 'Line three', { rank: 2, tree_column: 2 }),
      vehicle(3, 'Premium', { rank: 2, type: 'premium', tree_column: 5 }),
    ], 2)

    expect(layout.columns).toEqual([0, 2, 5])
    expect(layout.researchColumnCount).toBe(2)
    expect(layout.ranks.map((rank) => rank.rank)).toEqual([1, 2])
    expect(layout.ranks[0].lanes.map((lane) => lane.column)).toEqual([0, 2, 5])
    expect(layout.ranks[1].lanes[2].groups[0].root.name).toBe('Premium')
  })

  it('keeps a special folder child attached to its researchable root', () => {
    const layout = buildTechTreeLayout([
      vehicle(1, 'Root'),
      vehicle(2, 'Event variant', { type: 'collector', folder_of: 1 }),
    ], 1)

    expect(layout.ranks[0].lanes[0].groups).toHaveLength(1)
    expect(layout.ranks[0].lanes[0].groups[0].vehicles.map((item) => item.name)).toEqual([
      'Root',
      'Event variant',
    ])
  })

  it('turns a root and all nested folder variants into one ordered group', () => {
    const groups = groupVehicles([
      vehicle(3, 'Variant B', { tree_order: 3, folder_of: 2 }),
      vehicle(1, 'Root', { tree_order: 1 }),
      vehicle(2, 'Variant A', { tree_order: 2, folder_of: 1 }),
    ])

    expect(groups).toHaveLength(1)
    expect(groups[0].root.name).toBe('Root')
    expect(groups[0].children.map((item) => item.name)).toEqual(['Variant A', 'Variant B'])
  })

  it('keeps an orphaned folder entry visible as a standalone vehicle', () => {
    const groups = groupVehicles([vehicle(2, 'Orphan', { folder_of: 999 })])

    expect(groups).toHaveLength(1)
    expect(groups[0].root.name).toBe('Orphan')
    expect(groups[0].children).toEqual([])
  })
})
