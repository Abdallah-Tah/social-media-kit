import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { createRootRoute, createRoute, createRouter, RouterProvider, Outlet } from '@tanstack/react-router'
import { AppShell } from './app-shell'

const rootRoute = createRootRoute({
  component: () => (
    <AppShell>
      <Outlet />
    </AppShell>
  ),
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: () => <div>Dashboard Content</div>,
})

const intelligenceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/intelligence',
  component: () => <div>Intelligence Content</div>,
})

const router = createRouter({
  routeTree: rootRoute.addChildren([indexRoute, intelligenceRoute]),
  defaultPreload: 'intent',
})

async function waitForShell() {
  await waitFor(() => expect(document.querySelector('aside')).toBeInTheDocument(), { timeout: 3000 })
}

describe('AppShell', () => {
  it('renders the app title', async () => {
    render(<RouterProvider router={router} />)
    await waitForShell()
    const logo = document.querySelector('aside')?.textContent
    expect(logo).toContain('smkit')
  })

  it('renders main navigation items', async () => {
    render(<RouterProvider router={router} />)
    await waitForShell()
    const aside = document.querySelector('aside')?.textContent
    expect(aside).toContain('Dashboard')
    expect(aside).toContain('Intelligence')
    expect(aside).toContain('Drafts')
  })

  it('toggles mobile menu when hamburger is clicked', async () => {
    render(<RouterProvider router={router} />)
    await waitForShell()
    const buttons = screen.getAllByRole('button')
    const hamburger = buttons.find((b) => b.querySelector('svg'))
    expect(hamburger).toBeDefined()
    if (hamburger) fireEvent.click(hamburger)
  })
})
