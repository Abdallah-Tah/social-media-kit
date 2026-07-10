import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { describe, expect, it, vi } from 'vitest'
import { routeTree } from '@/routeTree.gen'
import { Route as IntelligenceRoute } from './intelligence'
import * as client from '@/api/client'

describe('lazy routes', () => {
  it('loads the Intelligence route through the app router', async () => {
    vi.spyOn(client.api, 'getSnapshots').mockResolvedValue({ snapshots: [] })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const router = createRouter({
      routeTree,
      history: createMemoryHistory({ initialEntries: ['/intelligence'] }),
    })

    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    )

    expect(IntelligenceRoute.options.component).toBeTypeOf('function')
    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Intelligence/i })).toHaveAttribute('data-status', 'active')
    })
  })
})
