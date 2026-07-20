import type { User } from '../types'

type Props = {
  authEnabled: boolean
  user: User | null
  authReady: boolean
  online: boolean
  authOpen: boolean
  onToggleAuth: () => void
  onLogout: () => void
}

export function TopBar({ authEnabled, user, authReady, online, authOpen, onToggleAuth, onLogout }: Props) {
  return (
    <header className="topbar">
      <a className="brand" href={import.meta.env.BASE_URL} aria-label="GrindTracker home">
        <span className="brand-mark" aria-hidden="true">GT</span>
        <span>
          <strong>GrindTracker</strong>
          <small>research command center</small>
        </span>
      </a>

      <div className="topbar-actions">
        <span className={`api-status ${online ? '' : 'is-offline'}`}>
          <i aria-hidden="true" /> API {online ? 'online' : 'offline'}
        </span>
        {!authEnabled ? (
          <span className="local-mode" title="Account synchronization is disabled on this static deployment.">Local progress</span>
        ) : user ? (
          <div className="user-actions">
            <span className="user-badge" title={user.email}>{user.email.slice(0, 1).toUpperCase()}</span>
            <span className="user-email">{user.email}</span>
            <button className="button button-quiet" type="button" onClick={onLogout}>Sign out</button>
          </div>
        ) : (
          <button
            className={`button button-quiet ${authOpen ? 'is-active' : ''}`}
            type="button"
            onClick={onToggleAuth}
            aria-expanded={authOpen}
            disabled={!authReady}
          >
            {authReady ? 'Sign in' : 'Checking…'}
          </button>
        )}
      </div>
    </header>
  )
}
