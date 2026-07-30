import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Stage7dShadowCard } from './Stage7dShadow'
import type { Stage7dStatus } from '@/api/models'

vi.mock('@/api/client', () => ({
  api: {
    getStage7dStatus: vi.fn(),
  },
}))

import { api } from '@/api/client'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

const fullStatus: Stage7dStatus = {
  ok: true,
  service: {
    status: 'running',
    pid: 255644,
    started_at: '2026-07-29T16:09:31-04:00',
    planned_completion_at: '2026-07-30T16:09:31-04:00',
    time_remaining_seconds: 85000,
  },
  safety: {
    shadow_mode: true,
    editorial_slots_enabled: false,
    publishing_enabled: false,
    notifications_enabled: false,
    cron_unchanged: true,
  },
  progress: {
    slots_expected: 3,
    slots_completed: 1,
    next_slot: { slot_id: 'intelligence_brief', scheduled_at: '2026-07-30T08:00:00-04:00' },
  },
  slots: [
    {
      slot_id: 'practical_takeaway',
      content_type: 'practical_takeaway',
      scheduled_at: '2026-07-29T17:00:00-04:00',
      completed_at: '2026-07-29T17:05:00-04:00',
      status: 'completed',
      candidates_received: 50,
      candidates_enriched: 50,
      candidates_merged: 10,
      evidence_urls_fetched: 12,
      evidence_fetch_failures: 0,
      extraction_successes: 3,
      extraction_failures: 1,
      extraction_llm_calls: 10,
      top_source_confidence_scores: [72, 68, 65, 61, 58],
      selected_candidate: 'cand_abc123def456',
      selected_format: 'technical_analysis',
      admission_result: 'admitted',
      admission_reasons: [],
      quality_score: 81,
      readiness_status: 'ready',
      shadow_outcome: 'ready_in_shadow',
      latency_ms: 1500,
      api_cost_usd: 0.012,
      result_path: '/state/editorial/shadow/stage_7d/2026-07-29_1700_practical_takeaway.json',
    },
    {
      slot_id: 'intelligence_brief',
      content_type: 'intelligence_brief',
      scheduled_at: '2026-07-30T08:00:00-04:00',
      completed_at: null,
      status: 'waiting',
      candidates_received: 0,
      candidates_enriched: 0,
      candidates_merged: 0,
      evidence_urls_fetched: 0,
      evidence_fetch_failures: 0,
      extraction_successes: 0,
      extraction_failures: 0,
      extraction_llm_calls: 0,
      top_source_confidence_scores: [],
      selected_candidate: null,
      selected_format: null,
      admission_result: null,
      admission_reasons: [],
      quality_score: null,
      readiness_status: null,
      shadow_outcome: null,
      latency_ms: null,
      api_cost_usd: null,
      result_path: null,
    },
  ],
  aggregate: {
    ready_in_shadow: 1,
    ready_with_warnings_hold: 0,
    requires_manual_review: 0,
    quality_rejected: 0,
    skipped_no_candidate: 0,
    draft_generation_failed: 0,
    total_api_cost_usd: 0.012,
  },
}

beforeEach(() => {
  vi.mocked(api.getStage7dStatus).mockResolvedValue(fullStatus)
})

describe('Stage7dShadowCard', () => {
  it('always shows the prominent shadow-mode banner', async () => {
    wrap(<Stage7dShadowCard />)
    await waitFor(() => {
      expect(screen.getByTestId('stage7d-shadow-banner')).toBeInTheDocument()
    })
    expect(screen.getByText(/SHADOW MODE — NO CONTENT WILL BE PUBLISHED/i)).toBeInTheDocument()
  })

  it('renders service status, timing, and per-slot cards with full data', async () => {
    wrap(<Stage7dShadowCard />)
    await waitFor(() => {
      expect(screen.getByText('● running')).toBeInTheDocument()
    })
    // Slot ids render.
    expect(screen.getByText('practical_takeaway')).toBeInTheDocument()
    expect(screen.getByText('intelligence_brief')).toBeInTheDocument()
    // Completed slot shows its shadow outcome.
    expect(screen.getByText('ready_in_shadow')).toBeInTheDocument()
  })

  it('renders safely with missing and null fields (no crash)', async () => {
    // A heavily-degraded response: nulls and empty collections everywhere.
    const degraded = {
      ok: true,
      service: {
        status: 'not_started',
        pid: null,
        started_at: null,
        planned_completion_at: null,
        time_remaining_seconds: null,
      },
      safety: {
        shadow_mode: true,
        editorial_slots_enabled: false,
        publishing_enabled: false,
        notifications_enabled: false,
        cron_unchanged: true,
      },
      progress: { slots_expected: 0, slots_completed: 0, next_slot: null },
      slots: [],
      aggregate: {
        ready_in_shadow: 0,
        ready_with_warnings_hold: 0,
        requires_manual_review: 0,
        quality_rejected: 0,
        skipped_no_candidate: 0,
        draft_generation_failed: 0,
        total_api_cost_usd: 0,
      },
    } as Stage7dStatus
    vi.mocked(api.getStage7dStatus).mockResolvedValue(degraded)

    wrap(<Stage7dShadowCard />)
    // Wait for the (degraded) data to load; component must not throw.
    await waitFor(() => {
      expect(screen.getByText('not started')).toBeInTheDocument()
    })
    expect(screen.getByTestId('stage7d-shadow-banner')).toBeInTheDocument()
    expect(screen.getByText(/No slot schedule available yet/i)).toBeInTheDocument()
  })

  it('renders a slot safely when most of its fields are missing', async () => {
    const partial = {
      ...fullStatus,
      slots: [
        // Only slot_id and status — everything else absent.
        { slot_id: 'midday_authority', status: 'waiting' } as unknown as Stage7dStatus['slots'][number],
      ],
    }
    vi.mocked(api.getStage7dStatus).mockResolvedValue(partial)

    wrap(<Stage7dShadowCard />)
    await waitFor(() => {
      expect(screen.getByText('midday_authority')).toBeInTheDocument()
    })
    expect(screen.getByText(/Waiting for scheduled time/i)).toBeInTheDocument()
  })

  it('shows the error state when the fetch fails', async () => {
    vi.mocked(api.getStage7dStatus).mockRejectedValue(new Error('boom'))
    wrap(<Stage7dShadowCard />)
    await waitFor(() => {
      expect(screen.getByText(/Could not load shadow status/i)).toBeInTheDocument()
    })
    // Banner is still present even in the error state.
    expect(screen.getByTestId('stage7d-shadow-banner')).toBeInTheDocument()
  })

  it('is read-only: no publish/approve/cutover/restart/telegram actions', async () => {
    wrap(<Stage7dShadowCard />)
    await waitFor(() => {
      expect(screen.getByTestId('stage7d-shadow-banner')).toBeInTheDocument()
    })
    const buttons = screen.queryAllByRole('button')
    for (const btn of buttons) {
      const label = (btn.textContent || '').toLowerCase()
      expect(label).not.toMatch(/publish|approve|cutover|restart|telegram|enable|notify/)
    }
  })
})
