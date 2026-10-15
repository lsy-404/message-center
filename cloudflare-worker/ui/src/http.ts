// Same-origin JSON requests; a 401 sends the browser back through sign-in.
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...options })
  const type = response.headers.get('content-type') || ''
  const body = type.includes('json') ? await response.json() : null
  if (response.status === 401) {
    window.location.replace('/login')
    throw new Error('access_required')
  }
  if (!response.ok) throw new Error(body?.error || `HTTP ${response.status}`)
  return body as T
}
