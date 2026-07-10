const API_BASE = '/api'

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
    return request<Record<string, unknown>>(`/analytics?${params.toString()}`)
  },
  syncAnalytics: (from?: string, to?: string) =>
    request<{ ok: boolean; synced: number; error?: string }>('/analytics/sync', {
      method: 'POST',
      body: JSON.stringify({ from, to }),
    }),
  getIntelligence: (params?: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams()
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v !== undefined) qs.set(k, String(v))
    })
    return request<Record<string, unknown>>(`/intelligence?${qs.toString()}`)
  },
  getDrafts: () => request<unknown[]>('/drafts'),
  getDraft: (id: string) => request<Record<string, unknown>>(`/drafts/${id}`),
  saveDraft: (id: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/drafts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  createDraftFromBrief: (cardId: string, brief: Record<string, unknown>) =>
    request<Record<string, unknown>>('/intelligence/draft', {
      method: 'POST',
      body: JSON.stringify({ card_id: cardId, brief }),
    }),
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
  runAgent: (body: Record<string, unknown>) =>
    request<Record<string, unknown>>('/run', { method: 'POST', body: JSON.stringify(body) }),
  upload: (category: string, name: string, file: Blob) => {
    const form = new FormData()
    form.append('file', file, name)
    return fetch(`${API_BASE}/upload?category=${encodeURIComponent(category)}&name=${encodeURIComponent(name)}`, {
      method: 'POST',
      body: form,
    })
  },
}
