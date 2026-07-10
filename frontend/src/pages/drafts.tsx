import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ExternalLink, FileText, Megaphone, RefreshCw, Save, Send } from 'lucide-react'

import { api } from '@/api/client'
import type { ContentDraftStatus } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

const statuses: ContentDraftStatus[] = ['draft', 'reviewed', 'approved', 'published']
const platforms = ['linkedin', 'facebook', 'x', 'threads', 'reddit', 'newsletter', 'youtube']

interface DraftForm {
  title: string
  slug: string
  status: ContentDraftStatus
  body: string
}

const emptyForm: DraftForm = { title: '', slug: '', status: 'draft', body: '' }

export default function DraftsPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState<DraftForm>(emptyForm)
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['linkedin', 'newsletter'])

  const draftsQuery = useQuery({ queryKey: ['drafts'], queryFn: api.getDrafts })
  const drafts = useMemo(() => draftsQuery.data || [], [draftsQuery.data])
  const selectedDraft = drafts.find((draft) => draft.draft_id === selectedId) || drafts[0]

  useEffect(() => {
    if (!selectedDraft) {
      setForm(emptyForm)
      return
    }
    setSelectedId(selectedDraft.draft_id)
    setForm({
      title: selectedDraft.title || '',
      slug: selectedDraft.slug || '',
      status: selectedDraft.status || 'draft',
      body: selectedDraft.body || '',
    })
  }, [selectedDraft])

  const counts = useMemo(() => {
    return statuses.reduce<Record<ContentDraftStatus, number>>((acc, status) => {
      acc[status] = drafts.filter((draft) => draft.status === status).length
      return acc
    }, { draft: 0, reviewed: 0, approved: 0, published: 0 })
  }, [drafts])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['drafts'] })
    queryClient.invalidateQueries({ queryKey: ['social-drafts'] })
  }

  const saveMutation = useMutation({
    mutationFn: () => api.saveDraft(selectedDraft.draft_id, form),
    onSuccess: (data) => {
      if (data.ok) toast.success('Draft saved')
      else toast.error(data.error || 'Save failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const publishMutation = useMutation({
    mutationFn: () => api.publishBlog(selectedDraft.draft_id),
    onSuccess: (data) => {
      if (data.ok) toast.success('Blog published')
      else toast.error(data.error || 'Publish failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const socialMutation = useMutation({
    mutationFn: () => api.createSocialDrafts(selectedDraft.draft_id, selectedPlatforms),
    onSuccess: (data) => {
      if (data.ok) toast.success(`Created ${data.drafts?.length || 0} social drafts`)
      else toast.error(data.error || 'Social draft failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const togglePlatform = (platform: string) => {
    setSelectedPlatforms((current) =>
      current.includes(platform) ? current.filter((item) => item !== platform) : [...current, platform]
    )
  }

  if (draftsQuery.isLoading) {
    return <DraftsSkeleton />
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Drafts</h1>
          <p className="text-muted-foreground">Review content drafts and turn published posts into social drafts.</p>
        </div>
        <Button variant="outline" onClick={refresh}>
          <RefreshCw className="h-4 w-4 mr-1" />
          Refresh
        </Button>
      </div>

      {draftsQuery.error && <ErrorCard message={(draftsQuery.error as Error).message} />}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {statuses.map((status) => (
          <Card key={status}>
            <CardContent className="p-4">
              <div className="text-2xl font-bold">{counts[status]}</div>
              <div className="text-xs capitalize text-muted-foreground">{status}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {drafts.length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-center text-muted-foreground">
            No JSON drafts yet. Create one from an Intelligence card after generating a brief.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="h-4 w-4" />
                Draft Queue
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {drafts.map((draft) => (
                <button
                  key={draft.draft_id}
                  type="button"
                  onClick={() => setSelectedId(draft.draft_id)}
                  className={`w-full rounded-lg border p-3 text-left transition hover:border-primary ${draft.draft_id === selectedDraft?.draft_id ? 'border-primary bg-primary/5' : 'border-border bg-card'}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 truncate font-medium">{draft.title || 'Untitled draft'}</div>
                    <Badge variant="outline" className="capitalize">{draft.status}</Badge>
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">{draft.draft_id} · {draft.content_type}</div>
                </button>
              ))}
            </CardContent>
          </Card>

          {selectedDraft && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center justify-between gap-3">
                  <span className="truncate">{selectedDraft.title || 'Untitled draft'}</span>
                  {selectedDraft.blog_url && (
                    <Button size="sm" variant="ghost" asChild>
                      <a href={selectedDraft.blog_url} target="_blank" rel="noreferrer">
                        <ExternalLink className="h-4 w-4 mr-1" />
                        Open
                      </a>
                    </Button>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 lg:grid-cols-[1fr_220px_160px]">
                  <Field label="Title">
                    <Input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} />
                  </Field>
                  <Field label="Slug">
                    <Input value={form.slug} onChange={(event) => setForm((current) => ({ ...current, slug: event.target.value }))} />
                  </Field>
                  <Field label="Status">
                    <select
                      value={form.status}
                      onChange={(event) => setForm((current) => ({ ...current, status: event.target.value as ContentDraftStatus }))}
                      className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                    >
                      {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
                    </select>
                  </Field>
                </div>

                <Field label="Body">
                  <textarea
                    value={form.body}
                    onChange={(event) => setForm((current) => ({ ...current, body: event.target.value }))}
                    className="min-h-[360px] w-full rounded-md border border-input bg-background p-3 font-mono text-sm"
                  />
                </Field>

                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
                    <Save className="h-4 w-4 mr-1" />
                    Save
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => publishMutation.mutate()}
                    disabled={publishMutation.isPending || form.status !== 'approved'}
                  >
                    <Send className="h-4 w-4 mr-1" />
                    Publish Blog
                  </Button>
                </div>

                <div className="rounded-lg border p-3">
                  <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                    <Megaphone className="h-4 w-4" />
                    Social Drafts
                  </div>
                  <div className="mb-3 flex flex-wrap gap-2">
                    {platforms.map((platform) => (
                      <Button
                        key={platform}
                        type="button"
                        size="sm"
                        variant={selectedPlatforms.includes(platform) ? 'default' : 'outline'}
                        onClick={() => togglePlatform(platform)}
                        className="capitalize"
                      >
                        {platform}
                      </Button>
                    ))}
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => socialMutation.mutate()}
                    disabled={socialMutation.isPending || selectedDraft.status !== 'published' || !selectedDraft.blog_url || selectedPlatforms.length === 0}
                  >
                    Generate Social Drafts
                  </Button>
                </div>
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

function DraftsSkeleton() {
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
