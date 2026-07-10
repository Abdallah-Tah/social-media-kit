import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CalendarClock, RefreshCw, Save, Search, Send } from 'lucide-react'

import { api } from '@/api/client'
import type { SocialDraft } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

export default function SchedulerPage() {
  const queryClient = useQueryClient()
  const [dryRun, setDryRun] = useState(true)
  const [topic, setTopic] = useState('AI')
  const [includeSeen, setIncludeSeen] = useState(false)
  const [lastSearchCount, setLastSearchCount] = useState<number | null>(null)

  const socialQuery = useQuery({ queryKey: ['social-drafts'], queryFn: api.getSocialDrafts })
  const socialDrafts = useMemo(() => socialQuery.data || [], [socialQuery.data])

  const scheduled = useMemo(() => socialDrafts.filter((draft) => draft.status === 'scheduled'), [socialDrafts])
  const due = useMemo(() => scheduled.filter(isDue), [scheduled])
  const upcoming = useMemo(() => scheduled.filter((draft) => !isDue(draft)), [scheduled])

  const refreshSocial = () => queryClient.invalidateQueries({ queryKey: ['social-drafts'] })

  const publishDueMutation = useMutation({
    mutationFn: () => api.publishDueSocialDrafts(dryRun),
    onSuccess: (data) => {
      if (data.ok) toast.success(dryRun ? 'Due dry run complete' : 'Due posts published')
      else toast.error(data.error || 'Publish due failed')
      refreshSocial()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const searchMutation = useMutation({
    mutationFn: () => api.runIntelligence({ topic, include_seen: includeSeen }),
    onSuccess: (data) => {
      const count = data.cards?.length || 0
      setLastSearchCount(count)
      toast.success(`Intelligence search complete · ${data.total ?? count} stories`)
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
          <p className="text-muted-foreground">Run searches and process scheduled social posts.</p>
        </div>
        <Button variant="outline" onClick={refreshSocial}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      {socialQuery.error && <ErrorCard message={(socialQuery.error as Error).message} />}

      <div className="grid gap-4 lg:grid-cols-3">
        <Metric label="Scheduled" value={scheduled.length} />
        <Metric label="Due Now" value={due.length} />
        <Metric label="Upcoming" value={upcoming.length} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <CalendarClock className="h-4 w-4" />
              Scheduled Queue
            </CardTitle>
          </CardHeader>
          <CardContent>
            {scheduled.length === 0 ? (
              <div className="text-center text-muted-foreground">No scheduled social drafts.</div>
            ) : (
              <div className="space-y-2">
                {scheduled.map((draft) => (
                  <div key={draft.draft_id} className="rounded-lg border p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-medium">{draft.title || 'Untitled social draft'}</div>
                        <div className="text-xs text-muted-foreground">{draft.platform} · {formatDate(draft.scheduled_at)}</div>
                      </div>
                      <Badge variant={isDue(draft) ? 'default' : 'outline'}>{isDue(draft) ? 'due' : 'upcoming'}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Send className="h-4 w-4" />
                Due Publisher
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm text-muted-foreground">Dry run</span>
                <Switch checked={dryRun} onCheckedChange={setDryRun} />
              </div>
              <Button className="w-full" onClick={() => publishDueMutation.mutate()} disabled={publishDueMutation.isPending || due.length === 0}>
                {publishDueMutation.isPending ? <RefreshCw className="h-4 w-4 mr-1 animate-spin" /> : <Send className="h-4 w-4 mr-1" />}
                Publish Due
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Search className="h-4 w-4" />
                Intelligence Search
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Topic" />
              <div className="flex items-center justify-between rounded-md border px-3 py-2">
                <span className="text-sm text-muted-foreground">Include seen stories</span>
                <Switch checked={includeSeen} onCheckedChange={setIncludeSeen} />
              </div>
              <div className="flex gap-2">
                <Button className="flex-1" onClick={() => searchMutation.mutate()} disabled={searchMutation.isPending}>
                  {searchMutation.isPending ? <RefreshCw className="h-4 w-4 mr-1 animate-spin" /> : <Search className="h-4 w-4 mr-1" />}
                  Search
                </Button>
                <Button variant="outline" onClick={() => saveSnapshotMutation.mutate()} disabled={lastSearchCount === null || saveSnapshotMutation.isPending}>
                  <Save className="h-4 w-4 mr-1" />
                  Save
                </Button>
              </div>
              {lastSearchCount !== null && <div className="text-sm text-muted-foreground">Last search cards: {lastSearchCount}</div>}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function isDue(draft: SocialDraft) {
  if (!draft.scheduled_at) return false
  const scheduledAt = new Date(draft.scheduled_at)
  return !Number.isNaN(scheduledAt.getTime()) && scheduledAt.getTime() <= Date.now()
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-2xl font-bold">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </CardContent>
    </Card>
  )
}

function SchedulerSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-20" />
      <Skeleton className="h-28" />
      <Skeleton className="h-96" />
    </div>
  )
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card className="border-destructive/50">
      <CardContent className="pt-6 text-destructive">{message}</CardContent>
    </Card>
  )
}
