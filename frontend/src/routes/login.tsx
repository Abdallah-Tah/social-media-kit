import { useEffect, useState } from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { Lock, ArrowRight, ShieldCheck } from 'lucide-react'

import { api } from '@/api/client'

const MONO = 'font-bwa-mono'

export function Login() {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [checking, setChecking] = useState(true)

  // If a valid session already exists, go straight to the app.
  useEffect(() => {
    let active = true
    api
      .checkAuth()
      .then((r) => {
        if (active && r.authenticated) navigate({ to: '/' })
      })
      .catch(() => {})
      .finally(() => {
        if (active) setChecking(false)
      })
    return () => {
      active = false
    }
  }, [navigate])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError('')
    try {
      const r = await api.login(password)
      if (r.ok) {
        navigate({ to: '/' })
      } else {
        setError('Invalid password.')
      }
    } catch {
      setError('Invalid password.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="relative flex min-h-screen items-center justify-center overflow-hidden px-4"
      style={{ background: '#09090b' }}
    >
      {/* ambient glow + grid texture */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(50% 40% at 50% 0%, rgba(0,92,255,0.16), transparent 70%)' }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.028) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.028) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
        }}
      />

      <div className="relative w-full max-w-sm">
        {/* signature accent line */}
        <div
          className="h-px w-full mb-6"
          style={{ background: 'linear-gradient(90deg, transparent, #005cff 30%, #3d7fff 50%, #005cff 70%, transparent)' }}
        />

        <div
          className="rounded-[6px] border px-6 py-8"
          style={{
            borderColor: '#26262b',
            background: '#0e0e10',
            boxShadow: '0 0 0 1px rgba(0,92,255,0.12), 0 24px 60px -20px rgba(0,0,0,0.7)',
          }}
        >
          {/* brand mark */}
          <div className="mb-7">
            <div className={`${MONO} text-[11px] uppercase tracking-[0.22em] text-[#71717a] mb-2`}>
              build with abdallah
            </div>
            <div className={`${MONO} text-2xl font-bold tracking-tight text-[#fafafa]`}>
              <span className="text-[#3d7fff]">▸</span> smkit
            </div>
            <div className={`${MONO} text-[11px] text-[#52525b] mt-1`}>content os · operator access</div>
          </div>

          {checking ? (
            <div className="h-24 rounded-[4px] bg-[#161618] animate-pulse" />
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label htmlFor="password" className={`${MONO} text-[11px] uppercase tracking-[0.18em] text-[#a1a1aa] block mb-2`}>
                  password
                </label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#52525b]" />
                  <input
                    id="password"
                    type="password"
                    autoFocus
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className={`${MONO} w-full rounded-[4px] border bg-[#161618] pl-9 pr-3 py-2.5 text-sm text-[#fafafa] placeholder:text-[#3a3a42] outline-none transition-colors focus:border-[#3d7fff]`}
                    style={{ borderColor: '#26262b' }}
                  />
                </div>
              </div>

              {error && (
                <div className={`${MONO} text-[12px] text-[#f87171]`}>// {error}</div>
              )}

              <button
                type="submit"
                disabled={submitting || !password}
                className="group flex w-full items-center justify-center gap-2 rounded-[4px] px-4 py-2.5 text-sm font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  background: '#005cff',
                  color: '#ffffff',
                  boxShadow: '0 0 24px -4px rgba(0,92,255,0.5)',
                }}
              >
                {submitting ? 'Verifying…' : 'Sign in'}
                {!submitting && <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />}
              </button>
            </form>
          )}
        </div>

        <div className="mt-5 flex items-center justify-center gap-1.5 text-[#52525b]">
          <ShieldCheck className="h-3.5 w-3.5" />
          <span className={`${MONO} text-[11px] uppercase tracking-[0.14em]`}>
            private session · read-only controls
          </span>
        </div>
      </div>
    </div>
  )
}

export const Route = createFileRoute('/login')({
  component: Login,
})
