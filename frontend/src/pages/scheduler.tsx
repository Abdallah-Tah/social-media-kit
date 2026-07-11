import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  CalendarClock, RefreshCw, Save, Search, Send, AlertTriangle,
  Clock, CheckCircle2, RotateCcw, Loader2,
} from 'lucide-react'

import { api } from '@/api/client'
import type { SocialDraft } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

const PLATFORMS = ['all', 'linkedin', 'facebook', 'x', 'threads', 'reddit', 'newsletter', 'youtube']

function isDue(draft: SocialDraft) {
  if (!draft.scheduled_at) return false
  const t = new Date(draft.scheduled_at).getTime()
  return !Number.isNaN(t) && t <= Date.now()
}

function fmtDate(v: string) {
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString()
}

function statusColor(status: string) {
  if (status === 'published') return 'border-emerald-500 text-emerald-400'
  if (status === 'failed') return 'border-red-500 text-red-400'
  if (status === 'scheduled') return 'border-violet-500 text-violet-400'
  if (status === 'approved') return 'border-blue-500 text-blue-400'
  return ''
}

function DraftRow({ draft, onRetry, retrying }: {
  draft: SocialDraft
  onRetry?: () => void
  retrying?: boolean
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border p-3">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{draft.title || 'Untitled'}</div>
        <div className="mt-0.5 text-xs text-muted-foreground capitalize">
          {draft.platform}
          {draft.scheduled_at ? ` · ${fmtDate(draft.scheduled_at)}` : ''}
        </div>
        {draft.error && (
          <div className="mt-1 text-xs text-red-400 line-clamp-2" title={draft.error}>
            <AlertTriangle className="inline h-3 w-3 mr-1" />{draft.error}
          </div>
        )}
        {draft.published_url && (
          <a href={draft.published_url} target="_blank" rel="noreferrer"
            className="mt-0.5 block truncate text-xs text-blue-400 hover:underline">
            {draft.published_url}
          </a>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="outline" className={`capitalize ${statusColor(draft.status)}`}>
          {draft.status === 'scheduled' && isDue(draft) ? 'due' : draft.status}
        </Badge>
        {draft.status === 'failed' && onRetry && (
          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onRetry} disabled={retrying}>
            {retrying ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
          </Button>
        )}
      </div>
    </div>
  )
}

export default function SchedulerPage() {
  const queryClient = useQueryClient()
  const [dryRun, setDryRun] = useState(true)
  const [topic, setTopic] = useState('AI')
  const [includeSeen, setIncludeSeen] = useState(false)
  const [lastCount, setLastCount] = useState<number | null>(null)
  const [platformTab, setPlatformTab] = useState('all')
  const [retryingId, setRetryingId] = useState<string | null>(null)

  const socialQuery = useQuery({ queryKey: ['social-drafts'], queryFn: api.getSocialDrafts, refetchInterval: 60_000 })
  const allDrafts = useMemo(() => socialQuery.data || [], [socialQuery.data])

  const scheduled = useMemo(() =>
    allDrafts.filter((d) => d.status === 'scheduled' && (platformTab === 'all' || d.platform === platformTab)),
    [allDrafts, platformTab])
  const failed = useMemo(() =>
    allDrafts.filter((d) => d.status === 'failed' && (platformTab === 'all' || d.platform === platformTab)),
    [allDrafts, platformTab])
  const published = useMemo(() =>
    allDrafts.filter((d) => d.status === 'published' && (platformTab === 'all' || d.platform === platformTab))
      .slice(0, 10),
    [allDrafts, platformTab])
  const due = useMemo(() => scheduled.filter(isDue), [scheduled])
  const upcoming = useMemo(() => scheduled.filter((d) => !isDue(d)), [scheduled])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['social-drafts'] })

  const publishDueMutation = useMutation({
    mutationFn: () => api.publishDueSocialDrafts(dryRun),
    onSuccess: (data) => {
      if (data.ok) toast.success(dryRun ? 'Dry run complete — nothing posted' : 'Due posts published')
      else toast.error(data.error || 'Publish due failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const retryMutation = useMutation({
    mutationFn: (draftId: string) => api.retrySocialDraft(draftId),
    onMutate: (draftId) => setRetryingId(draftId),
    onSuccess: (data) => {
      setRetryingId(null)
      if (data.ok) toast.success('Reset to approved — ready to publish')
      else toast.error(data.error || 'Retry failed')
      refresh()
    },
    onError: (err: Error) => { setRetryingId(null); toast.error(err.message) },
  })

  const searchMutation = useMutation({
    mutationFn: () => api.runIntelligence({ topic, include_seen: includeSeen }),
    onSuccess: (data) => {
      const count = data.cards?.length || 0
      setLastCount(count)
      toast.success(`Intelligence complete · ${data.total ?? count} stories`)
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const saveSnapshotMutation = useMutation({
    mutationFn: api.saveSnapshot,
    onSuccess: (data) => {
      if (data.ok) toast.success(`Snapshot saved${data.name ? `: ${data.name}` : ''}`)
      else toast.error(data.error || 'Snapshot failed')
    },
    onError: (err: Error) => toast.error(err.message),
  })

  if (socialQuery.isLoading) return <SchedulerSkeleton />

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Scheduler</h1>
          <p className="text-muted-foreground">Manage scheduled posts, retry failures, and run intelligence.</p>
        </div>
        <Button variant="outline" onClick={refresh}>
          <RefreshCw className="h-4 w-4 mr-1" />Refresh
        </Button>
      </div>

      {socialQuery.error && (
        <Card className="border-destructive/50">
          <CardContent className="pt-6 text-destructive">{(socialQuery.error as Error).message}</CardContent>
        </Card>
      )}

      {/* Summary row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricCard label="Scheduled" value={allDrafts.filter((d) => d.status === 'scheduled').length} icon={CalendarClock} />
        <MetricCard label="Due Now" value={allDrafts.filter((d) => d.status === 'scheduled' && isDue(d)).length} icon={Clock} accent="amber" />
        <MetricCard label="Failed" value={allDrafts.filter((d) => d.status === 'failed').length} icon={AlertTriangle} accent="red" />
        <MetricCard label="Published" value={allDrafts.filter((d) => d.status === 'published').length} icon={CheckCircle2} accent="emerald" />
      </div>

      {/* Platform tabs */}
      <div className="flex flex-wrap gap-1">
        {PLATFORMS.map((p) => (
          <Button
            key={p}
            size="sm"
            variant={platformTab === p ? 'default' : 'ghost'}
            className="capitalize h-7 text-xs"
            onClick={() => setPlatformTab(p)}
          >
            {p}
          </Button>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          {/* Due now */}
          {due.length > 0 && (
            <Card className="border-amber-500/30">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2 text-amber-400">
                  <Clock className="h-4 w-4" />Due Now ({due.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {due.map((d) => <DraftRow key={d.draft_id} draft={d} />)}
              </CardContent>
            </Card>
          )}

          {/* Upcoming */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <CalendarClock className="h-4 w-4" />Upcoming ({upcoming.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              {upcoming.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No upcoming scheduled posts{platformTab !== 'all' ? ` for ${platformTab}` : ''}.
                </p>
              ) : (
                <div className="space-y-2">
                  {upcoming.map((d) => <DraftRow key={d.draft_id} draft={d} />)}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Failed */}
          {failed.length > 0 && (
            <Card className="border-red-500/30">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2 text-red-400">
                  <AlertTriangle className="h-4 w-4" />Failed ({failed.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {failed.map((d) => (
                  <DraftRow
                    key={d.draft_id}
                    draft={d}
                    onRetry={() => retryMutation.mutate(d.draft_id)}
                    retrying={retryingId === d.draft_id}
                  />
                ))}
              </CardContent>
            </Card>
          )}

          {/* Recent published */}
          {published.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />Recent Wins ({published.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {published.map((d) => <DraftRow key={d.draft_id} draft={d} />)}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right panel */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Send className="h-4 w-4" />Publish Due
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm text-muted-foreground">Dry run (safe preview)</span>
                <Switch checked={dryRun} onCheckedChange={setDryRun} />
              </div>
              {!dryRun && (
                <p className="text-xs text-orange-400">
                  Live mode — will publish to real platforms.
                </p>
              )}
              <Button
                className="w-full"
                onClick={() => publishDueMutation.mutate()}
                disabled={publishDueMutation.isPending || due.length === 0}
              >
                {publishDueMutation.isPending
                  ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  : <Send className="h-4 w-4 mr-1" />}
                {dryRun ? 'Dry Run' : 'Publish'} {due.length} Due
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Search className="h-4 w-4" />Intelligence Search
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Topic" />
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm text-muted-foreground">Include seen stories</span>
                <Switch checked={includeSeen} onCheckedChange={setIncludeSeen} />
              </div>
              <div className="flex gap-2">
                <Button className="flex-1" onClick={() => searchMutation.mutate()} disabled={searchMutation.isPending}>
                  {searchMutation.isPending
                    ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                    : <Search className="h-4 w-4 mr-1" />}
                  Search
                </Button>
                <Button
                  variant="outline"
                  onClick={() => saveSnapshotMutation.mutate()}
                  disabled={lastCount === null || saveSnapshotMutation.isPending}
                >
                  <Save className="h-4 w-4" />
                </Button>
              </div>
              {lastCount !== null && (
                <p className="text-xs text-muted-foreground">Last run: {lastCount} cards</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function MetricCard({ label, value, icon: Icon, accent }: {
  label: string; value: number; icon: React.ElementType; accent?: string
}) {
  const color = accent === 'red' ? 'text-red-400' : accent === 'amber' ? 'text-amber-400' : accent === 'emerald' ? 'text-emerald-400' : 'text-primary'
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-4">
        <Icon className={`h-5 w-5 ${color}`} />
        <div>
          <div className="text-2xl font-bold">{value}</div>
          <div className="text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function SchedulerSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-20" /><Skeleton className="h-28" /><Skeleton className="h-96" />
    </div>
  )
}
