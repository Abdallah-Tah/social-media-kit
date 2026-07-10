import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from './client'

describe('API client error handling', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('throws on HTTP error with status text', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response('Internal Server Error', { status: 500 })
    )

    await expect(api.getState()).rejects.toThrow('HTTP 500')
  })

  it('returns parsed JSON on success', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ profiles: [], history: [] }), { status: 200 })
    )

    const data = await api.getState()
    expect(data).toEqual({ profiles: [], history: [] })
  })

  it('includes query params for analytics', async () => {
    let calledUrl = ''
    vi.mocked(globalThis.fetch).mockImplementationOnce((url) => {
      calledUrl = String(url)
      return Promise.resolve(new Response('{}', { status: 200 }))
    })

    await api.getAnalytics(30, 'linkedin')
    expect(calledUrl).toContain('/api/analytics?days=30')
    expect(calledUrl).toContain('platform=linkedin')
  })

  it('does not request intelligence briefs by default', async () => {
    let calledUrl = ''
    vi.mocked(globalThis.fetch).mockImplementationOnce((url) => {
      calledUrl = String(url)
      return Promise.resolve(new Response(JSON.stringify({ ok: true, cards: [] }), { status: 200 }))
    })

    await api.runIntelligence({ topic: 'AI', include_seen: false, min_score: 80, trend: 'exploding' })
    expect(calledUrl).toContain('/api/intelligence/run?')
    expect(calledUrl).toContain('topic=AI')
    expect(calledUrl).toContain('include_seen=false')
    expect(calledUrl).not.toContain('brief=')
    expect(calledUrl).not.toContain('min_score=')
    expect(calledUrl).not.toContain('trend=')
  })
})
