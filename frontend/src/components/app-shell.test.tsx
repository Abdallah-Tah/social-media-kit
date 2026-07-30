import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createRootRoute, createRoute, createRouter, RouterProvider, Outlet } from '@tanstack/react-router'
import { AppShell } from './app-shell'

vi.mock('@/api/client', () => ({
  api: {
    logout: vi.fn().mockResolvedValue({ ok: true }),
    checkAuth: vi.fn().mockResolvedValue({ ok: true, authenticated: false }),
  },
}))
import { api } from '@/api/client'

function makeRouter() {
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
  const loginRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/login',
    component: () => <div>Login Page</div>,
  })
  return createRouter({
    routeTree: rootRoute.addChildren([indexRoute, intelligenceRoute, loginRoute]),
    defaultPreload: 'intent',
  })
}

async function renderAt(path: string) {
  const router = makeRouter()
  render(<RouterProvider router={router} />)
  await router.navigate({ to: path })
  return router
}

async function waitForShell() {
  await waitFor(() => expect(document.querySelector('aside')).toBeInTheDocument(), { timeout: 3000 })
}

describe('AppShell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the brand wordmark', async () => {
    await renderAt('/')
    await waitForShell()
    const aside = document.querySelector('aside')
    expect(aside?.textContent).toContain('smkit')
    expect(aside?.textContent).toContain('build with abdallah')
  })

  it('renders main navigation items', async () => {
    await renderAt('/')
    await waitForShell()
    const aside = document.querySelector('aside')?.textContent
    expect(aside).toContain('Dashboard')
    expect(aside).toContain('Intelligence')
    expect(aside).toContain('Drafts')
  })

  it('toggles the mobile menu when the hamburger is clicked', async () => {
    await renderAt('/')
    await waitForShell()
    const hamburger = screen.getByLabelText('Toggle navigation')
    fireEvent.click(hamburger)
    fireEvent.click(hamburger)
  })

  it('signs out and redirects to /login', async () => {
    const original = window.location
    Object.defineProperty(window, 'location', { configurable: true, writable: true, value: { href: '/' } })
    try {
      await renderAt('/')
      await waitForShell()
      fireEvent.click(screen.getByTitle('Sign out'))
      await waitFor(() => expect(api.logout).toHaveBeenCalled())
      await waitFor(() => expect(window.location.href).toBe('/login'))
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, writable: true, value: original })
    }
  })

  it('renders the login route without the app chrome', async () => {
    await renderAt('/login')
    await waitFor(() => expect(screen.getByText('Login Page')).toBeInTheDocument())
    expect(document.querySelector('aside')).not.toBeInTheDocument()
  })
})
