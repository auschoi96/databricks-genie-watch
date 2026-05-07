/** Module-scoped result cache.
 *
 *  Stores already-resolved API responses keyed by an arbitrary string. Pages
 *  use `useCachedFetch(key, () => api.fooBar(...))` to read from cache before
 *  hitting the network. The cache survives page/route changes but not page
 *  reloads — that's intentional, since stale data should never persist past
 *  a hard refresh.
 *
 *  Refresh buttons call `invalidate(prefix)` to drop matching keys, then
 *  re-fetch on the next render.
 */

import { useEffect, useState } from 'react'

const _cache = new Map<string, unknown>()

export function getCached<T>(key: string): T | undefined {
  return _cache.get(key) as T | undefined
}

export function putCached<T>(key: string, value: T): void {
  _cache.set(key, value)
}

export function invalidate(prefix?: string): void {
  if (!prefix) {
    _cache.clear()
    return
  }
  for (const k of [..._cache.keys()]) {
    if (k.startsWith(prefix)) _cache.delete(k)
  }
}

/** React hook: load data via `fetcher` if not in cache, else return cached. */
export function useCachedFetch<T>(
  key: string,
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
): { data: T | undefined; error: string | null; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | undefined>(() => getCached<T>(key))
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<boolean>(() => getCached<T>(key) === undefined)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const cached = getCached<T>(key)
    if (cached !== undefined && tick === 0) {
      setData(cached)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    fetcher()
      .then(v => {
        if (cancelled) return
        putCached(key, v)
        setData(v)
        setLoading(false)
      })
      .catch(e => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : String(e))
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick, ...deps])

  function reload() {
    invalidate(key)
    setTick(t => t + 1)
  }

  return { data, error, loading, reload }
}
