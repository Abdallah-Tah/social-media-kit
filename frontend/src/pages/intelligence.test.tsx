import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { IntelligencePage } from './intelligence'
import * as client from '@/api/client'
import type { IntelligenceCard } from '@/api/models'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

function TestWrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <div data-testid="test-wrapper">{children}</div>
    </QueryClientProvider>
  )
}

function renderPage() {
  const Page = () => (
    <TestWrapper>
      <IntelligencePage />
    </TestWrapper>
  )
  render(<Page />)
}

function makeCard(overrides: Partial<IntelligenceCard> = {}): IntelligenceCard {
  const brief: NonNullable<IntelligenceCard['brief']> = {
    content_type: 'blog',
    title: 'How AI Agents Are Changing Developer Workflows',
    hook: 'Stop doing X manually',
    angle: 'practical guide',
    key_points: ['agents', 'workflows'],
    call_to_action: 'Try it today',
  }
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
    trend: { direction: 'up', strength: 0.8, velocity: 1.2, sparkline: [10, 20, 30], age_hours: 12 },
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
    brief,
    score_breakdown: [
      { name: 'Authority', score: 78, weight: 0.25 },
      { name: 'Trend', score: 80, weight: 0.25 },
    ],
    platform_fit: [
      { platform: 'linkedin', score: 85, reason: 'B2B audience' },
      { platform: 'x', score: 60, reason: 'Dev community' },
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
    queryClient.clear()
    vi.restoreAllMocks()
  })

  function clickRun() {
    const button = screen.getByRole('button', { name: /Run Intelligence/i })
    fireEvent.click(button)
  }

  it('renders fetched opportunities', async () => {
    vi.spyOn(client.api, 'runIntelligence').mockResolvedValueOnce({
      ok: true,
      cards: [makeCard({ rank: 1, cluster: { ...makeCard().cluster, headline: 'Fetched Opportunity' } })],
      total: 1,
      filtered: 1,
    })

    renderPage()
    clickRun()

    await waitFor(() => expect(screen.getAllByText('Fetched Opportunity')[0]).toBeInTheDocument())
    expect(screen.getAllByText('82')[0]).toBeInTheDocument()
  })

  it('updates filters and includes seen', async () => {
    const spy = vi.spyOn(client.api, 'runIntelligence').mockResolvedValue({ ok: true, cards: [], total: 0, filtered: 0 })
    renderPage()

    fireEvent.change(screen.getByPlaceholderText('e.g. AI, Laravel, Raspberry Pi'), { target: { value: 'Laravel' } })
    fireEvent.click(screen.getByLabelText('Include seen stories'))
    clickRun()

    await waitFor(
      () =>
        expect(spy).toHaveBeenCalledWith(
          expect.objectContaining({ topic: 'Laravel', include_seen: true })
        ),
      { timeout: 5000 }
    )
  })

  it('shows empty state when no cards', async () => {
    vi.spyOn(client.api, 'runIntelligence').mockResolvedValueOnce({ ok: true, cards: [], total: 0, filtered: 0 })
    renderPage()
    clickRun()

    await waitFor(() => expect(screen.getByText(/No opportunities found/)).toBeInTheDocument())
  })

  it('shows error state with retry', async () => {
    vi.spyOn(client.api, 'runIntelligence').mockRejectedValueOnce(new Error('Network down'))
    renderPage()
    clickRun()

    await waitFor(() => expect(screen.getByText(/Network down/)).toBeInTheDocument())
    expect(screen.getByText('Retry')).toBeInTheDocument()
  })

  it('expands card to show details', async () => {
    vi.spyOn(client.api, 'runIntelligence').mockResolvedValueOnce({
      ok: true,
      cards: [makeCard({ brief: undefined })],
      total: 1,
      filtered: 1,
    })

    renderPage()
    clickRun()
    await waitFor(() => expect(screen.getByText('AI agents reshape dev workflows')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Details'))
    await waitFor(() => expect(screen.getByText('Why care')).toBeInTheDocument())
    expect(screen.getByText('Score breakdown')).toBeInTheDocument()
    expect(screen.getByText('Platform fit')).toBeInTheDocument()
  })

  it('calls brief and draft actions', async () => {
    const card = makeCard()
    const briefSpy = vi.spyOn(client.api, 'generateBrief').mockResolvedValue({ ok: true, brief: card.brief })
    const draftSpy = vi.spyOn(client.api, 'createDraftFromBrief').mockResolvedValue({ ok: true, draft_id: 'draft-1' })
    vi.spyOn(client.api, 'runIntelligence').mockResolvedValueOnce({
      ok: true,
      cards: [card],
      total: 1,
      filtered: 1,
    })

    renderPage()
    clickRun()
    await waitFor(() => expect(screen.getByText('AI agents reshape dev workflows')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Generate Brief'))
    await waitFor(() => expect(briefSpy).toHaveBeenCalledWith(1))

    fireEvent.click(screen.getByText('Create Draft'))
    await waitFor(() => expect(draftSpy).toHaveBeenCalled())
  })
})
