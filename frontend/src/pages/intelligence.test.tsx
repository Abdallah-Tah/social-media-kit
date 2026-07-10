import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { IntelligencePage } from './intelligence'
import * as client from '@/api/client'
import type { Brief, IntelligenceCard } from '@/api/models'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

function renderPage() {
  const queryClient = makeQueryClient()
  render(
    <QueryClientProvider client={queryClient}>
      <IntelligencePage />
    </QueryClientProvider>
  )
}

function makeBrief(overrides: Partial<Brief> = {}): Brief {
  return {
    content_type: 'blog',
    title: 'Generated AI Agent Brief',
    hook: 'Stop doing X manually',
    angle: 'practical guide',
    key_points: ['agents', 'workflows'],
    call_to_action: 'Try it today',
    ...overrides,
  }
}

function makeCard(overrides: Partial<IntelligenceCard> = {}): IntelligenceCard {
  return {
    rank: 1,
    previously_seen: false,
    cluster: {
      headline: 'AI agents reshape dev workflows',
      summary: 'AI agents are increasingly integrated into developer tooling.',
      sources: ['techcrunch', 'github'],
      urls: ['https://example.com/ai-agents'],
      latest: new Date().toISOString(),
    },
    authority: { final_score: 78, source_trust: 80, recency_score: 75, domain_authority: 70 },
    trend: { direction: 'growing', strength: 0.8, velocity: 1.2, sparkline: [10, 20, 30], age_hours: 12 },
    opportunity: {
      opportunity_score: 82,
      signal: 'strong',
      urgency: 70,
      originality: 65,
      commercial_value: 80,
      authority_boost: 75,
      recommendation: 'blog',
    },
    recommendation: {
      recommendation: 'blog',
      confidence_score: 0.85,
      suggested_angle: 'practical guide',
      suggested_hook: 'Stop doing X manually',
      reason: 'High authority + trending',
    },
    brief: null,
    score_breakdown: [
      { name: 'Authority', score: 78, weight: 0.25 },
      { name: 'Trend', score: 80, weight: 0.25 },
    ],
    platform_fit: [
      { platform: 'linkedin', score: 85, reason: 'B2B audience' },
      { platform: 'youtube', score: 60, reason: 'Dev community' },
    ],
    why_care: {
      summary: 'AI agents are a major shift.',
      bullets: ['High authority sources', 'Growing trend'],
    },
    estimated_reach: 5000,
    estimated_difficulty: 'Medium',
    history_delta: { previous: 75, delta: 7, trend: 'up' },
    story_age: '12h',
    confidence_meter: 85,
    ...overrides,
  }
}

describe('IntelligencePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(client.api, 'getSnapshots').mockResolvedValue({ snapshots: [] })
  })

  function clickRun() {
    fireEvent.click(screen.getByRole('button', { name: /Run Intelligence/i }))
  }

  it('renders fetched opportunities with AI summary', async () => {
    vi.spyOn(client.api, 'runIntelligence').mockResolvedValueOnce({
      ok: true,
      cards: [makeCard({ cluster: { ...makeCard().cluster, headline: 'Fetched Opportunity' } })],
      total: 1,
      filtered: 1,
    })

    renderPage()
    clickRun()

    await waitFor(() => expect(screen.getAllByText('Fetched Opportunity')[0]).toBeInTheDocument())
    expect(screen.getByText('AI Daily Summary')).toBeInTheDocument()
    expect(screen.getAllByText('82')[0]).toBeInTheDocument()
  })

  it('runs intelligence with only server-supported filters', async () => {
    const spy = vi.spyOn(client.api, 'runIntelligence').mockResolvedValue({ ok: true, cards: [], total: 0, filtered: 0 })
    renderPage()

    fireEvent.change(screen.getByPlaceholderText('e.g. AI, Laravel, Raspberry Pi'), { target: { value: 'Laravel' } })
    fireEvent.click(screen.getByLabelText('Include seen stories'))
    fireEvent.click(screen.getByRole('button', { name: /Hot Now/i }))
    clickRun()

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith({ topic: 'Laravel', include_seen: true })
    })
  })

  it('applies quick filters locally', async () => {
    vi.spyOn(client.api, 'runIntelligence').mockResolvedValueOnce({
      ok: true,
      cards: [
        makeCard({ rank: 1, cluster: { ...makeCard().cluster, headline: 'Hot Story' }, opportunity: { ...makeCard().opportunity, opportunity_score: 90 } }),
        makeCard({ rank: 2, cluster: { ...makeCard().cluster, headline: 'Low Story' }, opportunity: { ...makeCard().opportunity, opportunity_score: 40 } }),
      ],
      total: 2,
      filtered: 2,
    })

    renderPage()
    clickRun()
    await waitFor(() => expect(screen.getAllByText('Hot Story')[0]).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Hot Now/i }))
    expect(screen.getAllByText('Hot Story')[0]).toBeInTheDocument()
    expect(screen.queryByText('Low Story')).not.toBeInTheDocument()
  })

  it('generated brief updates the card and Create Draft uses it', async () => {
    const card = makeCard({ brief: null })
    const newBrief = makeBrief({ title: 'Fresh Generated Brief' })
    vi.spyOn(client.api, 'runIntelligence').mockResolvedValueOnce({ ok: true, cards: [card], total: 1, filtered: 1 })
    const briefSpy = vi.spyOn(client.api, 'generateBrief').mockResolvedValue({ ok: true, brief: newBrief })
    const draftSpy = vi.spyOn(client.api, 'createDraftFromBrief').mockResolvedValue({ ok: true, draft_id: 'draft-1' })

    renderPage()
    clickRun()
    await waitFor(() => expect(screen.getAllByText('AI agents reshape dev workflows')[0]).toBeInTheDocument())

    const draftButton = screen.getByRole('button', { name: /Create Draft/i })
    expect(draftButton).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: /Generate Brief/i }))
    await waitFor(() => expect(briefSpy).toHaveBeenCalledWith(card))

    fireEvent.click(screen.getByRole('button', { name: /Details/i }))
    await waitFor(() => expect(screen.getByText('Fresh Generated Brief')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /Create Draft/i }))
    await waitFor(() => expect(draftSpy).toHaveBeenCalledWith(card, newBrief))
  })

  it('shows snapshot panel and loads a snapshot', async () => {
    vi.spyOn(client.api, 'getSnapshots').mockResolvedValue({ snapshots: [{ name: 'latest.json', when: 'today' }] })
    vi.spyOn(client.api, 'getSnapshot').mockResolvedValue({
      generated_at: new Date().toISOString(),
      count: 1,
      cards: [makeCard({ cluster: { ...makeCard().cluster, headline: 'Snapshot Story' } })],
    })

    renderPage()
    await waitFor(() => expect(screen.getByText('Recent Snapshots')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /latest/i }))

    await waitFor(() => expect(screen.getAllByText('Snapshot Story')[0]).toBeInTheDocument())
  })

  it('shows empty and error states', async () => {
    const runSpy = vi.spyOn(client.api, 'runIntelligence')
    runSpy.mockResolvedValueOnce({ ok: true, cards: [], total: 0, filtered: 0 })
    renderPage()
    clickRun()
    await waitFor(() => expect(screen.getByText(/No opportunities found/)).toBeInTheDocument())

    runSpy.mockRejectedValueOnce(new Error('Network down'))
    fireEvent.click(screen.getByRole('button', { name: /Run Intelligence/i }))
    await waitFor(() => expect(screen.getByText(/Network down/)).toBeInTheDocument())
  })
})
