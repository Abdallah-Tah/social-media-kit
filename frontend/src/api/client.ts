import type {
  AnalyticsSnapshot,
  Automation,
  AutomationLog,
  Campaign,
  ContentDraft,
  CreateDraftResponse,
  GenerateBriefResponse,
  IntelligenceCard,
  IntelligenceFilters,
  MutationResult,
  RunIntelligenceResponse,
  Snapshot,
  SnapshotSummary,
  SocialDraft,
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
    return request<RunIntelligenceResponse>(`/intelligence/run?${params.toString()}`)
  },

  getSnapshots: () => request<{ snapshots: SnapshotSummary[] }>('/intelligence/snapshots'),

  getSnapshot: (name: string) => request<Snapshot>(`/intelligence/snapshot?name=${encodeURIComponent(name)}`),

  generateBrief: (card: IntelligenceCard) =>
    request<GenerateBriefResponse>('/intelligence/brief', {
      method: 'POST',
      body: JSON.stringify({ card }),
    }),

  generateBriefs: (cards: IntelligenceCard[]) =>
    request<{ ok: boolean; briefs: Array<{ rank: number; brief: IntelligenceCard['brief'] }>; error?: string }>(
      '/intelligence/briefs',
      {
        method: 'POST',
        body: JSON.stringify({ cards }),
      }
    ),

  createDraftFromBrief: (card: IntelligenceCard, brief: Record<string, unknown>) =>
    request<CreateDraftResponse>('/intelligence/draft', {
      method: 'POST',
      body: JSON.stringify({ card, brief }),
    }),

  saveSnapshot: () =>
    request<{ ok: boolean; path?: string; name?: string; error?: string }>('/intelligence/save', {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  exportIntelligence: (format: 'csv' | 'json') => {
    window.open(`${API_BASE}/intelligence/export?format=${format}`, '_blank')
  },

  getDrafts: async () => {
    const data = await request<{ ok: boolean; drafts?: ContentDraft[]; error?: string }>('/drafts')
    return data.drafts || []
  },
  getDraft: (id: string) => request<{ ok: boolean; draft?: ContentDraft; error?: string }>(`/drafts/${id}`),
  saveDraft: (id: string, body: Partial<ContentDraft>) =>
    request<{ ok: boolean; draft?: ContentDraft; error?: string }>(`/drafts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  getSocialDrafts: async () => {
    const data = await request<{ ok: boolean; drafts?: SocialDraft[]; error?: string }>('/social_drafts')
    return data.drafts || []
  },
  getSocialDraft: (id: string) => request<{ ok: boolean; draft?: SocialDraft; error?: string }>(`/social_drafts/${id}`),
  saveSocialDraft: (id: string, body: Partial<SocialDraft>) =>
    request<{ ok: boolean; draft?: SocialDraft; error?: string }>(`/social_drafts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  publishSocialDrafts: (ids: string[], dryRun = true) =>
    request<MutationResult>('/social_drafts/publish', {
      method: 'POST',
      body: JSON.stringify({ ids, dry_run: dryRun }),
    }),
  publishDueSocialDrafts: (dryRun = true) =>
    request<MutationResult>('/social_drafts/publish_due', {
      method: 'POST',
      body: JSON.stringify({ dry_run: dryRun }),
    }),
  scheduleSocialDrafts: (ids: string[], scheduledAt: string) =>
    request<MutationResult>('/social_drafts/schedule', {
      method: 'POST',
      body: JSON.stringify({ ids, scheduled_at: scheduledAt }),
    }),

  publishBlog: (id: string) =>
    request<{ ok: boolean; draft?: ContentDraft; blog_url?: string; error?: string }>(`/drafts/${id}/publish`, { method: 'POST' }),

  createSocialDrafts: (draftId: string, platforms: string[]) =>
    request<{ ok: boolean; drafts?: SocialDraft[]; error?: string }>(`/drafts/${draftId}/social`, {
      method: 'POST',
      body: JSON.stringify({ platforms }),
    }),

  runAgent: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/run', { method: 'POST', body: JSON.stringify(body) }),

  getAutomations: () =>
    request<{ ok: boolean; automations: Automation[] }>('/automations'),

  updateAutomation: (jobId: string, fields: Partial<Pick<Automation, 'enabled' | 'interval_hours' | 'dry_run'>>) =>
    request<{ ok: boolean; automation: Automation; error?: string }>(`/automations/${jobId}`, {
      method: 'PATCH',
      body: JSON.stringify(fields),
    }),

  runAutomationNow: (jobId: string) =>
    request<{ ok: boolean; message?: string; error?: string }>(`/automations/${jobId}/run`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),

  getLogs: (limit = 100) =>
    request<{ ok: boolean; logs: AutomationLog[] }>(`/logs?limit=${limit}`),

  getCampaigns: () =>
    request<{ ok: boolean; campaigns: Campaign[] }>('/campaigns'),

  getCampaign: (id: string) =>
    request<{ ok: boolean; campaign: Campaign }>(`/campaigns/${id}`),

  createCampaign: (card: IntelligenceCard, brief: Record<string, unknown> | null, platforms?: string[]) =>
    request<{ ok: boolean; campaign?: Campaign; error?: string }>('/campaigns', {
      method: 'POST',
      body: JSON.stringify({ card, brief, platforms }),
    }),
}
