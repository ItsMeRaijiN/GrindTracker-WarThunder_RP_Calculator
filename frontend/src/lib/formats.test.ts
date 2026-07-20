import { describe, expect, it } from 'vitest'
import { acquisitionSummary, availabilityLabel } from './formats'
import type { Vehicle } from '../types'

const baseVehicle: Vehicle = {
  id: 1,
  name: 'Test vehicle',
  nation: 'france',
  class: 'army',
  rank: 5,
  type: 'premium',
  is_reserve: false,
}

describe('vehicle acquisition formatting', () => {
  it('does not present a Battle Pass nominal value as a GE purchase price', () => {
    const vehicle = { ...baseVehicle, availability: 'battle_pass', ge_cost: 8200, marketplace_item_id: 50210 }

    expect(availabilityLabel(vehicle)).toBe('Battle Pass')
    expect(acquisitionSummary(vehicle)).toBe('Battle Pass reward · Marketplace coupon')
  })

  it('shows direct and rotating GE offers with the correct qualifier', () => {
    expect(acquisitionSummary({ ...baseVehicle, availability: 'premium', ge_cost: 6090 })).toBe('6,090 GE')
    expect(acquisitionSummary({ ...baseVehicle, availability: 'limited', ge_cost: 1300 })).toBe('1,300 GE when available')
  })
})
