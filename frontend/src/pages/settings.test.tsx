import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SettingsPage from './settings'

vi.mock('@/api/client', () => ({
  api: {
    getAutomations: vi.fn(),
    updateAutomation: vi.fn(),
    runAutomationNow: vi.fn(),
    getLogs: vi.fn(),
  },
}))

import { api } from '@/api/client'

const mockAutomations = [
  {
    job_id: 'intelligence_run',
    label: 'Intelligence Run',
    description: 'Fetch and score fresh stories.',
    enabled: false,
    interval_hours: 6,
    dry_run: true,
    last_run: null,
    last_result: null as null,
    last_error: null,
    next_run: null,
  },
  {
    job_id: 'publish_due',
    label: 'Publish Scheduled Posts',
    description: 'Publish due social drafts.',
    enabled: true,
    interval_hours: 1,
    dry_run: true,
    last_run: new Date(Date.now() - 3600_000).toISOString(),
    last_result: 'ok' as const,
    last_error: '',
    next_run: new Date(Date.now() + 3600_000).toISOString(),
  },
]

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.mocked(api.getAutomations).mockResolvedValue({ ok: true, automations: mockAutomations })
  vi.mocked(api.getLogs).mockResolvedValue({ ok: true, logs: [] })
})

describe('SettingsPage', () => {
  it('renders automation cards', async () => {
    wrap(<SettingsPage />)
    await waitFor(() => {
      expect(screen.getByText('Intelligence Run')).toBeInTheDocument()
      expect(screen.getByText('Publish Scheduled Posts')).toBeInTheDocument()
    })
  })

  it('shows dry run badge', async () => {
    wrap(<SettingsPage />)
    await waitFor(() => {
      const badges = screen.getAllByText('dry run')
      expect(badges.length).toBeGreaterThan(0)
    })
  })

  it('shows last ok badge for enabled job with ok result', async () => {
    wrap(<SettingsPage />)
    await waitFor(() => {
      expect(screen.getByText('last ok')).toBeInTheDocument()
    })
  })

  it('calls updateAutomation when toggle is clicked', async () => {
    vi.mocked(api.updateAutomation).mockResolvedValue({
      ok: true,
      automation: { ...mockAutomations[0], enabled: true } as import('@/api/models').Automation,
    })
    wrap(<SettingsPage />)
    await waitFor(() => screen.getByText('Intelligence Run'))
    const toggles = screen.getAllByRole('switch', { name: /toggle/i })
    await userEvent.click(toggles[0])
    expect(api.updateAutomation).toHaveBeenCalledWith('intelligence_run', { enabled: true })
  })

  it('shows run now button and calls runAutomationNow on click', async () => {
    vi.mocked(api.runAutomationNow).mockResolvedValue({ ok: true, message: 'done' })
    wrap(<SettingsPage />)
    await waitFor(() => screen.getByText('Intelligence Run'))
    const runBtns = screen.getAllByRole('button', { name: 'Run now' })
    await userEvent.click(runBtns[0])
    expect(api.runAutomationNow).toHaveBeenCalledWith('intelligence_run')
  })

  it('shows empty log state when no logs', async () => {
    wrap(<SettingsPage />)
    await waitFor(() => {
      expect(screen.getByText(/No automation runs yet/i)).toBeInTheDocument()
    })
  })

  it('renders log entries when present', async () => {
    vi.mocked(api.getLogs).mockResolvedValue({
      ok: true,
      logs: [{ ts: new Date().toISOString(), job_id: 'publish_due', ok: true, message: 'published 2', dry_run: false }],
    })
    wrap(<SettingsPage />)
    await waitFor(() => {
      expect(screen.getByText('published 2')).toBeInTheDocument()
    })
  })
})
