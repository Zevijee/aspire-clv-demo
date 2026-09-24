const base = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
const authBase = `${base}/api/v1/auth`

export type Session = { username: string | null }

/** Dispatched when the session has ended and refreshing could not renew it. */
export const SIGNED_OUT_EVENT = 'clearview:signed-out'

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

let refreshing: Promise<Session | null> | null = null

/** Renew the access cookie. Null when the refresh token is gone or rejected.
 *
 * Shared while in flight: a report page fires several requests at once, and
 * when the access cookie lapses they all fail together. One refresh serves them
 * all; separate ones would present the same token repeatedly.
 */
export function refreshSession(): Promise<Session | null> {
  refreshing ??= send('/refresh', { method: 'POST' })
    .then(session => session.username ? session : null, () => null)
    .finally(() => { refreshing = null })
  return refreshing
}

/** fetch for report data: on a 401, refresh once and retry.
 *
 * If the refresh fails the session is over, so the sign-in gate is told and the
 * original 401 is returned for the caller's own error handling.
 */
export async function authorizedFetch(url: string, init?: RequestInit): Promise<Response> {
  const request = { ...init, credentials: 'include' as const }
  const response = await fetch(url, request)
  if (response.status !== 401) return response
  const session = await refreshSession()
  if (!session) {
    window.dispatchEvent(new CustomEvent(SIGNED_OUT_EVENT))
    return response
  }
  return fetch(url, request)
}
