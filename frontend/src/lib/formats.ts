import type { Vehicle } from '../types'

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']

export function formatRp(value: number): string {
  return value.toLocaleString('en-US')
}

export function formatMultiplier(value?: number | null): string {
  return (value ?? 1).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export function toRoman(value: number): string {
  return ROMAN[value - 1] || String(value)
}

export function battleRating(vehicle: Vehicle): number | null | undefined {
  return vehicle.br?.rb ?? vehicle.br?.ab ?? vehicle.br?.sb
}

export function vehicleCountLabel(count: number): string {
  return `${count} ${count === 1 ? 'vehicle' : 'vehicles'}`
}

export function availabilityLabel(vehicle: Vehicle): string {
  if (vehicle.availability === 'squadron') return 'Squadron'
  if (vehicle.availability === 'battle_pass') return 'Battle Pass'
  if (vehicle.availability === 'event') return 'Event'
  if (vehicle.availability === 'marketplace') return 'Marketplace'
  if (vehicle.availability === 'pack') return 'Store pack'
  if (vehicle.availability === 'special') return 'Special'
  if (vehicle.availability === 'limited') return 'Limited offer'
  if (vehicle.availability === 'unavailable') return 'Unavailable'
  if (vehicle.availability === 'retired') return 'Retired'
  return vehicle.type === 'premium' ? 'Premium' : 'Collector'
}

export function acquisitionSummary(vehicle: Vehicle): string {
  const market = vehicle.marketplace_item_id ? ' · Marketplace coupon' : ''
  if (vehicle.availability === 'battle_pass') return `Battle Pass reward${market}`
  if (vehicle.availability === 'event') return `Event reward${market}`
  if (vehicle.availability === 'marketplace') return 'Gaijin Marketplace coupon'
  if (vehicle.availability === 'pack') return 'Store pack vehicle'
  if (vehicle.availability === 'special') return 'Special or promotional vehicle'
  if (vehicle.availability === 'unavailable' || vehicle.availability === 'retired') return 'Not currently obtainable'
  if (vehicle.availability === 'squadron' && vehicle.rp_cost) return `${formatRp(vehicle.rp_cost)} squadron RP`
  if (vehicle.availability === 'limited' && vehicle.ge_cost) return `${formatRp(vehicle.ge_cost)} GE when available`
  if (vehicle.gjn_cost) return `${vehicle.gjn_cost} GJN`
  if (vehicle.ge_cost) return `${formatRp(vehicle.ge_cost)} GE`
  return 'No direct purchase price'
}

export function acquisitionDescription(vehicle: Vehicle): string {
  const premiumNote = vehicle.type === 'premium'
    ? ' It still has premium research efficiency when used in battle.'
    : ''
  const marketplaceNote = vehicle.marketplace_item_id
    ? ' A tradable coupon may also be available on the Gaijin Marketplace.'
    : ''
  if (vehicle.availability === 'battle_pass') {
    return `This vehicle was distributed as a Battle Pass reward.${premiumNote}${marketplaceNote}`
  }
  if (vehicle.availability === 'event') {
    return `This vehicle was distributed as an event reward.${premiumNote}${marketplaceNote}`
  }
  if (vehicle.availability === 'marketplace') {
    return `This vehicle is obtained through a tradable Marketplace coupon.${premiumNote}`
  }
  if (vehicle.availability === 'pack') {
    return `This vehicle is distributed through a Store pack, not as a direct GE purchase.${premiumNote}`
  }
  return `This vehicle is outside the standard research route.${premiumNote}`
}
