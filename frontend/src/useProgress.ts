import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from './api'
import type { ProgressEntry, ProgressPayload, User } from './types'

export type StoredProgress = ProgressEntry & { dirty?: boolean }
export type ProgressMap = Record<number, StoredProgress>
export type RemoteProgressRow = { vehicle_id: number; rp_earned: number; done: boolean }
export type ProgressUpdate = { vehicleId: number; rp: number; done: boolean; total?: number }

const STORAGE_PREFIX = 'grindtracker:progress:v5:'
const LEGACY_STORAGE_PREFIX = 'grindtracker:progress:v4:'
const MAX_LOCAL_RP = 100_000_000

function storageKey(user: User | null) {
  return `${STORAGE_PREFIX}${user ? `user:${user.id}` : 'guest'}`
}

function legacyStorageKey(user: User | null) {
  return `${LEGACY_STORAGE_PREFIX}${user ? `user:${user.id}` : 'guest'}`
}

function migrationKey(user: User) {
  return `${STORAGE_PREFIX}migration:user:${user.id}`
}

function readProgress(key: string): ProgressMap {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '{}') as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const result: ProgressMap = {}
    Object.entries(parsed).forEach(([rawId, rawEntry]) => {
      const id = Number(rawId)
      if (!Number.isSafeInteger(id) || id <= 0 || !rawEntry || typeof rawEntry !== 'object') return
      const entry = rawEntry as Record<string, unknown>
      const value = Number(entry.rp)
      const rp = Number.isFinite(value) ? Math.min(MAX_LOCAL_RP, Math.max(0, Math.floor(value))) : 0
      result[id] = { rp, done: entry.done === true, dirty: entry.dirty === true || undefined }
    })
    return result
  } catch {
    return {}
  }
}

function writeProgress(key: string, value: ProgressMap): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value))
    return true
  } catch {
    return false
  }
}

function removeProgress(key: string) {
  try {
    localStorage.removeItem(key)
  } catch {}
}

export function mergeGuestProgress(account: ProgressMap, guest: ProgressMap): ProgressMap {
  const next = { ...account }
  Object.entries(guest).forEach(([id, entry]) => {
    const vehicleId = Number(id)
    const current = next[vehicleId]
    const merged = {
      rp: Math.max(current?.rp || 0, entry.rp || 0),
      done: Boolean(current?.done || entry.done),
    }
    next[vehicleId] = {
      ...merged,
      dirty: Boolean(
        current?.dirty
        || current === undefined
        || merged.rp !== (current.rp || 0)
        || merged.done !== Boolean(current.done)
      ) || undefined,
    }
  })
  return next
}

export function reconcileSynchronizedProgress(
  current: ProgressMap,
  sent: ProgressMap,
  rows: RemoteProgressRow[],
): ProgressMap {
  const next = { ...current }
  rows.forEach((row) => {
    const before = sent[row.vehicle_id]
    const latest = current[row.vehicle_id]
    if (!before || !latest || latest.rp !== before.rp || Boolean(latest.done) !== Boolean(before.done)) return
    next[row.vehicle_id] = { rp: row.rp_earned, done: row.done }
  })
  return next
}

export function removeProgressEntries(source: ProgressMap, vehicleIds: number[]): ProgressMap {
  const rejected = new Set(vehicleIds)
  return Object.fromEntries(
    Object.entries(source).filter(([id]) => !rejected.has(Number(id))),
  ) as ProgressMap
}

export function applyProgressUpdates(
  source: ProgressMap,
  updates: ProgressUpdate[],
  markDirty: boolean,
): ProgressMap {
  let next: ProgressMap | null = null
  updates.forEach(({ vehicleId, rp, done, total }) => {
    if (!Number.isSafeInteger(vehicleId) || vehicleId <= 0 || !total || total <= 0) return
    const safeRp = Math.min(Math.max(0, Math.floor(Number.isFinite(rp) ? rp : 0)), total)
    const safeDone = done || safeRp >= total
    const entry: StoredProgress = {
      rp: safeDone ? total : safeRp,
      done: safeDone,
      dirty: markDirty || undefined,
    }
    const current = (next || source)[vehicleId]
    if (
      current
      && current.rp === entry.rp
      && Boolean(current.done) === entry.done
      && Boolean(current.dirty) === Boolean(entry.dirty)
    ) return
    if (!next) next = { ...source }
    next[vehicleId] = entry
  })
  return next || source
}

export function mergeHydratedProgress(
  current: ProgressMap,
  pendingMigration: ProgressMap,
  rows: RemoteProgressRow[],
): ProgressMap {
  const next: ProgressMap = Object.fromEntries(rows.map((row) => [row.vehicle_id, {
    rp: row.rp_earned,
    done: row.done,
  }]))
  Object.entries(current).forEach(([id, entry]) => {
    const migrationEntry = pendingMigration[Number(id)]
    const isLegacyMigrationCopy = Boolean(
      migrationEntry
      && entry.dirty
      && entry.rp === migrationEntry.rp
      && Boolean(entry.done) === Boolean(migrationEntry.done),
    )
    if (entry.dirty && !isLegacyMigrationCopy) next[Number(id)] = entry
  })
  return mergeGuestProgress(next, pendingMigration)
}

function dirtyEntries(source: ProgressMap): ProgressMap {
  return Object.fromEntries(Object.entries(source).filter(([, entry]) => entry.dirty)) as ProgressMap
}

function hasEntries(source: ProgressMap): boolean {
  return Object.keys(source).length > 0
}

export function isMigrationConfirmed(current: ProgressMap, pending: ProgressMap): boolean {
  return hasEntries(pending) && Object.keys(pending).every((id) => {
    const entry = current[Number(id)]
    return Boolean(entry && !entry.dirty)
  })
}

type SyncState = { key: string; running: boolean; resync: boolean; hydrated: boolean }

export function useProgress(user: User | null) {
  const key = storageKey(user)
  const [entries, setEntries] = useState<ProgressMap>(() => readProgress(key))
  const entriesRef = useRef(entries)
  const activeKeyRef = useRef(key)
  activeKeyRef.current = key
  const syncStateRef = useRef<SyncState>({ key, running: false, resync: false, hydrated: !user })
  if (syncStateRef.current.key !== key) {
    syncStateRef.current = { key, running: false, resync: false, hydrated: !user }
  }
  const [syncError, setSyncError] = useState<string | null>(null)
  const [syncNotice, setSyncNotice] = useState<string | null>(null)

  const replaceEntries = useCallback((next: ProgressMap) => {
    if (activeKeyRef.current !== key) return
    entriesRef.current = next
    writeProgress(key, next)
    setEntries(next)
  }, [key])

  const finalizeGuestMigration = useCallback((current: ProgressMap) => {
    if (!user) return
    const pendingKey = migrationKey(user)
    const pending = readProgress(pendingKey)
    if (isMigrationConfirmed(current, pending)) removeProgress(pendingKey)
  }, [user])

  const synchronizePending = useCallback(() => {
    if (!user) return
    const state = syncStateRef.current
    if (state.key !== key || !state.hydrated) return
    if (state.running) {
      state.resync = true
      return
    }
    state.running = true

    void (async () => {
      while (activeKeyRef.current === key) {
        state.resync = false
        const sent = dirtyEntries(entriesRef.current)
        if (!hasEntries(sent)) {
          finalizeGuestMigration(entriesRef.current)
          break
        }
        const payload = Object.fromEntries(
          Object.entries(sent).map(([id, entry]) => [Number(id), {
            rp_earned: entry.rp || 0,
            done: Boolean(entry.done),
          }]),
        )
        try {
          const { items } = await api.saveProgressBulk(payload)
          if (activeKeyRef.current !== key) break
          const next = reconcileSynchronizedProgress(entriesRef.current, sent, items)
          replaceEntries(next)
          finalizeGuestMigration(next)
          setSyncError(null)
        } catch (error) {
          const rejected = error instanceof ApiError
            ? error.rejectedVehicleIds.filter((vehicleId) => sent[vehicleId])
            : []
          if (activeKeyRef.current === key && rejected.length > 0) {
            const next = removeProgressEntries(entriesRef.current, rejected)
            replaceEntries(next)
            const pendingKey = migrationKey(user)
            const pending = removeProgressEntries(readProgress(pendingKey), rejected)
            if (hasEntries(pending)) writeProgress(pendingKey, pending)
            else removeProgress(pendingKey)
            setSyncError(null)
            setSyncNotice(
              `Removed stale progress for ${rejected.length} ${rejected.length === 1 ? 'vehicle' : 'vehicles'} no longer available for research.`,
            )
            continue
          }
          if (activeKeyRef.current === key) {
            setSyncError(error instanceof Error ? error.message : 'Could not synchronize progress.')
          }
          break
        }
        if (!state.resync) break
      }
    })().finally(() => {
      state.running = false
      state.resync = false
    })
  }, [finalizeGuestMigration, key, replaceEntries, user])

  useEffect(() => {
    let stored = readProgress(key)
    const oldKey = legacyStorageKey(user)
    const legacy = readProgress(oldKey)
    if (hasEntries(legacy)) {
      stored = mergeGuestProgress(stored, legacy)
      if (!user) {
        stored = Object.fromEntries(
          Object.entries(stored).map(([id, entry]) => [Number(id), { rp: entry.rp, done: entry.done }]),
        )
      }
      if (writeProgress(key, stored)) removeProgress(oldKey)
    }
    if (user) {
      const pendingKey = migrationKey(user)
      let pending = readProgress(pendingKey)
      const guestKey = storageKey(null)
      const guest = readProgress(guestKey)
      if (hasEntries(guest)) {
        pending = mergeGuestProgress(pending, guest)
        if (writeProgress(pendingKey, pending)) removeProgress(guestKey)
      }
    }
    replaceEntries(stored)
    setSyncError(null)
    setSyncNotice(null)
  }, [key, replaceEntries, user])

  const hydrateRemote = useCallback((rows: RemoteProgressRow[]) => {
    if (!user) return
    const pending = readProgress(migrationKey(user))
    const next = mergeHydratedProgress(entriesRef.current, pending, rows)
    syncStateRef.current.hydrated = true
    replaceEntries(next)
    if (hasEntries(dirtyEntries(next))) synchronizePending()
    else finalizeGuestMigration(next)
  }, [finalizeGuestMigration, replaceEntries, synchronizePending, user])

  const recoverFromHydrationFailure = useCallback((error: unknown) => {
    setSyncError(error instanceof Error ? error.message : 'Could not load synchronized progress.')
    if (!user || syncStateRef.current.key !== key) return
    const pending = readProgress(migrationKey(user))
    const next = mergeGuestProgress(entriesRef.current, pending)
    syncStateRef.current.hydrated = true
    replaceEntries(next)
    if (hasEntries(dirtyEntries(next))) synchronizePending()
  }, [key, replaceEntries, synchronizePending, user])

  const setProgressBulk = useCallback(
    (updates: ProgressUpdate[]) => {
      const next = applyProgressUpdates(entriesRef.current, updates, Boolean(user))
      if (next === entriesRef.current) return
      setSyncNotice(null)
      replaceEntries(next)
      synchronizePending()
    },
    [replaceEntries, synchronizePending, user],
  )

  const setProgress = useCallback(
    (vehicleId: number, rp: number, done: boolean, total?: number) => {
      setProgressBulk([{ vehicleId, rp, done, total }])
    },
    [setProgressBulk],
  )

  const clearLocalProgress = useCallback(() => {
    if (user) return
    replaceEntries({})
    removeProgress(legacyStorageKey(null))
    setSyncError(null)
    setSyncNotice(null)
  }, [replaceEntries, user])

  const clearUserCache = useCallback(() => {
    if (!user) return
    removeProgress(key)
    removeProgress(legacyStorageKey(user))
    removeProgress(migrationKey(user))
  }, [key, user])

  useEffect(() => {
    const refreshFromStorage = (event: StorageEvent) => {
      if (event.storageArea !== localStorage || event.key !== key) return
      const next = readProgress(key)
      entriesRef.current = next
      setEntries(next)
      if (user && hasEntries(dirtyEntries(next))) synchronizePending()
    }
    window.addEventListener('storage', refreshFromStorage)
    return () => window.removeEventListener('storage', refreshFromStorage)
  }, [key, synchronizePending, user])

  return useMemo(
    () => ({
      entries,
      syncError,
      syncNotice,
      hasPendingChanges: Object.values(entries).some((entry) => entry.dirty),
      hydrateRemote,
      recoverFromHydrationFailure,
      setProgress,
      setProgressBulk,
      clearLocalProgress,
      clearUserCache,
      get: (vehicleId: number) => entries[vehicleId] || { rp: 0, done: false },
      exportPayload: (): ProgressPayload =>
        Object.fromEntries(
          Object.entries(entries).map(([id, entry]) => [Number(id), {
            rp_current: entry.rp || 0,
            done: Boolean(entry.done),
          }]),
        ),
    }),
    [
      clearLocalProgress,
      clearUserCache,
      entries,
      hydrateRemote,
      recoverFromHydrationFailure,
      setProgress,
      setProgressBulk,
      syncError,
      syncNotice,
    ],
  )
}
