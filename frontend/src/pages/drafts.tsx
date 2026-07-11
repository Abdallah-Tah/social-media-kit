import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ExternalLink, FileText, Megaphone, RefreshCw, Save, Send,
  Eye, Code2, ImageIcon, Wand2, Loader2, Info,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'

import { api } from '@/api/client'
import type { ContentDraft, ContentDraftStatus } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'

const statuses: ContentDraftStatus[] = ['idea', 'draft', 'needs_review', 'approved', 'published']
const editableStatuses: ContentDraftStatus[] = ['idea', 'draft', 'needs_review', 'approved']
const platforms = ['linkedin', 'facebook', 'x', 'threads', 'reddit', 'newsletter', 'youtube']
const REWRITE_MODES = [
  { mode: 'shorter' as const, label: 'Shorter' },
  { mode: 'hook' as const, label: 'Stronger Hook' },
  { mode: 'technical' as const, label: 'More Technical' },
  { mode: 'casual' as const, label: 'More Casual' },
]
const COVER_STYLES = ['clean_tech', 'editorial', 'diagram', 'thumbnail', 'social_card']
const PLATFORM_CROPS: Record<string, string> = {
  Blog: '3/2',
  LinkedIn: '1.91/1',
  X: '2/1',
  YouTube: '16/9',
}

interface DraftForm {
  title: string
  slug: string
  status: ContentDraftStatus
  body: string
  seo_title: string
  seo_description: string
}

const emptyForm: DraftForm = { title: '', slug: '', status: 'draft', body: '', seo_title: '', seo_description: '' }

function statusBadgeClass(status: ContentDraftStatus) {
  if (status === 'published') return 'border-emerald-500 text-emerald-400'
  if (status === 'approved') return 'border-blue-500 text-blue-400'
  if (status === 'needs_review') return 'border-amber-500 text-amber-400'
  if (status === 'idea') return 'border-slate-500 text-slate-400'
  return ''
}

function publishDisabledReason(draft: ContentDraft | undefined, formStatus: ContentDraftStatus): string | null {
  if (!draft) return 'No draft selected'
  if (formStatus !== 'approved') return `Status must be "approved" (current: ${formStatus.replace('_', ' ')})`
  return null
}

export default function DraftsPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState<DraftForm>(emptyForm)
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['linkedin', 'newsletter'])
  const [bodyTab, setBodyTab] = useState<'edit' | 'preview'>('edit')
  const [coverStyle, setCoverStyle] = useState('clean_tech')

  const draftsQuery = useQuery({ queryKey: ['drafts'], queryFn: api.getDrafts })
  const drafts = useMemo(() => draftsQuery.data || [], [draftsQuery.data])
  const selectedDraft = drafts.find((d) => d.draft_id === selectedId) || drafts[0]

  // Cover info for the selected draft
  const coverQuery = useQuery({
    queryKey: ['draft-cover', selectedDraft?.draft_id],
    queryFn: () => api.getDraftCover(selectedDraft!.draft_id),
    enabled: !!selectedDraft,
    staleTime: 30_000,
  })

  useEffect(() => {
    if (!selectedDraft) { setForm(emptyForm); return }
    setSelectedId(selectedDraft.draft_id)
    setForm({
      title: selectedDraft.title || '',
      slug: selectedDraft.slug || '',
      status: selectedDraft.status || 'draft',
      body: selectedDraft.body || '',
      seo_title: (selectedDraft as any).seo_title || '',
      seo_description: (selectedDraft as any).seo_description || '',
    })
  }, [selectedDraft])

  const counts = useMemo(() => {
    return statuses.reduce<Record<ContentDraftStatus, number>>((acc, s) => {
      acc[s] = drafts.filter((d) => d.status === s).length
      return acc
    }, { idea: 0, draft: 0, needs_review: 0, approved: 0, published: 0 })
  }, [drafts])

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['drafts'] })
    queryClient.invalidateQueries({ queryKey: ['social-drafts'] })
    queryClient.invalidateQueries({ queryKey: ['draft-cover', selectedDraft?.draft_id] })
  }

  const saveMutation = useMutation({
    mutationFn: () => api.saveDraft(selectedDraft!.draft_id, {
      title: form.title,
      slug: form.slug,
      status: form.status,
      body: form.body,
      seo_title: form.seo_title,
      seo_description: form.seo_description,
    } as Partial<ContentDraft>),
    onSuccess: (data) => {
      if (data.ok) toast.success('Draft saved')
      else toast.error(data.error || 'Save failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const publishMutation = useMutation({
    mutationFn: () => api.publishBlog(selectedDraft!.draft_id),
    onSuccess: (data) => {
      if (data.ok) toast.success('Blog published')
      else toast.error(data.error || 'Publish failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const socialMutation = useMutation({
    mutationFn: () => api.createSocialDrafts(selectedDraft!.draft_id, selectedPlatforms),
    onSuccess: (data) => {
      if (data.ok) toast.success(`Created ${data.drafts?.length || 0} social drafts`)
      else toast.error(data.error || 'Social draft failed')
      refresh()
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const rewriteMutation = useMutation({
    mutationFn: (mode: 'shorter' | 'hook' | 'technical' | 'casual') =>
      api.rewriteDraft(selectedDraft!.draft_id, mode),
    onSuccess: (data) => {
      if (data.ok && data.body) {
        setForm((f) => ({ ...f, body: data.body! }))
        toast.success(`Rewritten (${data.mode}) — review and save`)
      } else {
        toast.error(data.error || 'Rewrite failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const coverMutation = useMutation({
    mutationFn: (style: string) => api.regenerateCover(selectedDraft!.draft_id, style),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success('Cover generated')
        queryClient.invalidateQueries({ queryKey: ['draft-cover', selectedDraft?.draft_id] })
      } else {
        toast.error(data.error || 'Cover generation failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const togglePlatform = (p: string) =>
    setSelectedPlatforms((cur) => cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p])

  const publishReason = publishDisabledReason(selectedDraft, form.status)

  if (draftsQuery.isLoading) return <DraftsSkeleton />

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Drafts</h1>
          <p className="text-muted-foreground">Edit drafts, generate covers, and push to social.</p>
        </div>
        <Button variant="outline" onClick={refresh}>
          <RefreshCw className="h-4 w-4 mr-1" />Refresh
        </Button>
      </div>

      {draftsQuery.error && <ErrorCard message={(draftsQuery.error as Error).message} />}

      {/* Status counts */}
      <div className="grid grid-cols-3 gap-3 lg:grid-cols-5">
        {statuses.map((s) => (
          <Card key={s}>
            <CardContent className="p-4">
              <div className="text-2xl font-bold">{counts[s]}</div>
              <div className="text-xs capitalize text-muted-foreground">{s.replace('_', ' ')}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {drafts.length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-center text-muted-foreground">
            No drafts yet. Create one from an Intelligence card after generating a brief.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
          {/* Draft list */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="h-4 w-4" />Draft Queue
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {drafts.map((draft) => (
                <button
                  key={draft.draft_id}
                  type="button"
                  onClick={() => setSelectedId(draft.draft_id)}
                  className={`w-full rounded-lg border p-3 text-left transition hover:border-primary ${
                    draft.draft_id === selectedDraft?.draft_id ? 'border-primary bg-primary/5' : 'border-border bg-card'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 truncate font-medium">{draft.title || 'Untitled'}</div>
                    <Badge variant="outline" className={`capitalize shrink-0 ${statusBadgeClass(draft.status)}`}>
                      {draft.status.replace('_', ' ')}
                    </Badge>
                  </div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {draft.draft_id} · {draft.content_type}
                  </div>
                </button>
              ))}
            </CardContent>
          </Card>

          {selectedDraft && (
            <div className="space-y-4">
              {/* Editor card */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base flex items-center justify-between gap-3">
                    <span className="truncate">{selectedDraft.title || 'Untitled draft'}</span>
                    {selectedDraft.blog_url && (
                      <Button size="sm" variant="ghost" asChild>
                        <a href={selectedDraft.blog_url} target="_blank" rel="noreferrer">
                          <ExternalLink className="h-4 w-4 mr-1" />Open
                        </a>
                      </Button>
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Core fields */}
                  <div className="grid gap-3 lg:grid-cols-[1fr_200px_160px]">
                    <Field label="Title">
                      <Input value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
                    </Field>
                    <Field label="Slug">
                      <Input value={form.slug} onChange={(e) => setForm((f) => ({ ...f, slug: e.target.value }))} />
                    </Field>
                    <Field label="Status">
                      <select
                        value={form.status}
                        onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as ContentDraftStatus }))}
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                      >
                        {(form.status === 'published' ? statuses : editableStatuses).map((s) => (
                          <option key={s} value={s} disabled={s === 'published'}>{s.replace('_', ' ')}</option>
                        ))}
                      </select>
                    </Field>
                  </div>

                  {/* SEO fields */}
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="SEO title">
                      <Input
                        value={form.seo_title}
                        placeholder="Leave blank to use main title"
                        onChange={(e) => setForm((f) => ({ ...f, seo_title: e.target.value }))}
                      />
                    </Field>
                    <Field label="SEO meta description">
                      <Input
                        value={form.seo_description}
                        placeholder="160-char summary for search engines"
                        onChange={(e) => setForm((f) => ({ ...f, seo_description: e.target.value }))}
                      />
                    </Field>
                  </div>

                  {/* Source links */}
                  {(selectedDraft.source_urls?.length ?? 0) > 0 && (
                    <div className="rounded-lg border bg-muted/20 p-3">
                      <p className="mb-2 text-xs font-medium text-muted-foreground">Source links</p>
                      <div className="flex flex-col gap-1">
                        {selectedDraft.source_urls!.slice(0, 5).map((url, i) => (
                          <a key={i} href={url} target="_blank" rel="noreferrer"
                            className="truncate text-xs text-blue-400 hover:underline">
                            {url}
                          </a>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Body editor with preview toggle */}
                  <div>
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">Body (markdown)</span>
                      <div className="flex gap-1">
                        <Button
                          size="sm" variant={bodyTab === 'edit' ? 'secondary' : 'ghost'}
                          className="h-7 px-2 text-xs"
                          onClick={() => setBodyTab('edit')}
                        >
                          <Code2 className="h-3 w-3 mr-1" />Edit
                        </Button>
                        <Button
                          size="sm" variant={bodyTab === 'preview' ? 'secondary' : 'ghost'}
                          className="h-7 px-2 text-xs"
                          onClick={() => setBodyTab('preview')}
                        >
                          <Eye className="h-3 w-3 mr-1" />Preview
                        </Button>
                      </div>
                    </div>
                    {bodyTab === 'edit' ? (
                      <textarea
                        value={form.body}
                        onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
                        className="min-h-[320px] w-full rounded-md border border-input bg-background p-3 font-mono text-sm resize-y"
                      />
                    ) : (
                      <div className="min-h-[320px] rounded-md border border-input bg-background p-4 prose prose-invert prose-sm max-w-none overflow-auto">
                        <ReactMarkdown>{form.body}</ReactMarkdown>
                      </div>
                    )}
                  </div>

                  {/* AI rewrite buttons */}
                  <div className="rounded-lg border p-3 space-y-2">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <Wand2 className="h-4 w-4" />
                      AI Rewrite
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {REWRITE_MODES.map(({ mode, label }) => (
                        <Button
                          key={mode}
                          size="sm"
                          variant="outline"
                          className="text-xs"
                          disabled={rewriteMutation.isPending}
                          onClick={() => rewriteMutation.mutate(mode)}
                        >
                          {rewriteMutation.isPending && rewriteMutation.variables === mode
                            ? <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                            : null}
                          {label}
                        </Button>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Rewrites body in-place. Review the result, then save if happy.
                    </p>
                  </div>

                  {/* Action buttons */}
                  <div className="flex flex-wrap gap-2">
                    <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
                      {saveMutation.isPending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Save className="h-4 w-4 mr-1" />}
                      Save
                    </Button>
                    <div className="relative group">
                      <Button
                        variant="outline"
                        onClick={() => publishMutation.mutate()}
                        disabled={!!publishReason || publishMutation.isPending}
                      >
                        {publishMutation.isPending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Send className="h-4 w-4 mr-1" />}
                        Publish Blog
                      </Button>
                      {publishReason && (
                        <div className="absolute bottom-full left-0 mb-1 hidden group-hover:block z-10
                          rounded bg-popover border border-border px-3 py-1.5 text-xs text-muted-foreground
                          whitespace-nowrap shadow-md">
                          <Info className="inline h-3 w-3 mr-1" />
                          {publishReason}
                        </div>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Cover image panel */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm flex items-center gap-2">
                    <ImageIcon className="h-4 w-4" />Cover Image
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {coverQuery.data?.exists && coverQuery.data.cover_image_url ? (
                    <div className="space-y-3">
                      <img
                        src={coverQuery.data.cover_image_url}
                        alt="Draft cover"
                        className="w-full max-w-sm rounded-lg border object-cover"
                        style={{ aspectRatio: '3/2' }}
                      />
                      {/* Platform crop previews */}
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                        {Object.entries(PLATFORM_CROPS).map(([label, ratio]) => (
                          <div key={label} className="space-y-1">
                            <div className="overflow-hidden rounded border bg-muted"
                              style={{ aspectRatio: ratio }}>
                              <img
                                src={coverQuery.data.cover_image_url}
                                alt={label}
                                className="h-full w-full object-cover"
                              />
                            </div>
                            <p className="text-center text-xs text-muted-foreground">{label}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="flex h-32 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                      No cover image yet
                    </div>
                  )}

                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={coverStyle}
                      onChange={(e) => setCoverStyle(e.target.value)}
                      className="h-9 rounded-md border border-input bg-background px-3 text-xs"
                    >
                      {COVER_STYLES.map((s) => (
                        <option key={s} value={s}>{s.replace('_', ' ')}</option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={coverMutation.isPending}
                      onClick={() => coverMutation.mutate(coverStyle)}
                    >
                      {coverMutation.isPending
                        ? <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                        : <RefreshCw className="h-4 w-4 mr-1" />}
                      {coverQuery.data?.exists ? 'Regenerate' : 'Generate'} Cover
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {/* Social drafts panel */}
              <Card>
                <CardContent className="pt-4 space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Megaphone className="h-4 w-4" />Social Drafts
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {platforms.map((p) => (
                      <Button
                        key={p}
                        type="button"
                        size="sm"
                        variant={selectedPlatforms.includes(p) ? 'default' : 'outline'}
                        onClick={() => togglePlatform(p)}
                        className="capitalize"
                      >
                        {p}
                      </Button>
                    ))}
                  </div>
                  <div className="flex items-center gap-3">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => socialMutation.mutate()}
                      disabled={
                        socialMutation.isPending ||
                        selectedDraft.status !== 'published' ||
                        !selectedDraft.blog_url ||
                        selectedPlatforms.length === 0
                      }
                    >
                      {socialMutation.isPending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
                      Generate Social Drafts
                    </Button>
                    {selectedDraft.status !== 'published' && (
                      <span className="text-xs text-muted-foreground flex items-center gap-1">
                        <Info className="h-3 w-3" />
                        Publish blog first
                      </span>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-2 block">
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
