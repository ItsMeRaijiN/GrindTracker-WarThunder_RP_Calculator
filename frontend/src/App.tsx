import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError, AUTH_ENABLED, setCsrfToken } from './api'
import { AuthPanel } from './components/AuthPanel'
import { CommandBar } from './components/CommandBar'
import { Planner } from './components/Planner'
import { TechTree } from './components/TechTree'
import { TopBar } from './components/TopBar'
import {
  isResearchTarget,
  isResearchTreeVehicle,
  isVehicleComplete,
  type VehicleProgressUpdate,
} from './lib/vehicles'
import type { Nation, TreeResponse, User, Vehicle, VehicleClass } from './types'
import { useProgress } from './useProgress'

export default function App() {
  const [nations, setNations] = useState<Nation[]>([])
  const [classes, setClasses] = useState<VehicleClass[]>([])
  const [nation, setNation] = useState('')
  const [vehicleClass, setVehicleClass] = useState('')
  const [tree, setTree] = useState<TreeResponse | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [user, setUser] = useState<User | null>(null)
  const [authReady, setAuthReady] = useState(!AUTH_ENABLED)
  const [authOpen, setAuthOpen] = useState(false)
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const progress = useProgress(user)

  useEffect(() => {
    if (!AUTH_ENABLED) return
    sessionStorage.removeItem('grindtracker:auth-token')
    void api.me()
      .then(({ user: restored, csrf_token }) => {
        setCsrfToken(csrf_token)
        setUser(restored)
      })
      .catch(() => setCsrfToken(null))
      .finally(() => setAuthReady(true))
  }, [])

  useEffect(() => {
    let active = true
    Promise.all([api.nations(), api.classes()])
      .then(([nationRows, classRows]) => {
        if (!active) return
        setNations(nationRows)
        setClasses(classRows)
        setNation((current) => current || nationRows.find((item) => item.slug === 'germany')?.slug || nationRows[0]?.slug || '')
        setVehicleClass((current) => current || classRows.find((item) => item.name === 'army')?.name || classRows[0]?.name || '')
      })
      .catch((caught) => {
        if (!active) return
        setError(errorMessage(caught))
        setLoading(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!nation || !vehicleClass) return
    let active = true
    setLoading(true)
    setError(null)
    setTree(null)
    setSelectedId(null)
    api.tree(nation, vehicleClass)
      .then((value) => {
        if (!active) return
        setTree(value)
        const researchable = value.nodes.filter(isResearchTarget)
        setSelectedId((current) => researchable.some((item) => item.id === current) ? current : researchable[0]?.id || null)
      })
      .catch((caught) => active && setError(errorMessage(caught)))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [nation, vehicleClass])

  useEffect(() => {
    if (!user) return
    let active = true
    void api.getProgress()
      .then((rows) => active && progress.hydrateRemote(rows))
      .catch((caught) => active && progress.recoverFromHydrationFailure(caught))
    return () => { active = false }
  }, [user, progress.hydrateRemote, progress.recoverFromHydrationFailure])

  const selected = useMemo(
    () => tree?.nodes.find((item) => item.id === selectedId) || null,
    [selectedId, tree],
  )
  const queryCount = useMemo(() => {
    const value = query.trim().toLocaleLowerCase('en')
    return tree?.nodes.filter((item) => !value || item.name.toLocaleLowerCase('en').includes(value)).length || 0
  }, [query, tree])
  const treeVehicles = useMemo(
    () => tree?.nodes.filter(isResearchTreeVehicle) || [],
    [tree],
  )
  const completed = useMemo(
    () => treeVehicles.filter((item) => isVehicleComplete(item, progress.get(item.id))).length,
    [progress, treeVehicles],
  )

  async function authenticate(mode: 'login' | 'register', email: string, password: string) {
    try {
      setAuthBusy(true)
      setAuthError(null)
      const response = mode === 'login' ? await api.login(email, password) : await api.register(email, password)
      setCsrfToken(response.csrf_token)
      setUser(response.user)
      setSessionError(null)
      setAuthOpen(false)
    } catch (caught) {
      setAuthError(errorMessage(caught))
    } finally {
      setAuthBusy(false)
    }
  }

  async function logout() {
    if (progress.hasPendingChanges && !window.confirm(
      'Some progress changes have not synchronized yet. Signing out now will remove their local backup. Sign out anyway?',
    )) return
    setSessionError(null)
    try {
      await api.logout()
    } catch (caught) {
      if (!(caught instanceof ApiError) || (caught.status !== 401 && caught.status !== 403)) {
        setSessionError(`Could not securely sign out. ${errorMessage(caught)}`)
        return
      }
    }
    progress.clearUserCache()
    setCsrfToken(null)
    setUser(null)
  }

  const selectVehicle = useCallback((vehicle: Vehicle) => setSelectedId(vehicle.id), [])
  const toggleVehicleDone = useCallback(
    (vehicle: Vehicle, done: boolean) => progress.setProgress(
      vehicle.id,
      done ? vehicle.rp_cost || 0 : 0,
      done,
      vehicle.rp_cost || undefined,
    ),
    [progress.setProgress],
  )
  const saveVehicleProgress = useCallback(
    (vehicle: Vehicle, rp: number, done: boolean) => progress.setProgress(
      vehicle.id,
      rp,
      done,
      vehicle.rp_cost || undefined,
    ),
    [progress.setProgress],
  )
  const updateVehiclesProgress = useCallback(
    (updates: VehicleProgressUpdate[]) => progress.setProgressBulk(updates.map(({ vehicle, rp, done }) => ({
      vehicleId: vehicle.id,
      rp,
      done,
      total: vehicle.rp_cost || undefined,
    }))),
    [progress.setProgressBulk],
  )

  return (
    <div className="app" id="top">
      <TopBar authEnabled={AUTH_ENABLED} user={user} authReady={authReady} online={!error} authOpen={authOpen} onToggleAuth={() => setAuthOpen((value) => !value)} onLogout={logout} />
      {AUTH_ENABLED && authOpen && !user && <AuthPanel busy={authBusy} error={authError} onSubmit={authenticate} />}

      <main>
        <section className="hero">
          <div>
            <div className="eyebrow">War Thunder · research planning</div>
            <h1><em>Plan your next unlock.</em></h1>
            <p>An interactive research tree, saved progress, and a forecast based on your battles — with vehicle-specific RP multipliers.</p>
          </div>
          <div className="mission-stats" aria-label="Current research tree statistics">
            <div><span>VEHICLES</span><strong>{treeVehicles.length}</strong></div>
            <div><span>UNLOCKED</span><strong>{completed}</strong></div>
            <div><span>PROGRESS</span><strong>{treeVehicles.length ? Math.round((completed / treeVehicles.length) * 100) : 0}%</strong></div>
          </div>
        </section>

        <CommandBar
          nations={nations}
          classes={classes}
          nation={nation}
          vehicleClass={vehicleClass}
          query={query}
          count={queryCount}
          onNationChange={setNation}
          onClassChange={setVehicleClass}
          onQueryChange={setQuery}
        />

        {progress.syncError && <div className="sync-warning">Progress was saved locally. Sync error: {progress.syncError}</div>}
        {progress.syncNotice && <div className="sync-warning" role="status">{progress.syncNotice}</div>}
        {sessionError && <div className="page-error" role="alert"><strong>Could not sign out.</strong><span>{sessionError}</span></div>}
        {error && <div className="page-error" role="alert"><strong>Could not load data.</strong><span>{error}</span></div>}

        <div className="workspace">
          <div className="tree-area">
            {loading && <TreeSkeleton />}
            {!loading && tree && (
              <TechTree
                tree={tree}
                query={query}
                selectedId={selectedId}
                getProgress={progress.get}
                onSelect={selectVehicle}
                onToggleDone={toggleVehicleDone}
                onUpdateRank={updateVehiclesProgress}
              />
            )}
          </div>
          {tree && (
            <Planner
              selected={selected}
              tree={tree}
              getProgress={progress.get}
              exportProgress={progress.exportPayload}
              onSaveProgress={saveVehicleProgress}
            />
          )}
        </div>
      </main>

      <footer>
        <span>GrindTracker v1.0</span>
        <p>Independent fan project. War Thunder and related trademarks belong to Gaijin Entertainment.</p>
        {!user && (
          <button
            className="clear-local"
            type="button"
            onClick={() => {
              if (window.confirm('Clear all progress stored in this browser profile?')) progress.clearLocalProgress()
            }}
          >
            Clear local progress
          </button>
        )}
      </footer>
    </div>
  )
}

function TreeSkeleton() {
  return (
    <div className="tree-skeleton" aria-label="Loading research tree">
      <div className="skeleton-title" />
      <div className="skeleton-ranks">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index}>
            <span />
            <i />
          </div>
        ))}
      </div>
    </div>
  )
}

function errorMessage(value: unknown) {
  return value instanceof Error ? value.message : 'Unknown error.'
}
