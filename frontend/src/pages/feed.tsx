import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Newspaper, RefreshCw, ExternalLink, Send, CheckCircle2,
  AlertTriangle, Loader2, Zap, TrendingUp, Clock,
  ImageIcon, Clapperboard, Copy,
} from 'lucide-react'

import { api } from '@/api/client'
import type { FeedItem } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'

const PLATFORMS = ['linkedin', 'facebook', 'x', 'threads', 'reddit', 'newsletter']

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  google_news: { label: 'Google News', color: 'border-blue-500 text-blue-400' },
  hackernews:  { label: 'Hacker News', color: 'border-orange-500 text-orange-400' },
  reddit:      { label: 'Reddit',       color: 'border-red-500 text-red-400' },
  rss:         { label: 'RSS',          color: 'border-emerald-500 text-emerald-400' },
  youtube_rss: { label: 'YouTube',      color: 'border-rose-500 text-rose-400' },
}

function sourceLabel(source: string) {
  if (SOURCE_LABELS[source]) return SOURCE_LABELS[source]
  // Prefix matches: "reddit/r/programming" → Reddit badge with subreddit label.
  if (source.startsWith('reddit')) {
    const sub = source.split('/r/')[1]
    return { label: sub ? `r/${sub}` : 'Reddit', color: SOURCE_LABELS.reddit.color }
  }
  if (source.startsWith('google_news')) return SOURCE_LABELS.google_news
  return { label: source, color: 'border-muted text-muted-foreground' }
}

function fmtAge(iso: string) {
  if (!iso) return ''
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

interface ShortPlan {
  plan_path?: string
  hook?: string
  voiceover?: string
  captions?: string[]
  scenes?: Array<{ kind?: string; title?: string; caption?: string }>
}

function FeedCard({
  item,
  selectedPlatforms,
  onTogglePlatform,
  onPublish,
  isPublishing,
  lastResult,
  onGenerateCover,
  onGenerateShort,
  isGenerating,
  coverUrl,
  shortPlan,
}: {
  item: FeedItem
  selectedPlatforms: string[]
  onTogglePlatform: (p: string) => void
  onPublish: (dryRun: boolean) => void
  isPublishing: boolean
  lastResult: Record<string, { ok: boolean; dry_run?: boolean; published_url?: string; error?: string }> | null
  onGenerateCover: () => void
  onGenerateShort: () => void
  isGenerating: 'cover' | 'short' | null
  coverUrl: string | null
  shortPlan: ShortPlan | null
}) {
  const src = sourceLabel(item.source)
  const score = Math.round(item.score * 100)

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <Badge variant="outline" className={`text-xs ${src.color}`}>{src.label}</Badge>
              {score > 0 && (
                <Badge variant="secondary" className="text-xs">
                  <TrendingUp className="h-2.5 w-2.5 mr-1" />{score}
                </Badge>
              )}
              {item.published_at && (
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock className="h-2.5 w-2.5" />{fmtAge(item.published_at)}
                </span>
              )}
            </div>
            <h3 className="font-semibold leading-snug">{item.title}</h3>
          </div>
          <a href={item.url} target="_blank" rel="noreferrer" className="shrink-0 mt-1">
            <ExternalLink className="h-4 w-4 text-muted-foreground hover:text-foreground" />
          </a>
        </div>

        {/* Summary */}
        {item.summary && (
          <p className="text-sm text-muted-foreground line-clamp-3">{item.summary}</p>
        )}

        {item.reason && (
          <p className="text-xs text-primary/80 italic">Why this matters: {item.reason}</p>
        )}

        {/* Interests */}
        {item.matched_interests.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {item.matched_interests.map((i) => (
              <Badge key={i} variant="secondary" className="text-xs capitalize">{i}</Badge>
            ))}
          </div>
        )}

        {/* Platform selector */}
        <div className="border-t pt-3 space-y-2">
          <p className="text-xs text-muted-foreground font-medium">Post to:</p>
          <div className="flex flex-wrap gap-1.5">
            {PLATFORMS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => onTogglePlatform(p)}
                className={`rounded-md border px-2.5 py-1 text-xs capitalize transition-colors ${
                  selectedPlatforms.includes(p)
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border text-muted-foreground hover:border-primary/50'
                }`}
              >
                {p}
              </button>
            ))}
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button
              size="sm"
              variant="outline"
              className="text-xs"
              disabled={isPublishing || selectedPlatforms.length === 0}
              onClick={() => onPublish(true)}
            >
              {isPublishing ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Zap className="h-3 w-3 mr-1" />}
              Create Drafts
            </Button>
            <Button
              size="sm"
              className="text-xs"
              disabled={isPublishing || selectedPlatforms.length === 0}
              onClick={() => onPublish(false)}
            >
              {isPublishing ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Send className="h-3 w-3 mr-1" />}
              Post Now
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-xs"
              disabled={isGenerating !== null}
              onClick={onGenerateCover}
            >
              {isGenerating === 'cover' ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <ImageIcon className="h-3 w-3 mr-1" />}
              Cover
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="text-xs"
              disabled={isGenerating !== null}
              onClick={onGenerateShort}
            >
              {isGenerating === 'short' ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Clapperboard className="h-3 w-3 mr-1" />}
              Short Script
            </Button>
          </div>

          {/* Generated cover preview */}
          {coverUrl && (
            <img src={coverUrl} alt="Generated cover" className="w-full rounded-lg border object-cover" style={{ aspectRatio: '16/9' }} />
          )}

          {/* Generated Short script */}
          {shortPlan && (
            <div className="rounded-lg border bg-muted/20 p-3 space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium flex items-center gap-1">
                  <Clapperboard className="h-3 w-3" />YouTube Short Script
                </span>
                <button
                  type="button"
                  className="flex items-center gap-1 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    const text = `HOOK: ${shortPlan.hook}\n\nVOICEOVER:\n${shortPlan.voiceover}\n\nCAPTIONS:\n${(shortPlan.captions || []).join('\n')}`
                    navigator.clipboard.writeText(text)
                    toast.success('Script copied')
                  }}
                >
                  <Copy className="h-3 w-3" />Copy
                </button>
              </div>
              {shortPlan.hook && <p><strong>Hook:</strong> {shortPlan.hook}</p>}
              {shortPlan.voiceover && (
                <p className="text-muted-foreground"><strong className="text-foreground">Voiceover:</strong> {shortPlan.voiceover}</p>
              )}
              {(shortPlan.scenes?.length ?? 0) > 0 && (
                <div>
                  <strong>Scenes:</strong>
                  <ol className="ml-4 mt-1 list-decimal space-y-0.5 text-muted-foreground">
                    {shortPlan.scenes!.map((s, i) => (
                      <li key={i}>{s.title || s.kind}{s.caption ? ` — ${s.caption}` : ''}</li>
                    ))}
                  </ol>
                </div>
              )}
              {shortPlan.plan_path && (
                <p className="text-muted-foreground">Saved: <code>{shortPlan.plan_path}</code></p>
              )}
            </div>
          )}

          {/* Results */}
          {lastResult && (
            <div className="rounded-lg border bg-muted/20 p-2 space-y-1">
              {Object.entries(lastResult).map(([platform, r]) => (
                <div key={platform} className="flex items-center justify-between text-xs">
                  <span className="capitalize text-muted-foreground">{platform}</span>
                  <div className="flex items-center gap-1.5">
                    {r.ok
                      ? <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                      : <AlertTriangle className="h-3 w-3 text-red-400" />}
                    {r.ok && r.dry_run && <span className="text-muted-foreground">draft created</span>}
                    {r.ok && !r.dry_run && r.published_url && (
                      <a href={r.published_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">
                        view post
                      </a>
                    )}
                    {!r.ok && <span className="text-red-400">{r.error}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export default function FeedPage() {
  const qc = useQueryClient()
  const [dryRun, setDryRun] = useState(true)
  // Per-item state: selected platforms + last publish result
  const [itemPlatforms, setItemPlatforms] = useState<Record<string, string[]>>({})
  const [itemResults, setItemResults] = useState<Record<string, Record<string, any>>>({})
  const [publishingUrl, setPublishingUrl] = useState<string | null>(null)
  const [itemCovers, setItemCovers] = useState<Record<string, string>>({})
  const [itemShorts, setItemShorts] = useState<Record<string, ShortPlan>>({})
  const [generating, setGenerating] = useState<{ url: string; what: 'cover' | 'short' } | null>(null)

  const feedQuery = useQuery({
    queryKey: ['feed'],
    queryFn: () => api.getFeed(),
    staleTime: 5 * 60_000,
  })

  const runMutation = useMutation({
    mutationFn: () => api.runFeed(false, 20),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success(`Feed refreshed — ${data.count} items fetched`)
        qc.invalidateQueries({ queryKey: ['feed'] })
      } else {
        toast.error(data.error || 'Feed refresh failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const publishMutation = useMutation({
    mutationFn: ({ item, platforms, dry_run }: { item: FeedItem; platforms: string[]; dry_run: boolean }) =>
      api.publishFeedItem(item, platforms, dry_run),
    onMutate: ({ item }) => setPublishingUrl(item.url),
    onSuccess: (data, { item, dry_run }) => {
      setPublishingUrl(null)
      if (data.ok) {
        setItemResults((prev) => ({ ...prev, [item.url]: data.results }))
        const published = Object.values(data.results).filter((r) => r.ok).length
        toast.success(
          dry_run
            ? `${published} social drafts created — check Drafts page`
            : `Posted to ${published} platforms`
        )
      } else {
        toast.error(data.error || 'Publish failed')
      }
    },
    onError: (err: Error) => { setPublishingUrl(null); toast.error(err.message) },
  })

  const coverMutation = useMutation({
    mutationFn: (item: FeedItem) => api.generateFeedCover(item),
    onMutate: (item) => setGenerating({ url: item.url, what: 'cover' }),
    onSuccess: (data, item) => {
      setGenerating(null)
      if (data.ok && data.cover_url) {
        setItemCovers((prev) => ({ ...prev, [item.url]: data.cover_url! }))
        toast.success(`Cover generated (${data.provider || 'local'})`)
      } else {
        toast.error(data.error || 'Cover generation failed')
      }
    },
    onError: (err: Error) => { setGenerating(null); toast.error(err.message) },
  })

  const shortMutation = useMutation({
    mutationFn: (item: FeedItem) => api.generateFeedShort(item),
    onMutate: (item) => setGenerating({ url: item.url, what: 'short' }),
    onSuccess: (data, item) => {
      setGenerating(null)
      if (data.ok) {
        setItemShorts((prev) => ({ ...prev, [item.url]: data }))
        toast.success('Short script ready')
      } else {
        toast.error(data.error || 'Short script failed')
      }
    },
    onError: (err: Error) => { setGenerating(null); toast.error(err.message) },
  })

  function platformsFor(url: string): string[] {
    return itemPlatforms[url] ?? PLATFORMS.slice(0, 3) // default: linkedin, facebook, x
  }

  function togglePlatform(url: string, platform: string) {
    setItemPlatforms((prev) => {
      const current = prev[url] ?? PLATFORMS.slice(0, 3)
      const next = current.includes(platform)
        ? current.filter((p) => p !== platform)
        : [...current, platform]
      return { ...prev, [url]: next }
    })
  }

  const snapshot = feedQuery.data
  const items = snapshot?.items ?? []
  const lastUpdated = snapshot?.generated_at

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Newspaper className="h-6 w-6" />News Feed
          </h1>
          <p className="text-muted-foreground">
            Google News · Hacker News · Reddit — select stories and post to social.
            {lastUpdated && (
              <span className="ml-2 text-xs">Last updated {fmtAge(lastUpdated)}</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
            <Switch checked={dryRun} onCheckedChange={setDryRun} />
            <span className={!dryRun ? 'text-orange-400 font-medium' : ''}>
              {dryRun ? 'Create drafts' : 'Post live'}
            </span>
          </label>
          <Button onClick={() => runMutation.mutate()} disabled={runMutation.isPending}>
            {runMutation.isPending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
            Refresh Feed
          </Button>
        </div>
      </div>

      {!dryRun && (
        <div className="rounded-lg border border-orange-500/30 bg-orange-500/5 px-4 py-3 text-sm text-orange-400">
          <AlertTriangle className="inline h-4 w-4 mr-1" />
          <strong>Live mode</strong> — "Post Now" will publish directly to real platforms. Use "Create Drafts" for a safe preview first.
        </div>
      )}

      {/* Feed stats */}
      {snapshot && (
        <div className="flex flex-wrap gap-3 text-sm text-muted-foreground">
          <span><strong className="text-foreground">{items.length}</strong> stories</span>
          {snapshot.snapshots && snapshot.snapshots.length > 1 && (
            <span>{snapshot.snapshots.length} snapshots available</span>
          )}
          {lastUpdated && <span>from {new Date(lastUpdated).toLocaleString()}</span>}
        </div>
      )}

      {feedQuery.isLoading && (
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => <Skeleton key={i} className="h-48" />)}
        </div>
      )}

      {!feedQuery.isLoading && items.length === 0 && (
        <Card>
          <CardContent className="pt-8 pb-8 text-center space-y-3">
            <Newspaper className="h-10 w-10 text-muted-foreground mx-auto" />
            <p className="text-muted-foreground">No feed items yet.</p>
            <p className="text-sm text-muted-foreground">
              Click <strong>Refresh Feed</strong> to fetch the latest stories from Google News, Hacker News, and Reddit.
            </p>
            <p className="text-xs text-muted-foreground">
              Or enable the <strong>News Feed Refresh</strong> automation in Settings to run every 3 hours automatically.
            </p>
            <Button onClick={() => runMutation.mutate()} disabled={runMutation.isPending} className="mt-2">
              {runMutation.isPending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <RefreshCw className="h-4 w-4 mr-1" />}
              Fetch Now
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <FeedCard
            key={item.url}
            item={item}
            selectedPlatforms={platformsFor(item.url)}
            onTogglePlatform={(p) => togglePlatform(item.url, p)}
            onPublish={(isD) => publishMutation.mutate({ item, platforms: platformsFor(item.url), dry_run: isD ?? dryRun })}
            isPublishing={publishingUrl === item.url}
            lastResult={itemResults[item.url] ?? null}
            onGenerateCover={() => coverMutation.mutate(item)}
            onGenerateShort={() => shortMutation.mutate(item)}
            isGenerating={generating?.url === item.url ? generating.what : null}
            coverUrl={itemCovers[item.url] ?? null}
            shortPlan={itemShorts[item.url] ?? null}
          />
        ))}
      </div>
    </div>
  )
}
