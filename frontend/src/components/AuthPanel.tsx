import { useState, type FormEvent } from 'react'

type Props = {
  busy: boolean
  error: string | null
  onSubmit: (mode: 'login' | 'register', email: string, password: string) => Promise<void>
}

export function AuthPanel({ busy, error, onSubmit }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'login' | 'register'>('login')

  async function submit(event: FormEvent) {
    event.preventDefault()
    await onSubmit(mode, email, password)
  }

  return (
    <aside className="auth-panel" aria-label="Authentication">
      <div className="eyebrow">Progress sync</div>
      <h2>{mode === 'login' ? 'Return to your campaign' : 'Create a pilot account'}</h2>
      <p>Progress is also stored locally. An account lets you move it between devices.</p>
      <form onSubmit={submit}>
        <label>
          <span>E-mail</span>
          <input type="email" maxLength={320} autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label>
          <span>Password</span>
          <input
            type="password"
            minLength={mode === 'register' ? 12 : 1}
            maxLength={128}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
          {mode === 'register' && <small>Use at least 12 characters. Password managers are welcome.</small>}
        </label>
        {error && <div className="inline-error" role="alert">{error}</div>}
        <button className="button button-primary" disabled={busy} type="submit">
          {busy ? 'Connecting…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>
      </form>
      <button className="auth-switch" type="button" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
        {mode === 'login' ? 'No account? Create one' : 'Already have an account? Sign in'}
      </button>
    </aside>
  )
}
