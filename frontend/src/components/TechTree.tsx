import { memo, useEffect, useMemo, useState, type CSSProperties } from 'react'
import {
  acquisitionSummary,
  availabilityLabel,
  battleRating,
  formatMultiplier,
  formatRp,
  toRoman,
  vehicleCountLabel,
} from '../lib/formats'
import { buildTechTreeLayout, type VehicleGroup } from '../lib/treeLayout'
import {
  buildRankUnlockOperation,
  canUndoRankUnlock,
  isResearchTarget,
  isResearchTreeVehicle,
  isReserveVehicle,
  isVehicleComplete,
  rankResetUpdates,
  type RankUnlockOperation,
  type VehicleProgressUpdate,
} from '../lib/vehicles'
import type { ProgressEntry, TreeResponse, Vehicle } from '../types'

type Props = {
  tree: TreeResponse
  query: string
  selectedId: number | null
  getProgress: (id: number) => ProgressEntry
  onSelect: (vehicle: Vehicle) => void
  onToggleDone: (vehicle: Vehicle, done: boolean) => void
  onUpdateRank: (updates: VehicleProgressUpdate[]) => void
}

type CardContext = Pick<Props, 'selectedId' | 'getProgress' | 'onSelect' | 'onToggleDone'> & {
  nodeMap: Map<number, Vehicle>
  parents: Map<number, number[]>
  path: Set<number>
  normalizedQuery: string
}

export function TechTree({ tree, query, selectedId, getProgress, onSelect, onToggleDone, onUpdateRank }: Props) {
  const layout = useMemo(
    () => buildTechTreeLayout(tree.nodes, tree.meta?.research_column_count),
    [tree.meta?.research_column_count, tree.nodes],
  )
  const nodeMap = useMemo(() => new Map(tree.nodes.map((item) => [item.id, item])), [tree.nodes])
  const parents = useMemo(() => buildParentMap(tree), [tree])
  const path = useMemo(() => collectAncestorIds(selectedId, parents), [parents, selectedId])
  const [collapsedRanks, setCollapsedRanks] = useState<Set<number>>(new Set())
  const [openFolders, setOpenFolders] = useState<Set<number>>(new Set())
  const [rankOperations, setRankOperations] = useState<Map<number, RankUnlockOperation>>(new Map())
  const normalizedQuery = query.trim().toLocaleLowerCase('en')
  const treeIdentity = `${tree.meta?.nation || ''}:${tree.meta?.class || ''}`

  useEffect(() => {
    setCollapsedRanks(new Set())
    setOpenFolders(new Set())
    setRankOperations(new Map())
  }, [treeIdentity])

  const context: CardContext = {
    selectedId,
    getProgress,
    onSelect,
    onToggleDone,
    nodeMap,
    parents,
    path,
    normalizedQuery,
  }
  const researchCount = tree.nodes.filter(isResearchTreeVehicle).length
  const specialCount = tree.nodes.filter((vehicle) => vehicle.type !== 'tree').length

  function toggleRank(rank: number) {
    setCollapsedRanks((current) => toggledSet(current, rank))
  }

  function toggleFolder(vehicleId: number) {
    setOpenFolders((current) => toggledSet(current, vehicleId))
  }

  return (
    <section className="tree-shell wt-tree" aria-label="Research tree">
      <div className="tree-heading">
        <div>
          <div className="eyebrow">Research tree</div>
          <h2>Vehicle research tree</h2>
          {tree.meta?.source_version && <p className="tree-source">Datamine {tree.meta.source_version}</p>}
        </div>
        <div className="tree-heading-tools">
          <div className="tree-legend">
            <span><i className="legend-dot path" /> target route</span>
            <span><i className="legend-dot done" /> unlocked</span>
            <span><i className="legend-dot folder" /> folder</span>
          </div>
          <div className="rank-actions" aria-label="Rank display controls">
            <button type="button" onClick={() => setCollapsedRanks(new Set())}>Expand all</button>
            <button type="button" onClick={() => setCollapsedRanks(new Set(layout.ranks.map((rank) => rank.rank)))}>Collapse all</button>
          </div>
        </div>
      </div>

      <div
        className="tree-column-headings"
        style={{
          '--line-count': Math.max(1, layout.columns.length),
          '--research-columns': layout.researchColumnCount,
          '--special-columns': Math.max(0, layout.columns.length - layout.researchColumnCount),
        } as CSSProperties}
      >
        <span className="research-columns-label">Research tree <b>{researchCount}</b></span>
        {layout.researchColumnCount < layout.columns.length && (
          <span className="special-columns-label">Premium &amp; special <b>{specialCount}</b></span>
        )}
      </div>

      <div className="rank-list" aria-label="Vehicle ranks">
        {layout.ranks.map((rank) => {
          const rankMatches = rank.vehicles.some((vehicle) => vehicleMatches(vehicle, normalizedQuery))
          const effectiveCollapsed = normalizedQuery ? !rankMatches : collapsedRanks.has(rank.rank)
          const researchVehicles = rank.vehicles.filter(isResearchTreeVehicle)
          const researchTargets = rank.vehicles.filter(isResearchTarget)
          const doneCount = researchVehicles.filter((vehicle) => isVehicleComplete(vehicle, getProgress(vehicle.id))).length
          const unlockOperation = buildRankUnlockOperation(researchTargets, getProgress)
          const savedOperation = rankOperations.get(rank.rank)
          const canUndo = Boolean(savedOperation && canUndoRankUnlock(savedOperation, getProgress))
          const action = canUndo ? 'undo' : unlockOperation.unlock.length ? 'unlock' : 'reset'
          const completion = researchVehicles.length ? (doneCount / researchVehicles.length) * 100 : 0
          const contentId = `research-rank-${rank.rank}`
          return (
            <section
              className={`research-rank ${rankMatches ? '' : 'has-no-match'}`}
              key={rank.rank}
              aria-labelledby={`rank-label-${rank.rank}`}
            >
              <h3 className="sr-only" id={`rank-label-${rank.rank}`}>Rank {toRoman(rank.rank)}</h3>
              <div className="rank-header">
                <button
                  className="rank-toggle"
                  type="button"
                  aria-expanded={!effectiveCollapsed}
                  aria-controls={contentId}
                  onClick={() => toggleRank(rank.rank)}
                >
                  <span className="rank-name"><small>RANK</small><strong>{toRoman(rank.rank)}</strong></span>
                  <span className="rank-summary">
                    <b>{vehicleCountLabel(rank.vehicles.length)}</b>
                    <small>{doneCount}/{researchVehicles.length} tree vehicles unlocked</small>
                  </span>
                  <span className="rank-progress" aria-hidden="true"><i style={{ width: `${completion}%` }} /></span>
                  <i className="rank-chevron" aria-hidden="true" />
                </button>
                {researchTargets.length > 0 && (
                  <button
                    className={`rank-complete ${action === 'unlock' ? '' : 'is-reverse'}`}
                    type="button"
                    onClick={() => {
                      if (canUndo && savedOperation) {
                        onUpdateRank(savedOperation.undo)
                        setRankOperations((current) => withoutMapEntry(current, rank.rank))
                        return
                      }
                      if (unlockOperation.unlock.length) {
                        const count = unlockOperation.unlock.length
                        const confirmed = window.confirm(
                          `Mark ${count} remaining ${count === 1 ? 'vehicle' : 'vehicles'} in Rank ${toRoman(rank.rank)} as unlocked?`,
                        )
                        if (!confirmed) return
                        setRankOperations((current) => new Map(current).set(rank.rank, unlockOperation))
                        onUpdateRank(unlockOperation.unlock)
                        return
                      }
                      const confirmed = window.confirm(
                        `Reset research progress for all ${researchTargets.length} vehicles in Rank ${toRoman(rank.rank)}?`,
                      )
                      if (!confirmed) return
                      setRankOperations((current) => withoutMapEntry(current, rank.rank))
                      onUpdateRank(rankResetUpdates(researchTargets))
                    }}
                  >
                    {action === 'undo' ? 'Undo unlock' : action === 'unlock' ? 'Unlock rank' : 'Reset rank'}
                  </button>
                )}
              </div>

              {!effectiveCollapsed && (
                <div
                  className="rank-board"
                  id={contentId}
                  style={{
                    '--line-count': Math.max(1, layout.columns.length),
                    '--research-columns': layout.researchColumnCount,
                  } as CSSProperties}
                >
                  {rank.lanes.map((lane, laneIndex) => (
                    <div
                      className={`research-lane ${laneIndex === layout.researchColumnCount ? 'starts-special' : ''}`}
                      data-line={String(laneIndex + 1).padStart(2, '0')}
                      key={lane.column}
                    >
                      {lane.groups.map((group, groupIndex) => {
                        const priorIds = new Set(
                          lane.groups.slice(0, groupIndex).flatMap((item) => item.vehicles.map((vehicle) => vehicle.id)),
                        )
                        const linkedInsideRank = group.vehicles.some((vehicle) => (
                          (parents.get(vehicle.id) || []).some((parentId) => priorIds.has(parentId))
                        ))
                        const linkedFromPriorRank = group.vehicles.some((vehicle) => (
                          (parents.get(vehicle.id) || []).some((parentId) => {
                            const parent = nodeMap.get(parentId)
                            return parent && parent.rank < rank.rank && (parent.tree_column ?? 0) === lane.column
                          })
                        ))
                        return (
                          <VehicleGroupView
                            {...context}
                            group={group}
                            isSpecialColumn={laneIndex >= layout.researchColumnCount}
                            isLinked={linkedInsideRank || linkedFromPriorRank}
                            isOpen={openFolders.has(group.root.id)}
                            key={group.root.id}
                            onToggleFolder={() => toggleFolder(group.root.id)}
                          />
                        )
                      })}
                    </div>
                  ))}
                </div>
              )}
            </section>
          )
        })}
      </div>
    </section>
  )
}

type GroupProps = CardContext & {
  group: VehicleGroup
  isSpecialColumn: boolean
  isLinked: boolean
  isOpen: boolean
  onToggleFolder: () => void
}

function VehicleGroupView(props: GroupProps) {
  const { group } = props
  const selectedChild = group.children.some((vehicle) => vehicle.id === props.selectedId)
  const matchingChild = Boolean(props.normalizedQuery) && group.children.some(
    (vehicle) => vehicleMatches(vehicle, props.normalizedQuery),
  )
  const effectiveOpen = props.isOpen || selectedChild || matchingChild
  const groupOnPath = group.vehicles.some((vehicle) => props.path.has(vehicle.id))
  const doneCount = group.vehicles.filter((vehicle) => isVehicleComplete(vehicle, props.getProgress(vehicle.id))).length

  return (
    <div className={`vehicle-group ${props.isLinked ? 'has-connector' : ''} ${groupOnPath ? 'is-path' : ''}`}>
      <div className={group.children.length && !effectiveOpen ? 'folder-stack' : ''}>
        <VehicleCard
          {...props}
          compact={props.isSpecialColumn}
          folderCount={group.children.length || undefined}
          vehicle={group.root}
        />
      </div>
      {group.children.length > 0 && (
        <>
          <button
            className="folder-toggle"
            type="button"
            aria-expanded={effectiveOpen}
            aria-controls={`vehicle-folder-${group.root.id}`}
            onClick={props.onToggleFolder}
          >
            <i className="folder-icon" aria-hidden="true" />
            <span>
              <b>{group.children.length} grouped {group.children.length === 1 ? 'vehicle' : 'vehicles'}</b>
              <small>{doneCount}/{group.vehicles.length} unlocked</small>
            </span>
            <i className="folder-chevron" aria-hidden="true" />
          </button>
          {effectiveOpen && (
            <div className="folder-drawer" id={`vehicle-folder-${group.root.id}`}>
              {group.children.map((vehicle) => (
                <VehicleCard {...props} compact folderChild vehicle={vehicle} key={vehicle.id} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

type VehicleCardProps = CardContext & {
  vehicle: Vehicle
  compact?: boolean
  folderChild?: boolean
  folderCount?: number
}

const VehicleCard = memo(function VehicleCard({
  vehicle,
  compact = false,
  folderChild = false,
  folderCount,
  selectedId,
  getProgress,
  onSelect,
  onToggleDone,
  nodeMap,
  parents,
  path,
  normalizedQuery,
}: VehicleCardProps) {
  const progress = getProgress(vehicle.id)
  const total = vehicle.rp_cost || 0
  const reserve = isReserveVehicle(vehicle)
  const researchable = isResearchTarget(vehicle)
  const done = isVehicleComplete(vehicle, progress)
  const required = [...new Set(parents.get(vehicle.id) || [])]
  const locked = researchable && required.some((id) => {
    const parent = nodeMap.get(id)
    return parent ? !isVehicleComplete(parent, getProgress(id)) : false
  })
  const requiredNames = required.map((id) => nodeMap.get(id)?.name).filter(Boolean)
  const special = vehicle.type !== 'tree'
  const matches = vehicleMatches(vehicle, normalizedQuery)
  const progressPercent = total ? Math.min(100, ((progress.rp || 0) / total) * 100) : 0
  const status = reserve
    ? 'RESERVE · UNLOCKED'
    : special
      ? availabilityLabel(vehicle).toUpperCase()
      : !researchable
        ? 'NO RP COST'
        : done
          ? 'UNLOCKED'
          : locked
            ? 'LOCKED'
            : 'RESEARCH'

  return (
    <article
      className={[
        'vehicle-card',
        compact ? 'is-compact' : '',
        folderChild ? 'is-folder-child' : '',
        special ? 'is-special' : '',
        selectedId === vehicle.id ? 'is-selected' : '',
        path.has(vehicle.id) ? 'is-path' : '',
        done ? 'is-done' : '',
        matches ? '' : 'is-dimmed',
      ].join(' ')}
      title={vehicle.name}
    >
      <button
        className="vehicle-main"
        type="button"
        aria-current={selectedId === vehicle.id ? 'true' : undefined}
        onClick={() => onSelect(vehicle)}
      >
        <span className="vehicle-kicker">{status}{folderCount ? ` · FOLDER ×${folderCount}` : ''}</span>
        <span className="vehicle-title-row">
          <i className={`vehicle-silhouette is-${vehicle.class}`} aria-hidden="true" />
          <strong>{vehicle.name}</strong>
        </span>
        <span className="vehicle-meta">
          <b>BR {battleRating(vehicle) ?? '—'}</b>
          <span>
            {reserve
              ? 'Starting vehicle'
              : special
                ? `×${formatMultiplier(vehicle.rp_multiplier)} RP`
                : `${formatRp(total)} RP`}
          </span>
        </span>
        {special && <small>{acquisitionSummary(vehicle)}</small>}
        {!special && requiredNames.length > 0 && <small>Requires {requiredNames.join(', ')}</small>}
        <span
          className="progress-track"
          role="progressbar"
          aria-label={`${vehicle.name} progress`}
          aria-valuemin={0}
          aria-valuemax={total || 100}
          aria-valuenow={total ? Math.min(total, progress.rp || 0) : done ? 100 : 0}
        >
          <i style={{ width: `${done && !total ? 100 : progressPercent}%` }} />
        </span>
      </button>
      {researchable && (
        <button
          className="done-toggle"
          type="button"
          aria-label={done ? `Mark ${vehicle.name} as incomplete` : `Mark ${vehicle.name} as complete`}
          aria-pressed={done}
          onClick={() => onToggleDone(vehicle, !done)}
        >
          {done ? '✓' : ''}
        </button>
      )}
    </article>
  )
}, sameVehicleCardProps)

function sameVehicleCardProps(previous: VehicleCardProps, next: VehicleCardProps): boolean {
  if (
    previous.vehicle !== next.vehicle
    || previous.compact !== next.compact
    || previous.folderChild !== next.folderChild
    || previous.folderCount !== next.folderCount
    || previous.normalizedQuery !== next.normalizedQuery
    || previous.nodeMap !== next.nodeMap
    || previous.parents !== next.parents
    || previous.onSelect !== next.onSelect
    || previous.onToggleDone !== next.onToggleDone
  ) return false

  const vehicleId = previous.vehicle.id
  if ((previous.selectedId === vehicleId) !== (next.selectedId === vehicleId)) return false
  if (previous.path.has(vehicleId) !== next.path.has(vehicleId)) return false

  const relevantIds = [vehicleId, ...(previous.parents.get(vehicleId) || [])]
  return relevantIds.every((id) => {
    const before = previous.getProgress(id)
    const after = next.getProgress(id)
    return (before.rp || 0) === (after.rp || 0) && Boolean(before.done) === Boolean(after.done)
  })
}

export function buildParentMap(tree: TreeResponse): Map<number, number[]> {
  const result = new Map<number, number[]>()
  const addParent = (child: number, parent: number) => {
    result.set(child, [...new Set([...(result.get(child) || []), parent])])
  }
  tree.edges.forEach((edge) => addParent(edge.child, edge.parent))
  tree.nodes.forEach((node) => {
    if (node.folder_of) addParent(node.id, node.folder_of)
  })
  return result
}

export function collectAncestorIds(selectedId: number | null, parents: Map<number, number[]>): Set<number> {
  const result = new Set<number>()
  const pending = selectedId ? [selectedId] : []
  while (pending.length) {
    const id = pending.pop()!
    if (result.has(id)) continue
    result.add(id)
    pending.push(...(parents.get(id) || []))
  }
  return result
}

function vehicleMatches(vehicle: Vehicle, normalizedQuery: string): boolean {
  return !normalizedQuery || vehicle.name.toLocaleLowerCase('en').includes(normalizedQuery)
}

function toggledSet(values: Set<number>, value: number): Set<number> {
  const result = new Set(values)
  if (result.has(value)) result.delete(value)
  else result.add(value)
  return result
}

function withoutMapEntry<T>(values: Map<number, T>, key: number): Map<number, T> {
  const result = new Map(values)
  result.delete(key)
  return result
}
