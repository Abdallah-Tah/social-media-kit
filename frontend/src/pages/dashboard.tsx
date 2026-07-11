import { useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  LayoutDashboard, Clock, CheckCircle2, AlertTriangle, CalendarClock,
  FileText, Megaphone, Brain, Settings, RefreshCw, Zap,
} from 'lucide-react'

import { api } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardDescription, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { SocialDraft } from '@/api/models'

function isDue(d: SocialDraft) {
  if (!d.scheduled_at) return false
  const t = new Date(d.scheduled_at).getTime()
  return !Number.isNaN(t) && t <= Date.now()
}

function fmtRel(iso: string | null | undefined) {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function fmtNext(iso: string | null | undefined) {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  if (diff < 0) return 'overdue'
  if (diff < 60) return 'in <1m'
  if (diff < 3600) return `in ${Math.floor(diff / 60)}m`
  if (diff < 86400) return `in ${Math.floor(diff / 3600)}h`
  return `in ${Math.floor(diff / 86400)}d`
}

function statusColor(s: string) {
  if (s === 'published') return 'border-emerald-500 text-emerald-400'
  if (s === 'approved') return 'border-blue-500 text-blue-400'
  if (s === 'needs_review') return 'border-amber-500 text-amber-400'
  if (s === 'failed') return 'border-red-500 text-red-400'
  if (s === 'scheduled') return 'border-violet-500 text-violet-400'
  return ''
}

export default function DashboardPage() {
  const qc = useQueryClient()

  const analyticsQ = useQuery({ queryKey: ['analytics', 30], queryFn: () => api.getAnalytics(30), staleTime: 60_000 })
  const draftsQ = useQuery({ queryKey: ['drafts'], queryFn: api.getDrafts, staleTime: 30_000 })
  const socialQ = useQuery({ queryKey: ['social-drafts'], queryFn: api.getSocialDrafts, staleTime: 30_000 })
  const automationsQ = useQuery({ queryKey: ['automations'], queryFn: api.getAutomations, staleTime: 30_000 })

  const drafts = useMemo(() => draftsQ.data || [], [draftsQ.data])
  const socials = useMemo(() => socialQ.data || [], [socialQ.data])
  const automations = useMemo(() => automationsQ.data?.automations || [], [automationsQ.data])

  const pendingApproval = drafts.filter((d) => d.status === 'needs_review')
  const dueNow = socials.filter(isDue)
  const todayQueue = socials.filter((d) => {
    if (d.status !== 'scheduled') return false
    if (!d.scheduled_at) return false
    const at = new Date(d.scheduled_at)
    const now = new Date()
    return at.toDateString() === now.toDateString()
  })
  const failedPosts = socials.filter((d) => d.status === 'failed')
  const recentWins = socials.filter((d) => d.status === 'published').slice(0, 5)
  const nextAutoRun = automations
    .filter((a) => a.enabled && a.next_run)
    .sort((a, b) => (a.next_run! < b.next_run! ? -1 : 1))[0]

  const data = analyticsQ.data
  const funnel = data?.editorial_funnel as any
  const social = data?.social as any

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ['analytics'] })
    qc.invalidateQueries({ queryKey: ['drafts'] })
    qc.invalidateQueries({ queryKey: ['social-drafts'] })
    qc.invalidateQueries({ queryKey: ['automations'] })
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <LayoutDashboard className="h-6 w-6" />Dashboard
          </h1>
          <p className="text-muted-foreground">Content pipeline at a glance.</p>
        </div>
        <Button variant="outline" onClick={refreshAll}>
          <RefreshCw className="h-4 w-4 mr-1" />Refresh
        </Button>
      </div>

      {/* Operational KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <OpCard
          label="Pending Approval"
          value={pendingApproval.length}
          icon={Clock}
          accent="amber"
          href="/drafts"
          sublabel="need review"
        />
        <OpCard
          label="Due Now"
          value={dueNow.length}
          icon={CalendarClock}
          accent={dueNow.length > 0 ? 'amber' : undefined}
          href="/scheduler"
          sublabel="scheduled posts"
        />
        <OpCard
          label="Failed Posts"
          value={failedPosts.length}
          icon={AlertTriangle}
          accent={failedPosts.length > 0 ? 'red' : undefined}
          href="/scheduler"
          sublabel="need retry"
        />
        <OpCard
          label="Today's Queue"
          value={todayQueue.length}
          icon={Megaphone}
          href="/scheduler"
          sublabel="scheduled today"
        />
      </div>

      {/* Pipeline funnel numbers */}
      {(analyticsQ.isLoading) && <Skeleton className="h-24" />}
      {funnel && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard title="Drafts Created" value={funnel.drafts_created ?? 0} icon={FileText} />
          <MetricCard title="Blogs Published" value={funnel.blogs_published ?? 0} icon={CheckCircle2} accent="emerald" />
          <MetricCard title="Social Published" value={social?.total_published ?? 0} icon={Megaphone} accent="blue" />
          <MetricCard title="Conversion" value={`${funnel.overall_conversion_rate ?? 0}%`} icon={Brain} />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Pending approvals */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Clock className="h-4 w-4 text-amber-400" />Needs Review
            </CardTitle>
          </CardHeader>
          <CardContent>
            {draftsQ.isLoading && <Skeleton className="h-16" />}
            {pendingApproval.length === 0 && !draftsQ.isLoading && (
              <p className="text-sm text-muted-foreground">All clear — nothing waiting for review.</p>
            )}
            <div className="space-y-2">
              {pendingApproval.slice(0, 5).map((d) => (
                <div key={d.draft_id} className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm">{d.title || 'Untitled'}</span>
                  <Link to="/drafts">
                    <Badge variant="outline" className="text-xs border-amber-500 text-amber-400 shrink-0">review</Badge>
                  </Link>
                </div>
              ))}
            </div>
            {pendingApproval.length > 5 && (
              <p className="mt-2 text-xs text-muted-foreground">+{pendingApproval.length - 5} more in Drafts</p>
            )}
          </CardContent>
        </Card>

        {/* Failed posts */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-400" />Failed Posts
            </CardTitle>
          </CardHeader>
          <CardContent>
            {socialQ.isLoading && <Skeleton className="h-16" />}
            {failedPosts.length === 0 && !socialQ.isLoading && (
              <p className="text-sm text-muted-foreground">No failed posts.</p>
            )}
            <div className="space-y-2">
              {failedPosts.slice(0, 5).map((d) => (
                <div key={d.draft_id} className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="truncate text-sm block">{d.title || 'Untitled'}</span>
                    <span className="text-xs capitalize text-muted-foreground">{d.platform}</span>
                  </div>
                  <Link to="/scheduler">
                    <Badge variant="outline" className="text-xs border-red-500 text-red-400 shrink-0">retry</Badge>
                  </Link>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Automations + recent wins */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />Automations
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {automationsQ.isLoading && <Skeleton className="h-16" />}
            {automations.length > 0 && (
              <div className="space-y-2">
                {automations.filter((a) => a.enabled).slice(0, 3).map((a) => (
                  <div key={a.job_id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate text-muted-foreground">{a.label}</span>
                    <span className={`shrink-0 ${a.last_result === 'error' ? 'text-red-400' : 'text-muted-foreground'}`}>
                      {fmtRel(a.last_run)}
                    </span>
                  </div>
                ))}
                {automations.filter((a) => a.enabled).length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No automations enabled. <Link to="/settings" className="text-primary hover:underline">Configure</Link>
                  </p>
                )}
              </div>
            )}
            {nextAutoRun && (
              <div className="rounded border bg-muted/20 px-2 py-1.5 text-xs">
                Next: <strong>{nextAutoRun.label}</strong> · {fmtNext(nextAutoRun.next_run)}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent wins */}
      {recentWins.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />Recent Wins
            </CardTitle>
            <CardDescription>Last published social posts</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {recentWins.map((d) => (
                <div key={d.draft_id} className="flex items-center justify-between gap-3 text-sm">
                  <div className="flex items-center gap-2 min-w-0">
                    <Badge variant="outline" className={`capitalize shrink-0 text-xs ${statusColor(d.status)}`}>{d.platform}</Badge>
                    <span className="truncate text-muted-foreground">{d.title || 'Untitled'}</span>
                  </div>
                  {d.published_url && (
                    <a href={d.published_url} target="_blank" rel="noreferrer"
                      className="text-xs text-blue-400 hover:underline shrink-0">view</a>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Quick nav */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { to: '/intelligence', label: 'Run Intelligence', icon: Brain, desc: 'Discover new stories' },
          { to: '/drafts', label: 'Edit Drafts', icon: FileText, desc: `${drafts.length} total drafts` },
          { to: '/scheduler', label: 'Scheduler', icon: CalendarClock, desc: `${todayQueue.length} today` },
          { to: '/settings', label: 'Automations', icon: Settings, desc: `${automations.filter((a) => a.enabled).length} enabled` },
        ].map(({ to, label, icon: Icon, desc }) => (
          <Link key={to} to={to}>
            <Card className="cursor-pointer transition-colors hover:border-primary hover:bg-primary/5">
              <CardContent className="flex items-center gap-3 p-4">
                <Icon className="h-5 w-5 text-primary shrink-0" />
                <div>
                  <div className="text-sm font-medium">{label}</div>
                  <div className="text-xs text-muted-foreground">{desc}</div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}

function OpCard({ label, value, icon: Icon, accent, href, sublabel }: {
  label: string; value: number; icon: React.ElementType; accent?: string; href: string; sublabel: string
}) {
  const color = accent === 'red' ? 'text-red-400' : accent === 'amber' ? 'text-amber-400' : 'text-primary'
  const border = accent === 'red' && value > 0 ? 'border-red-500/30' : accent === 'amber' && value > 0 ? 'border-amber-500/30' : ''
  return (
    <Link to={href}>
      <Card className={`cursor-pointer transition hover:border-primary ${border}`}>
        <CardContent className="p-4">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-3xl font-bold">{value}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
              <div className="text-xs text-muted-foreground">{sublabel}</div>
            </div>
            <Icon className={`h-5 w-5 ${color} mt-1`} />
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function MetricCard({ title, value, icon: Icon, accent }: {
  title: string; value: number | string; icon: React.ElementType; accent?: string
}) {
  const color = accent === 'emerald' ? 'text-emerald-400' : accent === 'blue' ? 'text-blue-400' : 'text-primary'
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription className="flex items-center gap-1.5">
          <Icon className={`h-4 w-4 ${color}`} />{title}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold">{value}</div>
      </CardContent>
    </Card>
  )
}
