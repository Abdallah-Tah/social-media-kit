import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DraftsPage from './drafts'

vi.mock('@/api/client', () => ({
  api: {
    getDrafts: vi.fn(),
    saveDraft: vi.fn(),
    publishBlog: vi.fn(),
    createSocialDrafts: vi.fn(),
    getDraftCover: vi.fn(),
    regenerateCover: vi.fn(),
    rewriteDraft: vi.fn(),
  },
}))

import { api } from '@/api/client'

const mockDraft = {
  draft_id: 'abc123',
  title: 'AI and APIs',
  slug: 'ai-and-apis',
  status: 'draft' as const,
  body: '# AI and APIs\n\nContent here.',
  content_type: 'blog',
  source_urls: ['https://example.com/source'],
  blog_url: '',
  published_at: '',
  created_at: '2026-07-01T00:00:00Z',
  updated_at: '2026-07-01T00:00:00Z',
  source_cluster: {},
  recommendation: {},
  brief: {},
  cover_image_url: '',
  seo_title: '',
  seo_description: '',
}

const mockApprovedDraft = { ...mockDraft, status: 'approved' as const, draft_id: 'def456', title: 'Approved Post' }

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  vi.mocked(api.getDrafts).mockResolvedValue([mockDraft, mockApprovedDraft])
  vi.mocked(api.getDraftCover).mockResolvedValue({ ok: true, cover_image_url: '', exists: false, styles: ['clean_tech'] })
})

describe('DraftsPage', () => {
  it('renders draft list', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => {
      expect(screen.getAllByText('AI and APIs').length).toBeGreaterThan(0)
      expect(screen.getByText('Approved Post')).toBeInTheDocument()
    })
  })

  it('shows status badges', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => {
      expect(screen.getAllByText('draft').length).toBeGreaterThan(0)
      expect(screen.getAllByText('approved').length).toBeGreaterThan(0)
    })
  })

  it('shows source links for selected draft', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => {
      expect(screen.getByText('https://example.com/source')).toBeInTheDocument()
    })
  })

  it('shows body in edit mode by default', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => {
      const textarea = document.querySelector('textarea')
      expect(textarea).toBeTruthy()
      expect(textarea!.value).toContain('Content here.')
    })
  })

  it('switches to markdown preview', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => screen.getAllByText('AI and APIs').length > 0)
    const previewBtns = screen.getAllByRole('button', { name: /preview/i })
    await userEvent.click(previewBtns[0])
    await waitFor(() => {
      expect(screen.getByText('Content here.')).toBeInTheDocument()
    })
  })

  it('shows SEO fields', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Leave blank to use main title/i)).toBeInTheDocument()
      expect(screen.getByPlaceholderText(/160-char summary/i)).toBeInTheDocument()
    })
  })

  it('shows AI rewrite buttons', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Shorter' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Stronger Hook' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'More Technical' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'More Casual' })).toBeInTheDocument()
    })
  })

  it('calls rewriteDraft with mode on button click', async () => {
    vi.mocked(api.rewriteDraft).mockResolvedValue({ ok: true, body: 'Shorter version.', mode: 'shorter' })
    wrap(<DraftsPage />)
    await waitFor(() => screen.getByRole('button', { name: 'Shorter' }))
    await userEvent.click(screen.getByRole('button', { name: 'Shorter' }))
    expect(api.rewriteDraft).toHaveBeenCalledWith('abc123', 'shorter')
  })

  it('publish button is disabled when status is draft', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => screen.getByRole('button', { name: /Publish Blog/i }))
    const publishBtn = screen.getByRole('button', { name: /Publish Blog/i })
    expect(publishBtn).toBeDisabled()
  })

  it('shows cover panel with generate button', async () => {
    wrap(<DraftsPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Generate Cover/i })).toBeInTheDocument()
    })
  })

  it('shows cover image when exists', async () => {
    vi.mocked(api.getDraftCover).mockResolvedValue({
      ok: true,
      cover_image_url: 'https://cdn.example.com/cover.png',
      exists: true,
      styles: ['clean_tech'],
    })
    wrap(<DraftsPage />)
    await waitFor(() => {
      const img = screen.getAllByRole('img').find((el) => el.getAttribute('alt') === 'Draft cover')
      expect(img).toBeTruthy()
      expect(img!.getAttribute('src')).toBe('https://cdn.example.com/cover.png')
    })
  })

  it('calls regenerateCover when button clicked', async () => {
    vi.mocked(api.regenerateCover).mockResolvedValue({ ok: true, cover_image_url: 'url', style: 'clean_tech' })
    wrap(<DraftsPage />)
    await waitFor(() => screen.getByRole('button', { name: /Generate Cover/i }))
    await userEvent.click(screen.getByRole('button', { name: /Generate Cover/i }))
    expect(api.regenerateCover).toHaveBeenCalledWith('abc123', 'clean_tech')
  })
})
