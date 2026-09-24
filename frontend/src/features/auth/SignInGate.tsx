import { useCallback, useEffect, useState } from 'react'
import { getSession, login, logout, type Session } from './api'

type State = { status: 'checking' } | { status: 'out'; reason?: string } | { status: 'in'; username: string }

/** Holds the whole application behind a sign-in.
 *
 * The gate is presentation only. The lock is on the API, where every reporting
 * router depends on a session, so hiding the pages is a courtesy rather than
 * the protection -- a request made outside this app still gets 401.
 */
export function SignInGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>({ status: 'checking' })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  const apply = useCallback((session: Session) => {
    setState(session.username ? { status: 'in', username: session.username } : { status: 'out' })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void getSession(controller.signal).then(apply, () => {
      if (!controller.signal.aborted) {
        // A failure here is the API being unreachable, not a rejected password.
        setState({ status: 'out', reason: 'The reporting service could not be reached.' })
      }
    })
    return () => controller.abort()
  }, [apply])

  if (state.status === 'checking') {
    return <div className="sign-in" aria-busy="true"><p className="sign-in__checking">Checking your session…</p></div>
  }

  if (state.status === 'in') {
    return <>
      {children}
      <button type="button" className="sign-in__out" onClick={() => {
        void logout().then(apply, () => setState({ status: 'out' }))
      }}>Sign out {state.username}</button>
    </>
  }

  return (
    <div className="sign-in">
      <form className="sign-in__card" onSubmit={event => {
        event.preventDefault()
        setBusy(true)
        void login(username, password)
          .then(session => { setPassword(''); setShowPassword(false); apply(session) })
          .catch((error: Error) => setState({ status: 'out', reason: error.message }))
          .finally(() => setBusy(false))
      }}>
        <h1 className="sign-in__title">Clearview</h1>
        <p className="sign-in__subtitle">Aspire Health Group reporting</p>
        <label className="sign-in__field">
          <span>Username</span>
          <input name="username" autoComplete="username" required autoFocus
            value={username} onChange={event => setUsername(event.target.value)} />
        </label>
        <label className="sign-in__field">
          <span>Password</span>
          <span className="sign-in__password">
            <input name="password" type={showPassword ? 'text' : 'password'}
              autoComplete="current-password" required
              value={password} onChange={event => setPassword(event.target.value)} />
            {/* A button, not a checkbox, so it never submits the form and never
                becomes a field the browser tries to save. aria-pressed carries
                the state to a screen reader, which the icon alone would not. */}
            <button type="button" className="sign-in__reveal"
              aria-pressed={showPassword}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              onClick={() => setShowPassword(shown => !shown)}>
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </span>
        </label>
        {/* Announced, so the failure is not visible only to people who can see it. */}
        {state.reason && <p className="sign-in__error" role="alert">{state.reason}</p>}
        <button type="submit" className="sign-in__submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
