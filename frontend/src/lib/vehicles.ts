import type { ProgressEntry, Vehicle } from '../types'

export type VehicleProgressUpdate = { vehicle: Vehicle; rp: number; done: boolean }
export type RankUnlockOperation = {
  unlock: VehicleProgressUpdate[]
  undo: VehicleProgressUpdate[]
}

export function isReserveVehicle(vehicle: Vehicle): boolean {
  return vehicle.type === 'tree' && vehicle.is_reserve
}

export function isResearchTarget(vehicle: Vehicle): boolean {
  return vehicle.type === 'tree' && typeof vehicle.rp_cost === 'number' && vehicle.rp_cost > 0
}

export function isResearchTreeVehicle(vehicle: Vehicle): boolean {
  return isReserveVehicle(vehicle) || isResearchTarget(vehicle)
}

export function isVehicleComplete(vehicle: Vehicle, progress: ProgressEntry): boolean {
  if (isReserveVehicle(vehicle)) return true
  const total = vehicle.rp_cost || 0
  return Boolean(progress.done || (total > 0 && (progress.rp || 0) >= total))
}

export function incompleteResearchTargets(
  vehicles: Vehicle[],
  getProgress: (vehicleId: number) => ProgressEntry,
): Vehicle[] {
  return vehicles.filter((vehicle) => (
    isResearchTarget(vehicle) && !isVehicleComplete(vehicle, getProgress(vehicle.id))
  ))
}

export function buildRankUnlockOperation(
  vehicles: Vehicle[],
  getProgress: (vehicleId: number) => ProgressEntry,
): RankUnlockOperation {
  const pending = incompleteResearchTargets(vehicles, getProgress)
  return {
    unlock: pending.map((vehicle) => ({
      vehicle,
      rp: vehicle.rp_cost || 0,
      done: true,
    })),
    undo: pending.map((vehicle) => {
      const progress = getProgress(vehicle.id)
      return {
        vehicle,
        rp: progress.rp || 0,
        done: Boolean(progress.done),
      }
    }),
  }
}

export function canUndoRankUnlock(
  operation: RankUnlockOperation,
  getProgress: (vehicleId: number) => ProgressEntry,
): boolean {
  return operation.unlock.length > 0 && operation.unlock.every(({ vehicle }) => (
    isVehicleComplete(vehicle, getProgress(vehicle.id))
  ))
}

export function rankResetUpdates(vehicles: Vehicle[]): VehicleProgressUpdate[] {
  return vehicles.filter(isResearchTarget).map((vehicle) => ({ vehicle, rp: 0, done: false }))
}
