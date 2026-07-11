import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { CalendarClock, CheckSquare, RefreshCw, Save, Send } from 'lucide-react'

import { api } from '@/api/client'
import type { SocialDraftStatus } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

const statuses: SocialDraftStatus[] = ['idea', 'draft', 'needs_review', 'approved', 'scheduled', 'published', 'failed']

interface SocialForm {
  title: string
  text: string
  description: string
  status: SocialDraftStatus
  hashtags: string
}

const emptyForm: SocialForm = { title: '', text: '', description: '', status: 'draft', hashtags: '' }

export default function SocialPage() {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [activeId, setActiveId] = useState('')
  const [statusFilter, setStatusFilter] = useState<SocialDraftStatus | 'all'>('all')
  const [scheduledAt, setScheduledAt] = useState('')
  const [dryRun, setDryRun] = useState(true)
  const [form, setForm] = useState<SocialForm>(emptyForm)

  const draftsQuery = useQuery({ queryKey: ['social-drafts'], queryFn: api.getSocialDrafts })
  const allDrafts = useMemo(() => draftsQuery.data || [], [draftsQuery.data])
  const drafts = statusFilter === 'all' ? allDrafts : allDrafts.filter((draft) => draft.status === statusFilter)
  const activeDraft = allDrafts.find((draft) => draft.draft_id === activeId) || drafts[0] || allDrafts[0]
  const selectedDrafts = allDrafts.filter((draft) => selectedIds.includes(draft.draft_id))

  useEffect(() => {
    if (!activeDraft) {
      setForm(emptyForm)
      return
    }
    setActiveId(activeDraft.draft_id)
    setForm({
      title: activeDraft.title || '',
      text: activeDraft.text || '',
      description: activeDraft.description || '',
      status: activeDraft.status || 'draft',
      hashtags: (activeDraft.hashtags || []).join(', '),
    })
  }, [activeDraft])

  const counts = useMemo(() => {
    return statuses.reduce<Record<SocialDraftStatus, number>>((acc, status) => {
      acc[status] = allDrafts.filter((draft) => draft.status === status).length
      return acc
    }, { idea: 0, draft: 0, needs_review: 0, approved: 0, scheduled: 0, published: 0, failed: 0 })
  }, [allDrafts])

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['social-drafts'] })

  const saveMutation = useMutation({
    mutationFn: () => api.saveSocialDraft(activeDraft.draft_id, {
      title: form.title,
      text: form.text,
      description: form.description,
      status: form.status,
      hashtags: form.hashtags.split(',').map((tag) => tag.trim()).filter(Boolean),
    }),
    onSuccess: (data) => {
      if (data.ok) toast.success('Social draft saved')
      else toast.error(data.error || 'Save failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const scheduleMutation = useMutation({
    mutationFn: () => api.scheduleSocialDrafts(selectedIds, new Date(scheduledAt).toISOString()),
    onSuccess: (data) => {
      if (data.ok) toast.success('Schedule updated')
      else toast.error(data.error || 'Schedule failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const publishMutation = useMutation({
    mutationFn: () => api.publishSocialDrafts(selectedIds, dryRun),
    onSuccess: (data) => {
      if (data.ok) toast.success(dryRun ? 'Dry run complete' : 'Publish complete')
      else toast.error(data.error || 'Publish failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const toggleSelected = (id: string) => {
    setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])
  }

  const canSchedule = selectedDrafts.length > 0 && selectedDrafts.every((draft) => draft.status === 'approved') && !!scheduledAt
  const canPublish = selectedDrafts.length > 0 && selectedDrafts.every((draft) => draft.status === 'approved' || draft.status === 'scheduled')

  if (draftsQuery.isLoading) return <SocialSkeleton />

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Social Drafts</h1>
          <p className="text-muted-foreground">Approve, schedule, and publish platform-native posts.</p>
        </div>
        <Button variant="outline" onClick={refresh}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      {draftsQuery.error && <ErrorCard message={(draftsQuery.error as Error).message} />}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        {statuses.map((status) => (
          <button key={status} type="button" onClick={() => setStatusFilter(status)} className="text-left">
            <Card className={statusFilter === status ? 'border-primary bg-primary/5' : ''}>
              <CardContent className="p-4">
                <div className="text-2xl font-bold">{counts[status]}</div>
                <div className="text-xs capitalize text-muted-foreground">{status.replace('_', ' ')}</div>
              </CardContent>
            </Card>
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 pt-6">
          <Field label="Filter">
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as SocialDraftStatus | 'all')}
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="all">all</option>
              {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
            </select>
          </Field>
          <Field label="Schedule selected">
            <Input type="datetime-local" value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
          </Field>
          <Button variant="outline" onClick={() => scheduleMutation.mutate()} disabled={!canSchedule || scheduleMutation.isPending}>
            <CalendarClock className="h-4 w-4 mr-1" />
            Schedule
          </Button>
          <div className="flex items-center gap-2 rounded-md border px-3 py-2">
            <Switch checked={dryRun} onCheckedChange={setDryRun} />
            <span className="text-sm text-muted-foreground">Dry run</span>
          </div>
          <Button onClick={() => publishMutation.mutate()} disabled={!canPublish || publishMutation.isPending}>
            <Send className="h-4 w-4 mr-1" />
            Publish Selected
          </Button>
        </CardContent>
      </Card>

      {allDrafts.length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-center text-muted-foreground">
            No social drafts yet. Publish a content draft first, then generate social drafts from Drafts.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <CheckSquare className="h-4 w-4" />
                Queue
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {drafts.map((draft) => (
                <div key={draft.draft_id} className={`rounded-lg border p-3 ${draft.draft_id === activeDraft?.draft_id ? 'border-primary bg-primary/5' : ''}`}>
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(draft.draft_id)}
                      onChange={() => toggleSelected(draft.draft_id)}
                      className="mt-1"
                    />
                    <button type="button" onClick={() => setActiveId(draft.draft_id)} className="min-w-0 flex-1 text-left">
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate font-medium">{draft.title || 'Untitled social draft'}</div>
                        <Badge variant="outline" className="capitalize">{draft.status}</Badge>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">{draft.platform} · {draft.draft_id}</div>
                    </button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {activeDraft && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center justify-between gap-3">
                  <span className="truncate capitalize">{activeDraft.platform} Post</span>
                  <Badge variant="secondary" className="capitalize">{activeDraft.status}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 lg:grid-cols-[1fr_180px]">
                  <Field label="Title">
                    <Input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} />
                  </Field>
                  <Field label="Status">
                    <select
                      value={form.status}
                      onChange={(event) => setForm((current) => ({ ...current, status: event.target.value as SocialDraftStatus }))}
                      className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                    >
                      {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
                    </select>
                  </Field>
                </div>
                <Field label="Post Text">
                  <textarea
                    value={form.text}
                    onChange={(event) => setForm((current) => ({ ...current, text: event.target.value }))}
                    className="min-h-[220px] w-full rounded-md border border-input bg-background p-3 text-sm"
                  />
                </Field>
                <div className="grid gap-3 lg:grid-cols-2">
                  <Field label="Description">
                    <textarea
                      value={form.description}
                      onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
                      className="min-h-[120px] w-full rounded-md border border-input bg-background p-3 text-sm"
                    />
                  </Field>
                  <Field label="Hashtags">
                    <textarea
                      value={form.hashtags}
                      onChange={(event) => setForm((current) => ({ ...current, hashtags: event.target.value }))}
                      className="min-h-[120px] w-full rounded-md border border-input bg-background p-3 text-sm"
                    />
                  </Field>
                </div>
                {activeDraft.scheduled_at && <div className="text-sm text-muted-foreground">Scheduled: {formatDate(activeDraft.scheduled_at)}</div>}
                {activeDraft.error && <div className="text-sm text-destructive">{activeDraft.error}</div>}
                <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
                  <Save className="h-4 w-4 mr-1" />
                  Save
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function SocialSkeleton() {
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
