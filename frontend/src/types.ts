export type Nation = { id: number; slug: string; name: string }
export type VehicleClass = { id: number; name: string }
export type User = { id: number; email: string }

export type Vehicle = {
  id: number
  name: string
  nation: string
  class: string
  rank: number
  type: 'tree' | 'premium' | 'collector'
  is_reserve: boolean
  availability?:
    | 'researchable'
    | 'premium'
    | 'limited'
    | 'squadron'
    | 'battle_pass'
    | 'event'
    | 'marketplace'
    | 'pack'
    | 'special'
    | 'unavailable'
    | 'retired'
    | string
  tree_column?: number | null
  tree_order?: number | null
  br?: { ab?: number | null; rb?: number | null; sb?: number | null }
  rp_multiplier?: number | null
  rp_cost?: number | null
  ge_cost?: number | null
  gjn_cost?: number | null
  marketplace_item_id?: number | null
  folder_of?: number | null
}

export type Edge = { parent: number; child: number; unlock_rp?: number | null }

export type ResearchEfficiencyRules = {
  premium_max_target_rank_offset: number
  target_above: Record<string, number>
  target_above_default: number
  target_below: Record<string, number>
  target_below_default: number
}

export type TreeResponse = {
  nodes: Vehicle[]
  edges: Edge[]
  meta?: {
    nation: string
    class: string
    vehicle_count: number
    research_column_count?: number
    research_efficiency?: ResearchEfficiencyRules
    source_version?: string | null
    source_revision?: string | null
    updated_at?: string | null
  }
}

export type RecentBattle = { rp: number; minutes: number }
export type ProgressEntry = { rp?: number; done?: boolean }
export type ProgressPayload = Record<number, { rp_current: number; done: boolean }>

export type CalcPayload = {
  vehicle_id: number
  research_vehicle_id?: number
  rp_current?: number
  avg_rp_per_battle?: number
  avg_battle_minutes?: number
  recent_battles?: RecentBattle[]
  rp_is_base?: boolean
  has_premium?: boolean
  booster_percent?: number
  skill_bonus_percent?: number
  has_talisman?: boolean
  game_mode?: 'ab' | 'rb' | 'sb'
  progress?: ProgressPayload
}

type AverageSummary = {
  avg_rp_per_battle: number
  avg_battle_minutes: number
  samples: number
  rp_is_base: boolean
}

export type EstimateResult = {
  vehicle: Pick<Vehicle, 'id' | 'name' | 'rank' | 'type' | 'rp_cost' | 'ge_cost'>
  research_vehicle?: Pick<Vehicle, 'id' | 'name' | 'rank' | 'type' | 'rp_multiplier'> | null
  rp_current: number
  rp_remaining: number
  base_from_recent: AverageSummary
  effective_rp_per_battle: number
  modifiers: RpModifiers
  battles_needed: number | null
  minutes_needed: number | null
  hours_needed: number | null
  ge_cost_by_rate: number
  prerequisite_ids: number[]
  prerequisites: Array<{ id: number; name: string }>
}

export type CascadeBreakdown = {
  id: number
  name: string
  rank: number
  rp_cost: number
  rp_current: number
  rp_remaining: number
  done: boolean
  effective_rp_per_battle: number
  research_efficiency: number
  direct_predecessor_bonus: boolean
}

export type CascadeResult = {
  target: { id: number; name: string }
  research_vehicle?: Pick<Vehicle, 'id' | 'name' | 'rank' | 'type' | 'rp_multiplier'> | null
  base_from_recent: AverageSummary
  effective_rp_per_battle: number
  modifiers: RpModifiers
  required_ids: number[]
  breakdown: CascadeBreakdown[]
  rp_total_remaining: number
  battles_needed: number | null
  minutes_needed: number | null
  hours_needed: number | null
  ge_cost_by_rate: number
}

export type RpModifiers = {
  vehicle_rp_multiplier: number
  vehicle_rp_multiplier_applied: boolean
  economy_multiplier: number
  research_efficiency: number
  direct_predecessor_bonus: boolean
}
