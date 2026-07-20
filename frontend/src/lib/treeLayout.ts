import type { Vehicle } from '../types'

export type VehicleGroup = {
  root: Vehicle
  children: Vehicle[]
  vehicles: Vehicle[]
}

export type ResearchLane = {
  column: number
  groups: VehicleGroup[]
}

export type RankSection = {
  rank: number
  vehicles: Vehicle[]
  lanes: ResearchLane[]
}

export type TechTreeLayout = {
  columns: number[]
  researchColumnCount: number
  ranks: RankSection[]
}

export function buildTechTreeLayout(nodes: Vehicle[], researchColumnCount?: number): TechTreeLayout {
  const columns = [...new Set(nodes.map((vehicle) => vehicle.tree_column ?? 0))].sort((a, b) => a - b)
  const ranks = [...new Set(nodes.map((vehicle) => vehicle.rank))].sort((a, b) => a - b)
  const safeResearchColumnCount = Math.max(1, Math.min(columns.length, researchColumnCount ?? columns.length))

  return {
    columns,
    researchColumnCount: safeResearchColumnCount,
    ranks: ranks.map((rank) => {
      const rankVehicles = nodes.filter((vehicle) => vehicle.rank === rank)
      return {
        rank,
        vehicles: sortVehicles(rankVehicles),
        lanes: columns.map((column) => ({
          column,
          groups: groupVehicles(rankVehicles.filter((vehicle) => (vehicle.tree_column ?? 0) === column)),
        })),
      }
    }),
  }
}

export function groupVehicles(vehicles: Vehicle[]): VehicleGroup[] {
  const sorted = sortVehicles(vehicles)
  const byId = new Map(sorted.map((vehicle) => [vehicle.id, vehicle]))
  const children = new Map<number, Vehicle[]>()
  sorted.forEach((vehicle) => {
    if (vehicle.folder_of && byId.has(vehicle.folder_of)) {
      children.set(vehicle.folder_of, [...(children.get(vehicle.folder_of) || []), vehicle])
    }
  })

  const roots = sorted.filter((vehicle) => !vehicle.folder_of || !byId.has(vehicle.folder_of))
  return roots.map((root) => {
    const descendants: Vehicle[] = []
    const pending = [...(children.get(root.id) || [])]
    while (pending.length) {
      const vehicle = pending.shift()!
      descendants.push(vehicle)
      pending.push(...(children.get(vehicle.id) || []))
    }
    const orderedChildren = sortVehicles(descendants)
    return { root, children: orderedChildren, vehicles: [root, ...orderedChildren] }
  })
}

function sortVehicles(vehicles: Vehicle[]): Vehicle[] {
  return [...vehicles].sort((left, right) => (
    (left.tree_column ?? 0) - (right.tree_column ?? 0)
    || (left.tree_order ?? Number.MAX_SAFE_INTEGER) - (right.tree_order ?? Number.MAX_SAFE_INTEGER)
    || left.name.localeCompare(right.name)
  ))
}
