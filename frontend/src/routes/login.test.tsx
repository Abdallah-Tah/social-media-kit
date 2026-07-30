import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

const navigateSpy = vi.fn()
vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useNavigate: () => navigateSpy }
})

vi.mock('@/api/client', () => ({
  api: {
    checkAuth: vi.fn(),
    login: vi.fn(),
  },
}))
import { api } from '@/api/client'
import { Login } from './login'

describe('Login page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.checkAuth).mockResolvedValue({ ok: true, authenticated: false })
  })

  it('renders the brand wordmark and password form', async () => {
    render(<Login />)
    await waitFor(() => expect(screen.getByLabelText('password')).toBeInTheDocument())
    expect(screen.getByText('smkit')).toBeInTheDocument()
    expect(screen.getByText('build with abdallah')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('shows an error on a wrong password', async () => {
    vi.mocked(api.login).mockResolvedValue({ ok: false, error: 'invalid password' })
    render(<Login />)
    await waitFor(() => screen.getByLabelText('password'))
    fireEvent.change(screen.getByLabelText('password'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(screen.getByText(/invalid password/i)).toBeInTheDocument())
    expect(navigateSpy).not.toHaveBeenCalled()
  })

  it('navigates to / on a successful login', async () => {
    vi.mocked(api.login).mockResolvedValue({ ok: true })
    render(<Login />)
    await waitFor(() => screen.getByLabelText('password'))
    fireEvent.change(screen.getByLabelText('password'), { target: { value: 'correct' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(api.login).toHaveBeenCalledWith('correct'))
    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith({ to: '/' }))
  })

  it('redirects to / if a valid session already exists', async () => {
    vi.mocked(api.checkAuth).mockResolvedValue({ ok: true, authenticated: true })
    render(<Login />)
    await waitFor(() => expect(navigateSpy).toHaveBeenCalledWith({ to: '/' }))
  })
})
