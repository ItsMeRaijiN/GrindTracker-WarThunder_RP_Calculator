import type { CalcPayload, CascadeResult, EstimateResult, StaticCatalog, TreeResponse } from './types'
import { createCalculator } from './lib/calculator'

let catalogPromise: Promise<StaticCatalog> | null = null
let calculator: ReturnType<typeof createCalculator> | null = null

async function loadCatalog(): Promise<StaticCatalog> {
  if (!catalogPromise) {
    catalogPromise = (async () => {
      const response = await fetch(import.meta.env.BASE_URL + 'data/catalog.json', {
        credentials: 'omit',
        signal: AbortSignal.timeout(20_000),
      })
      if (!response.ok) throw new Error('Could not load the vehicle catalog. Please retry.')
      const catalog = await response.json() as StaticCatalog
      if (catalog.schema_version !== 1 || !Array.isArray(catalog.nodes) || !catalog.nodes.length
        || !Array.isArray(catalog.edges) || !Array.isArray(catalog.trees) || !catalog.trees.length
        || !Array.isArray(catalog.nations) || !catalog.nations.length
        || !Array.isArray(catalog.classes) || !catalog.classes.length) {
        throw new Error('The vehicle catalog is incomplete. Please reload the page.')
      }
      calculator = createCalculator(catalog)
      return catalog
    })().catch((error: unknown) => {
      catalogPromise = null
      throw error
    })
  }
  return catalogPromise
}

function calculate(kind: 'estimate', payload: CalcPayload, signal?: AbortSignal): Promise<EstimateResult>
function calculate(kind: 'cascade', payload: CalcPayload, signal?: AbortSignal): Promise<CascadeResult>
async function calculate(kind: 'estimate' | 'cascade', payload: CalcPayload, signal?: AbortSignal) {
  signal?.throwIfAborted()
  await loadCatalog()
  signal?.throwIfAborted()
  return calculator![kind](payload)
}

export const staticApi = {
  nations: async () => (await loadCatalog()).nations,
  classes: async () => (await loadCatalog()).classes,
  tree: async (nation: string, vehicleClass: string): Promise<TreeResponse> => {
    const catalog = await loadCatalog()
    const nodes = catalog.nodes.filter((vehicle) => vehicle.nation === nation && vehicle.class === vehicleClass)
      .sort((a, b) => (a.tree_column || 0) - (b.tree_column || 0)
        || (a.tree_order || 0) - (b.tree_order || 0) || a.rank - b.rank || a.name.localeCompare(b.name))
    const ids = new Set(nodes.map((vehicle) => vehicle.id))
    return {
      nodes,
      edges: catalog.edges.filter((edge) => ids.has(edge.parent) && ids.has(edge.child)),
      meta: catalog.trees.find((tree) => tree.nation === nation && tree.class === vehicleClass)
        || { nation, class: vehicleClass, vehicle_count: 0 },
    }
  },
  estimate: (payload: CalcPayload, signal?: AbortSignal) => calculate('estimate', payload, signal),
  cascade: (payload: CalcPayload, signal?: AbortSignal) => calculate('cascade', payload, signal),
}
