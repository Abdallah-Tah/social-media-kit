import type {
  AnalyticsSnapshot,
  CreateDraftResponse,
  GenerateBriefResponse,
  IntelligenceCard,
  IntelligenceFilters,
  RunIntelligenceResponse,
  Snapshot,
} from './models'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`
  const resp = await fetch(url, {
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => 'Unknown error')
    throw new Error(`HTTP ${resp.status}: ${text}`)
  }
  return (await resp.json()) as T
}

export const api = {
  getState: () => request<Record<string, unknown>>('/state'),

  getAnalytics: (days?: number | null, platform?: string | null) => {
    const params = new URLSearchParams()
    if (days !== undefined && days !== null) params.set('days', String(days))
    if (platform) params.set('platform', platform)
    return request<AnalyticsSnapshot>(`/analytics?${params.toString()}`)
  },

  syncAnalytics: (from?: string, to?: string) =>
    request<{ ok: boolean; synced: number; error?: string }>('/analytics/sync', {
      method: 'POST',
      body: JSON.stringify({ from, to }),
    }),

  runIntelligence: (filters: IntelligenceFilters) => {
    const params = new URLSearchParams()
    if (filters.topic) params.set('topic', filters.topic)
    params.set('include_seen', String(filters.include_seen ?? false))
    params.set('brief', 'true')
    return request<RunIntelligenceResponse>(`/intelligence/run?${params.toString()}`)
  },

  getSnapshots: () => request<{ snapshots: string[] }>('/intelligence/snapshots'),

  getSnapshot: (name: string) => request<Snapshot>(`/intelligence/snapshot?name=${encodeURIComponent(name)}`),

  generateBrief: (cardId: number) =>
    request<GenerateBriefResponse>('/intelligence/brief', {
      method: 'POST',
      body: JSON.stringify({ rank: cardId }),
    }),

  generateBriefs: (ranks: number[]) =>
    request<{ ok: boolean; briefs: Array<{ rank: number; brief: IntelligenceCard['brief'] }>; error?: string }>(
      '/intelligence/briefs',
      {
        method: 'POST',
        body: JSON.stringify({ ranks }),
      }
    ),

  createDraftFromBrief: (rank: number, brief: Record<string, unknown>) =>
    request<CreateDraftResponse>('/intelligence/draft', {
      method: 'POST',
      body: JSON.stringify({ rank, brief }),
    }),

  saveSnapshot: () =>
    request<{ ok: boolean; path?: string; error?: string }>('/intelligence/save', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  exportIntelligence: (format: 'csv' | 'json') => {
    window.open(`${API_BASE}/intelligence/export?format=${format}`, '_blank')
  },

  getDrafts: () => request<unknown[]>('/drafts'),
  getDraft: (id: string) => request<Record<string, unknown>>(`/drafts/${id}`),
  saveDraft: (id: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/drafts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

  getSocialDrafts: () => request<unknown[]>('/social_drafts'),
  publishSocialDrafts: (ids: string[], dryRun = true) =>
    request<Record<string, unknown>>('/social_drafts/publish', {
      method: 'POST',
      body: JSON.stringify({ ids, dry_run: dryRun }),
    }),
  scheduleSocialDrafts: (ids: string[], scheduledAt: string) =>
    request<Record<string, unknown>>('/social_drafts/schedule', {
      method: 'POST',
      body: JSON.stringify({ ids, scheduled_at: scheduledAt }),
    }),

  publishBlog: (id: string) =>
    request<Record<string, unknown>>(`/drafts/${id}/publish`, { method: 'POST' }),

  createSocialDrafts: (draftId: string, platforms: string[]) =>
    request<Record<string, unknown>>(`/drafts/${draftId}/social`, {
      method: 'POST',
      body: JSON.stringify({ platforms }),
    }),

  runAgent: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/run', { method: 'POST', body: JSON.stringify(body) }),
}
