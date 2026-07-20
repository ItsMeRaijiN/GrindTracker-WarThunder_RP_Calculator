import type { Nation, VehicleClass } from '../types'

const classLabels: Record<string, string> = {
  army: 'Ground',
  aviation: 'Aviation',
  helicopter: 'Helicopters',
  coastal: 'Coastal fleet',
  bluewater: 'Bluewater fleet',
}

type Props = {
  nations: Nation[]
  classes: VehicleClass[]
  nation: string
  vehicleClass: string
  query: string
  count: number
  onNationChange: (value: string) => void
  onClassChange: (value: string) => void
  onQueryChange: (value: string) => void
}

export function CommandBar(props: Props) {
  return (
    <section className="command-bar" aria-label="Research tree filters">
      <label className="select-field">
        <span>Nation</span>
        <select value={props.nation} onChange={(event) => props.onNationChange(event.target.value)}>
          {props.nations.map((nation) => <option key={nation.id} value={nation.slug}>{nation.name}</option>)}
        </select>
      </label>

      <div className="class-tabs" role="group" aria-label="Military branch">
        {props.classes.map((item) => (
          <button
            key={item.id}
            type="button"
            className={props.vehicleClass === item.name ? 'is-active' : ''}
            onClick={() => props.onClassChange(item.name)}
          >
            {classLabels[item.name] || item.name}
          </button>
        ))}
      </div>

      <label className="search-field">
        <span className="sr-only">Search vehicles</span>
        <span aria-hidden="true">⌕</span>
        <input
          type="search"
          placeholder="Search vehicles…"
          value={props.query}
          onChange={(event) => props.onQueryChange(event.target.value)}
        />
        <kbd>{props.count}</kbd>
      </label>
    </section>
  )
}
