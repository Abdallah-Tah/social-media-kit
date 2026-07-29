import type {
  AnalyticsSnapshot,
  Automation,
  AutomationLog,
  Campaign,
  CampaignAnalytics,
  ContentDraft,
  CreateDraftResponse,
  FeedItem,
  FeedSnapshot,
  GenerateBriefResponse,
  IntelligenceCard,
  IntelligenceFilters,
  IntelligenceSourceConfig,
  MutationResult,
  PlatformConnection,
  RunIntelligenceResponse,
  Snapshot,
  SnapshotSummary,
  SocialDraft,
  Stage7dStatus,
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

  getStage7dStatus: () => request<Stage7dStatus>('/editorial/stage7d-status'),

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

  getDraftCover: (draftId: string) =>
    request<{ ok: boolean; cover_image_url: string; exists: boolean; styles: string[]; error?: string }>(
      `/drafts/${draftId}/cover`
    ),

  regenerateCover: (draftId: string, style: string) =>
    request<{ ok: boolean; cover_image_url?: string; style?: string; error?: string }>(
      `/drafts/${draftId}/cover`,
      { method: 'POST', body: JSON.stringify({ style }) }
    ),

  rewriteDraft: (draftId: string, mode: 'shorter' | 'hook' | 'technical' | 'casual') =>
    request<{ ok: boolean; body?: string; mode?: string; error?: string }>(
      `/drafts/${draftId}/rewrite`,
      { method: 'POST', body: JSON.stringify({ mode }) }
    ),

  retrySocialDraft: (draftId: string) =>
    request<{ ok: boolean; draft?: SocialDraft; error?: string }>(
      `/social_drafts/${draftId}/retry`,
      { method: 'POST', body: JSON.stringify({}) }
    ),

  getConnections: () =>
    request<{ ok: boolean; connections: PlatformConnection[] }>('/connections'),

  getSourceConfig: () =>
    request<{ ok: boolean; config: IntelligenceSourceConfig }>('/intelligence/config'),

  updateSourceConfig: (fields: Partial<IntelligenceSourceConfig>) =>
    request<{ ok: boolean; config: IntelligenceSourceConfig }>('/intelligence/config', {
      method: 'POST',
      body: JSON.stringify(fields),
    }),

  getCampaignAnalytics: () =>
    request<{ ok: boolean; campaigns: CampaignAnalytics[] }>('/analytics/campaigns'),

  getFeed: (snapshot?: string) => {
    const qs = snapshot ? `?snapshot=${encodeURIComponent(snapshot)}` : ''
    return request<FeedSnapshot & { ok: boolean }>(`/feed${qs}`)
  },

  runFeed: (dryRun = true, limit = 20) =>
    request<{ ok: boolean; count: number; items: FeedItem[]; saved: string | null; dry_run: boolean; error?: string }>(
      '/feed/run',
      { method: 'POST', body: JSON.stringify({ dry_run: dryRun, limit }) }
    ),

  publishFeedItem: (item: FeedItem, platforms: string[], dryRun = true) =>
    request<{ ok: boolean; results: Record<string, { ok: boolean; dry_run?: boolean; draft_id?: string; published_url?: string; error?: string }>; dry_run: boolean; error?: string }>(
      '/feed/publish',
      { method: 'POST', body: JSON.stringify({ item, platforms, dry_run: dryRun }) }
    ),

  runFeedPipeline: (item: FeedItem, dryRun = true, profile = 'default') =>
    request<{ ok: boolean; dry_run: boolean; topic?: string; url?: string; stdout?: string; stderr?: string; error?: string; message?: string }>(
      '/feed/pipeline',
      { method: 'POST', body: JSON.stringify({ item, dry_run: dryRun, profile }) }
    ),

  postFeedYouTube: async (item: FeedItem, mode: 'short' | 'video', dryRun = true, force = false) => {
    type YtResult = { ok: boolean; dry_run?: boolean; mode?: string; url?: string; video?: string; video_url?: string; title?: string; message?: string; error?: string }
    // The render/upload runs as an async job on the server (it can take
    // minutes; proxies cut long requests at ~120s). Start it, then poll.
    const start = await request<{ ok: boolean; job_id?: string; status?: string; error?: string } & YtResult>(
      '/feed/youtube',
      { method: 'POST', body: JSON.stringify({ item, mode, dry_run: dryRun, force }) }
    )
    if (!start.ok || !start.job_id) return start as YtResult
    const deadline = Date.now() + 30 * 60 * 1000 // 30 min cap
    for (;;) {
      await new Promise((r) => setTimeout(r, 5000))
      const st = await request<{ ok: boolean; status?: string; result?: YtResult; error?: string }>(
        `/feed/youtube/status?job=${start.job_id}`
      )
      if (!st.ok) return { ok: false, error: st.error || 'job status failed' }
      if (st.status === 'done') return st.result ?? { ok: false, error: 'job returned no result' }
      if (Date.now() > deadline) return { ok: false, error: 'timed out waiting for render job (30 min)' }
    }
  },

  generateFeedCover: (item: FeedItem) =>
    request<{ ok: boolean; cover_url?: string; path?: string; provider?: string; error?: string }>(
      '/feed/generate',
      { method: 'POST', body: JSON.stringify({ item, what: 'cover' }) }
    ),

  generateFeedShort: (item: FeedItem) =>
    request<{
      ok: boolean
      plan_path?: string
      hook?: string
      voiceover?: string
      captions?: string[]
      scenes?: Array<{ kind?: string; title?: string; caption?: string }>
      publish_metadata?: Record<string, unknown>
      error?: string
    }>('/feed/generate', { method: 'POST', body: JSON.stringify({ item, what: 'short' }) }),

  saveConnectionSecrets: (values: Record<string, string>) =>
    request<{ ok: boolean; saved?: string[]; rejected?: string[]; connections?: PlatformConnection[]; error?: string }>(
      '/connections/save',
      { method: 'POST', body: JSON.stringify({ values }) }
    ),
}
