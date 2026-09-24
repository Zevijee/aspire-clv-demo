const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
const authBase = `${base}/api/v1/auth`

export type Session = { username: string | null }

/** Every call sends the session cookie.
 *
 * `credentials: 'include'` is required even same-origin here, because the local
 * dev server and the API are different ports and the browser treats that as
 * cross-origin. The API allows credentials for exactly this reason, which is
 * also why its CORS origin list is load bearing rather than advisory.
 */
async function send(path: string, init?: RequestInit): Promise<Session> {
  const response = await fetch(`${authBase}${path}`, { credentials: 'include', ...init })
  const body = await response.json().catch(() => ({})) as Session & { detail?: string }
  if (!response.ok) {
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Sign in could not complete.')
  }
  return body
}

export function getSession(signal?: AbortSignal) {
  return send('/session', { signal })
}

export function login(username: string, password: string) {
  return send('/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
}

export function logout() {
  return send('/logout', { method: 'POST' })
}
