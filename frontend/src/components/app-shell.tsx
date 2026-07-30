import { Link, useRouterState } from '@tanstack/react-router'
import {
  Brain,
  FileText,
  LayoutDashboard,
  Megaphone,
  CalendarClock,
  BarChart3,
  Globe,
  Newspaper,
  Settings,
  Bot,
  Menu,
  X,
  LogOut,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/api/client'
import { useState } from 'react'

/*
 * App shell styled on the buildwithabdallah design system:
 * near-black zinc surfaces (#09090b / #0e0e10), electric-blue accent
 * (#005cff / #3d7fff), JetBrains Mono (font-bwa-mono) for the wordmark,
 * kickers and nav, tight radii and a glowing active-route indicator.
 */

const MONO = 'font-bwa-mono'

const nav = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/feed', label: 'News Feed', icon: Newspaper },
  { to: '/intelligence', label: 'Intelligence', icon: Brain },
  { to: '/drafts', label: 'Drafts', icon: FileText },
  { to: '/social', label: 'Social Drafts', icon: Megaphone },
  { to: '/scheduler', label: 'Scheduler', icon: CalendarClock },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/sources', label: 'Sources', icon: Globe },
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/assistant', label: 'AI Assistant', icon: Bot },
]

function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <div>
      <div className={cn(MONO, 'text-[10px] uppercase tracking-[0.22em] text-[#71717a] mb-1')}>
        build with abdallah
      </div>
      <div className={cn(MONO, 'font-bold tracking-tight text-[#fafafa]', compact ? 'text-base' : 'text-xl')}>
        <span className="text-[#3d7fff]">▸</span> smkit
      </div>
      {!compact && <div className={cn(MONO, 'text-[10px] text-[#52525b] mt-0.5')}>content os</div>}
    </div>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const state = useRouterState()
  const current = state.location.pathname

  // The login route is full-screen and renders without the app chrome.
  if (current === '/login') {
    return <>{children}</>
  }

  async function handleLogout() {
    try {
      await api.logout()
    } catch {
      /* ignore — clear the session client-side regardless */
    }
    window.location.href = '/login'
  }

  const navItems = (onNavigate?: () => void) =>
    nav.map((item) => {
      const Icon = item.icon
      const active = current === item.to || current.startsWith(item.to + '/')
      return (
        <Link
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          className={cn(
            'group relative flex items-center gap-3 rounded-[4px] px-3 py-2 text-[13px] transition-colors',
            MONO,
            active ? 'text-[#fafafa]' : 'text-[#a1a1aa] hover:text-[#fafafa] hover:bg-[rgba(255,255,255,0.03)]'
          )}
          style={active ? { background: 'rgba(0,92,255,0.10)' } : undefined}
        >
          {active && (
            <span
              className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full"
              style={{ background: '#005cff', boxShadow: '0 0 8px rgba(0,92,255,0.8)' }}
            />
          )}
          <Icon className="h-4 w-4 shrink-0" style={{ color: active ? '#3d7fff' : undefined }} />
          <span className="truncate">{item.label}</span>
        </Link>
      )
    })

  return (
    <div className="flex min-h-screen" style={{ background: '#09090b', color: '#fafafa' }}>
      {/* Desktop sidebar */}
      <aside
        className="hidden w-64 flex-col border-r lg:flex"
        style={{ background: '#0e0e10', borderColor: '#26262b' }}
      >
        <div className="border-b px-5 py-5" style={{ borderColor: '#1c1c20' }}>
          <Wordmark />
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">{navItems()}</nav>
        <div className="border-t px-5 py-3" style={{ borderColor: '#1c1c20' }}>
          <div className={cn(MONO, 'flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-[#52525b]')}>
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ background: '#34d399' }} />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full" style={{ background: '#34d399' }} />
            </span>
            system online
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex h-16 items-center justify-between border-b px-4"
          style={{ background: '#0e0e10', borderColor: '#26262b' }}
        >
          {/* Mobile: menu + brand */}
          <div className="flex items-center gap-3 lg:hidden">
            <button
              onClick={() => setOpen(!open)}
              className="rounded-[4px] p-2 text-[#a1a1aa] transition-colors hover:bg-[rgba(255,255,255,0.04)] hover:text-[#fafafa]"
              aria-label="Toggle navigation"
            >
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <Wordmark compact />
          </div>

          {/* Desktop: live status pill */}
          <div className="hidden items-center gap-2 lg:flex">
            <span
              className={cn(MONO, 'inline-flex items-center gap-1.5 rounded-[4px] border px-2 py-1 text-[10px] uppercase tracking-[0.14em]')}
              style={{ color: '#34d399', borderColor: 'rgba(52,211,153,0.25)', background: 'rgba(52,211,153,0.05)' }}
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ background: '#34d399' }} />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full" style={{ background: '#34d399' }} />
              </span>
              live
            </span>
          </div>

          {/* Right: operator + sign out */}
          <div className="flex items-center gap-2.5">
            <div className="mr-0.5 hidden flex-col items-end sm:flex">
              <span className={cn(MONO, 'text-[11px] text-[#a1a1aa]')}>abdallah</span>
              <span className={cn(MONO, 'text-[10px] text-[#52525b]')}>operator</span>
            </div>
            <div
              className="flex h-8 w-8 items-center justify-center rounded-[4px]"
              style={{ background: 'rgba(0,92,255,0.15)', border: '1px solid rgba(0,92,255,0.3)' }}
            >
              <span className={cn(MONO, 'text-[12px] font-semibold text-[#3d7fff]')}>A</span>
            </div>
            <button
              onClick={handleLogout}
              title="Sign out"
              className="rounded-[4px] p-2 text-[#71717a] transition-colors hover:bg-[rgba(248,113,113,0.08)] hover:text-[#f87171]"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>

        {/* Mobile nav drawer */}
        {open && (
          <nav className="space-y-0.5 border-b p-3 lg:hidden" style={{ background: '#0e0e10', borderColor: '#26262b' }}>
            {navItems(() => setOpen(false))}
          </nav>
        )}

        <main className="flex-1 overflow-auto p-4 md:p-6">{children}</main>
      </div>
    </div>
  )
}
