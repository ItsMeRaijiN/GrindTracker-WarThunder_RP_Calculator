import type { CalcPayload, CascadeResult, EstimateResult, RpModifiers, StaticCatalog, Vehicle } from '../types'

// Python's round() uses ties-to-even. Keep forecasts identical to the API,
// including half-minute durations and exact decimal ties.
export function roundLikePython(value: number, places = 0): number {
  const scale = 10 ** places
  const scaled = value * scale
  const lower = Math.floor(scaled)
  if (Number.isInteger(value * 2 ** (places + 1)) && scaled - lower === 0.5) {
    return (lower % 2 === 0 ? lower : lower + 1) / scale
  }
  return Number(value.toFixed(places))
}

function number(value: number | undefined, fallback: number, max: number, integer = false): number {
  const result = value ?? fallback
  if (!Number.isFinite(result) || result < 0 || result > max || (integer && !Number.isInteger(result))) {
    throw new Error('Enter a valid non-negative value within the supported range.')
  }
  return result
}

function forecast(payload: CalcPayload) {
  if ((payload.recent_battles?.length || 0) > 5) throw new Error('Use at most five recent battles.')
  const recent = (payload.recent_battles || []).map((row) => ({
    rp: number(row.rp, 0, 10_000_000),
    minutes: number(row.minutes, 0, 300),
  })).filter((row) => row.rp > 0)
  const durations = recent.filter((row) => row.minutes > 0)
  const avgRp = number(payload.avg_rp_per_battle, 0, 10_000_000)
  const avgMinutes = number(payload.avg_battle_minutes, 9, 300)
  return {
    rp: recent.length ? recent.reduce((sum, row) => sum + row.rp, 0) / recent.length : avgRp,
    minutes: recent.length
      ? durations.length ? durations.reduce((sum, row) => sum + row.minutes, 0) / durations.length : 9
      : avgMinutes,
    samples: recent.length,
    base: Boolean(payload.rp_is_base),
    economy: 1 + Number(Boolean(payload.has_premium)) + Number(Boolean(payload.has_talisman))
      + number(payload.booster_percent, 0, 1000, true) / 100
      + number(payload.skill_bonus_percent, 0, 500, true) / 100,
  }
}

function vehicleSummary(vehicle: Vehicle) {
  return {
    id: vehicle.id, name: vehicle.name, rank: vehicle.rank, type: vehicle.type,
    rp_cost: vehicle.rp_cost ?? null, ge_cost: vehicle.ge_cost ?? null,
    rp_multiplier: vehicle.rp_multiplier ?? null,
  }
}

function timeEstimate(remaining: number, effectiveRp: number, averageMinutes: number) {
  if (remaining === 0) return { battles_needed: 0, minutes_needed: 0, hours_needed: 0 }
  if (effectiveRp <= 0) return { battles_needed: null, minutes_needed: null, hours_needed: null }
  const battles = Math.ceil(remaining / effectiveRp)
  const minutes = roundLikePython(battles * averageMinutes)
  return { battles_needed: battles, minutes_needed: minutes, hours_needed: roundLikePython(minutes / 60, 2) }
}

export function createCalculator(catalog: StaticCatalog) {
  const vehicles = new Map(catalog.nodes.map((vehicle) => [vehicle.id, vehicle]))
  const parents = new Map<number, Set<number>>()
  const directParents = new Map<number, Set<number>>()
  const add = (map: Map<number, Set<number>>, child: number, parent: number) => {
    const values = map.get(child) || new Set<number>()
    values.add(parent)
    map.set(child, values)
  }
  catalog.edges.forEach((edge) => {
    if (!vehicles.has(edge.parent) || !vehicles.has(edge.child)) return
    add(parents, edge.child, edge.parent)
    add(directParents, edge.child, edge.parent)
  })
  catalog.nodes.forEach((vehicle) => {
    if (vehicle.folder_of && vehicles.has(vehicle.folder_of)) add(parents, vehicle.id, vehicle.folder_of)
  })

  function prepare(payload: CalcPayload) {
    const target = vehicles.get(payload.vehicle_id)
    if (!target) throw new Error('Vehicle not found.')
    if (!target.rp_cost) throw new Error('This vehicle has no research RP cost and cannot be a target.')
    const source = payload.research_vehicle_id === undefined ? null : vehicles.get(payload.research_vehicle_id)
    if (source === undefined) throw new Error('Research vehicle not found.')
    if (source?.id === target.id) throw new Error('The target cannot also be the research vehicle.')
    if (source && (source.nation !== target.nation || source.class !== target.class)) {
      throw new Error('The research vehicle must belong to the same nation and branch.')
    }
    if (payload.game_mode && !['ab', 'rb', 'sb'].includes(payload.game_mode)) throw new Error('Invalid game mode.')
    const pace = forecast(payload)
    const current = number(payload.rp_current, 0, 100_000_000, true)
    const average = {
      avg_rp_per_battle: roundLikePython(pace.rp, 2),
      avg_battle_minutes: roundLikePython(pace.minutes, 2),
      samples: pace.samples,
      rp_is_base: pace.base,
    }
    function calculate(vehicle: Vehicle) {
      const rules = catalog.trees.find((tree) => tree.nation === vehicle.nation && tree.class === vehicle.class)?.research_efficiency
      if (!rules) throw new Error('The catalog is missing research efficiency rules. Reload the page.')
      const direct = Boolean(source && directParents.get(vehicle.id)?.has(source.id))
      let efficiency = 1
      if (direct) efficiency = payload.game_mode === 'ab' ? 1.3 : 1.1
      else if (source && !(source.type === 'premium' && vehicle.rank <= source.rank + rules.premium_max_target_rank_offset)) {
        const difference = vehicle.rank - source.rank
        efficiency = difference >= 0
          ? rules.target_above[String(difference)] ?? rules.target_above_default
          : rules.target_below[String(-difference)] ?? rules.target_below_default
      }
      const multiplier = Math.max(0, source?.rp_multiplier || 1)
      const effective = pace.rp * (pace.base ? multiplier * pace.economy : 1) * efficiency
      const modifiers: RpModifiers = {
        vehicle_rp_multiplier: multiplier,
        vehicle_rp_multiplier_applied: pace.base,
        economy_multiplier: pace.economy,
        research_efficiency: efficiency,
        direct_predecessor_bonus: direct,
      }
      return { effective, modifiers }
    }
    return { target, source, pace, current, average, calculate }
  }

  return {
    estimate(payload: CalcPayload): EstimateResult {
      const { target, source, pace, current, average, calculate } = prepare(payload)
      const rpCurrent = Math.min(current, target.rp_cost || 0)
      const remaining = (target.rp_cost || 0) - rpCurrent
      const result = calculate(target)
      const requirements = [...(parents.get(target.id) || [])].sort((a, b) => a - b)
      return {
        vehicle: vehicleSummary(target),
        research_vehicle: source ? vehicleSummary(source) : null,
        rp_current: rpCurrent,
        rp_remaining: remaining,
        base_from_recent: average,
        effective_rp_per_battle: roundLikePython(result.effective, 2),
        modifiers: result.modifiers,
        ...timeEstimate(remaining, result.effective, pace.minutes),
        ge_cost_by_rate: Math.ceil(remaining / 45),
        prerequisite_ids: requirements,
        prerequisites: requirements.map((id) => ({ id, name: vehicles.get(id)!.name })),
      }
    },
    cascade(payload: CalcPayload): CascadeResult {
      const { target, source, pace, current, average, calculate } = prepare(payload)
      if (Object.keys(payload.progress || {}).length > 5000) throw new Error('Too many progress entries.')
      const progress = { ...payload.progress }
      progress[target.id] ??= { rp_current: current, done: false }
      const found = new Set<number>()
      const pending = [target.id]
      while (pending.length) {
        for (const parent of parents.get(pending.pop()!) || []) {
          if (parent === target.id || found.has(parent)) continue
          found.add(parent)
          pending.push(parent)
        }
      }
      const requiredIds = [...found].sort((a, b) => a - b).concat(target.id)
      const route = requiredIds.map((id) => vehicles.get(id)!).sort((a, b) => (
        a.rank - b.rank || (a.tree_column || 0) - (b.tree_column || 0)
        || (a.tree_order || 0) - (b.tree_order || 0) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0)
      ))
      let totalRemaining = 0
      let totalBattles = 0
      let unknown = false
      const breakdown = route.map((vehicle) => {
        const total = vehicle.rp_cost || 0
        const saved = progress[vehicle.id]
        const done = Boolean(saved?.done || vehicle.is_reserve)
        const rpCurrent = Math.min(number(saved?.rp_current, 0, 100_000_000, true), total)
        const remaining = done ? 0 : total - rpCurrent
        totalRemaining += remaining
        const result = calculate(vehicle)
        const time = timeEstimate(remaining, result.effective, pace.minutes)
        if (time.battles_needed === null) unknown ||= remaining > 0
        else totalBattles += time.battles_needed
        return {
          id: vehicle.id, name: vehicle.name, rank: vehicle.rank, rp_cost: total,
          rp_current: rpCurrent, rp_remaining: remaining, done,
          effective_rp_per_battle: roundLikePython(result.effective, 2),
          research_efficiency: result.modifiers.research_efficiency,
          direct_predecessor_bonus: result.modifiers.direct_predecessor_bonus,
        }
      })
      const result = calculate(target)
      const minutes = unknown ? null : roundLikePython(totalBattles * pace.minutes)
      return {
        target: { id: target.id, name: target.name },
        research_vehicle: source ? vehicleSummary(source) : null,
        base_from_recent: average,
        effective_rp_per_battle: roundLikePython(result.effective, 2),
        modifiers: result.modifiers,
        required_ids: requiredIds,
        breakdown,
        rp_total_remaining: totalRemaining,
        battles_needed: unknown ? null : totalBattles,
        minutes_needed: minutes,
        hours_needed: minutes === null ? null : roundLikePython(minutes / 60, 2),
        ge_cost_by_rate: Math.ceil(totalRemaining / 45),
      }
    },
  }
}
