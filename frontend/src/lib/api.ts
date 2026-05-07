import type {
  CostRollup,
  CostTopSpender,
  EvalExperimentMapping,
  EvalRun,
  EvalSummary,
  FeedbackEvent,
  HealthStatus,
  ResourceRollupItem,
  ResourceUsage,
  SpaceListItem,
  SpaceSummary,
  TopQuery,
  UsageRollup,
} from '@/types/api'

const API_BASE = '/api'
const DEFAULT_TIMEOUT = 30_000

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function fetchJson<T>(
  path: string,
  init: RequestInit = {},
  timeout = DEFAULT_TIMEOUT,
): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(init.headers || {}),
      },
    })
    if (!res.ok) {
      let detail: unknown = null
      try {
        detail = await res.json()
      } catch {
        detail = await res.text()
      }
      throw new ApiError(`${res.status} ${res.statusText}`, res.status, detail)
    }
    if (res.status === 204) return undefined as T
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

// ── Spaces ──────────────────────────────────────────────────────────────────

export const listSpaces = () => fetchJson<SpaceListItem[]>('/spaces')

export const getSpace = (spaceId: string) =>
  fetchJson<SpaceSummary>(`/spaces/${spaceId}`)

export const refreshSpaces = () =>
  fetchJson<{ refreshed: number }>('/spaces/refresh', { method: 'POST' })

// ── Cost ────────────────────────────────────────────────────────────────────

export const getSpaceCost = (spaceId: string, days = 7) =>
  fetchJson<CostRollup>(`/spaces/${spaceId}/cost?days=${days}`)

export const getTopSpenders = (days = 7, limit = 10) =>
  fetchJson<CostTopSpender[]>(`/cost/top?days=${days}&limit=${limit}`)

export const getTopExpensiveQueries = (spaceId: string, days = 7, limit = 20) =>
  fetchJson<TopQuery[]>(
    `/spaces/${spaceId}/cost/top-queries?days=${days}&limit=${limit}`,
  )

// ── Usage ───────────────────────────────────────────────────────────────────

export const getSpaceUsage = (spaceId: string, days = 30) =>
  fetchJson<UsageRollup>(`/spaces/${spaceId}/usage?days=${days}`)

export const getSpaceFeedback = (spaceId: string, days = 30, limit = 200) =>
  fetchJson<FeedbackEvent[]>(
    `/spaces/${spaceId}/feedback?days=${days}&limit=${limit}`,
  )

// ── Resources ───────────────────────────────────────────────────────────────

export const getSpaceResources = (spaceId: string, days = 30) =>
  fetchJson<ResourceUsage[]>(`/spaces/${spaceId}/resources?days=${days}`)

export const getResourceRollup = (days = 30, limit = 50) =>
  fetchJson<ResourceRollupItem[]>(`/resources/rollup?days=${days}&limit=${limit}`)

export const getSpacesUsingResource = (fullName: string, days = 30) =>
  fetchJson<string[]>(
    `/resources/spaces?full_name=${encodeURIComponent(fullName)}&days=${days}`,
  )

// ── Evals ───────────────────────────────────────────────────────────────────

export const getSpaceEvals = (spaceId: string) =>
  fetchJson<EvalSummary>(`/spaces/${spaceId}/evals`)

export const getEvalRun = (runId: string) =>
  fetchJson<EvalRun>(`/evals/runs/${runId}`)

// ── Settings ────────────────────────────────────────────────────────────────

export const getHealth = () => fetchJson<HealthStatus>('/settings/health')

export const getEvalMapping = (spaceId: string) =>
  fetchJson<EvalExperimentMapping | Record<string, never>>(
    `/settings/eval-mapping/${spaceId}`,
  )

export const setEvalMapping = (spaceId: string, experimentId: string) =>
  fetchJson<EvalExperimentMapping>(`/settings/eval-mapping/${spaceId}`, {
    method: 'POST',
    body: JSON.stringify({ experiment_id: experimentId }),
  })

export const deleteEvalMapping = (spaceId: string) =>
  fetchJson<{ deleted: string }>(`/settings/eval-mapping/${spaceId}`, {
    method: 'DELETE',
  })

export const refreshConversationCache = () =>
  fetchJson<{ queued: number }>('/settings/cache/refresh', { method: 'POST' })

// ── Auth ────────────────────────────────────────────────────────────────────

export const getCurrentUser = () =>
  fetchJson<{ email: string; is_admin: boolean; auth_source: string }>('/auth/me')
