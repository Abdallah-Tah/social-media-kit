import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  Globe, CheckCircle2, XCircle, RefreshCw, Save, AlertTriangle, Loader2,
} from 'lucide-react'

import { api } from '@/api/client'
import type { IntelligenceSourceConfig, PlatformConnection } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'

function ConnectionCard({ conn }: { conn: PlatformConnection }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border p-4">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {conn.connected
            ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            : <XCircle className="h-4 w-4 shrink-0 text-red-400" />}
          <span className="font-medium">{conn.name}</span>
          <Badge variant="outline" className={conn.connected ? 'border-emerald-500 text-emerald-400' : 'border-red-500 text-red-400'}>
            {conn.connected ? 'connected' : 'not connected'}
          </Badge>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{conn.description}</p>
        {!conn.connected && conn.missing_vars.length > 0 && (
          <p className="mt-1 text-xs text-red-400">
            <AlertTriangle className="inline h-3 w-3 mr-1" />
            Missing: {conn.missing_vars.join(', ')} in config/secrets.env
          </p>
        )}
      </div>
      <div className="text-right text-xs text-muted-foreground shrink-0">
        {conn.last_publish_status && (
          <>
            <div className={conn.last_publish_status === 'published' ? 'text-emerald-400' : 'text-red-400'}>
              Last: {conn.last_publish_status}
            </div>
            {conn.last_publish_at && (
              <div>{new Date(conn.last_publish_at).toLocaleDateString()}</div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function ToggleRow({ label, checked, onChange }: {
  label: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border px-4 py-3">
      <span className="text-sm">{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  )
}

export default function SourcesPage() {
  const qc = useQueryClient()
  const [localConfig, setLocalConfig] = useState<IntelligenceSourceConfig | null>(null)
  const [dirty, setDirty] = useState(false)

  const connectionsQuery = useQuery({
    queryKey: ['connections'],
    queryFn: api.getConnections,
    staleTime: 30_000,
  })

  const configQuery = useQuery({
    queryKey: ['intelligence-config'],
    queryFn: api.getSourceConfig,
    staleTime: 60_000,
    select: (data) => data.config,
  })

  const effectiveConfig = localConfig ?? configQuery.data

  const saveMutation = useMutation({
    mutationFn: () => api.updateSourceConfig(localConfig!),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success('Source config saved')
        setLocalConfig(null)
        setDirty(false)
        qc.invalidateQueries({ queryKey: ['intelligence-config'] })
      } else {
        toast.error('Save failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  function toggle(field: keyof IntelligenceSourceConfig, value: boolean) {
    const base = effectiveConfig!
    setLocalConfig({ ...base, [field]: value })
    setDirty(true)
  }

  const isLoading = connectionsQuery.isLoading || configQuery.isLoading

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Sources</h1>
          <p className="text-muted-foreground">Content sources and platform connection health.</p>
        </div>
        <Button variant="outline" size="sm"
          onClick={() => { qc.invalidateQueries({ queryKey: ['connections'] }); qc.invalidateQueries({ queryKey: ['intelligence-config'] }) }}>
          <RefreshCw className="h-4 w-4 mr-1" />Refresh
        </Button>
      </div>

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-20" /><Skeleton className="h-20" /><Skeleton className="h-20" />
        </div>
      )}

      {/* Platform connections */}
      {!connectionsQuery.isLoading && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Platform Connections</h2>
          <p className="text-sm text-muted-foreground">
            Credential status for each publisher. Set missing vars in <code className="text-xs bg-muted px-1 py-0.5 rounded">config/secrets.env</code>.
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            {(connectionsQuery.data?.connections ?? []).map((conn) => (
              <ConnectionCard key={conn.id} conn={conn} />
            ))}
          </div>
        </section>
      )}

      {/* Content sources */}
      {!configQuery.isLoading && effectiveConfig && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Content Sources</h2>
            {dirty && (
              <Button size="sm" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
                {saveMutation.isPending ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Save className="h-4 w-4 mr-1" />}
                Save changes
              </Button>
            )}
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Globe className="h-4 w-4" />Source toggles
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <ToggleRow label="Hacker News" checked={effectiveConfig.enable_hacker_news}
                  onChange={(v) => toggle('enable_hacker_news', v)} />
                <ToggleRow label="Reddit" checked={effectiveConfig.enable_reddit}
                  onChange={(v) => toggle('enable_reddit', v)} />
                <ToggleRow label="GitHub Trending" checked={effectiveConfig.enable_github_trending}
                  onChange={(v) => toggle('enable_github_trending', v)} />
                <ToggleRow label="Newsletters" checked={effectiveConfig.enable_newsletters}
                  onChange={(v) => toggle('enable_newsletters', v)} />
                <ToggleRow label="Newsletter Mining (deep)" checked={effectiveConfig.enable_newsletter_mining}
                  onChange={(v) => toggle('enable_newsletter_mining', v)} />
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Active subreddits</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {effectiveConfig.reddit_subreddits.map((sub) => (
                    <Badge key={sub} variant="secondary" className="text-xs">r/{sub}</Badge>
                  ))}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Edit in <code className="bg-muted px-1 rounded">config/agent.yaml</code> or save overrides.
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">GitHub topics</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  {effectiveConfig.github_trending_topics.map((t) => (
                    <Badge key={t} variant="secondary" className="text-xs">{t}</Badge>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">Newsletter URLs</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1">
                  {effectiveConfig.newsletters.slice(0, 6).map((url) => (
                    <a key={url} href={url} target="_blank" rel="noreferrer"
                      className="block truncate text-xs text-blue-400 hover:underline">
                      {url}
                    </a>
                  ))}
                  {effectiveConfig.newsletters.length > 6 && (
                    <p className="text-xs text-muted-foreground">+{effectiveConfig.newsletters.length - 6} more</p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
      )}
    </div>
  )
}
