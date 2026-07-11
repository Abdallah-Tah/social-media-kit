import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  BarChart3, TrendingUp, FileText, Megaphone, RefreshCw,
  Zap, ExternalLink, CheckCircle2, Loader2,
} from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

import { api } from '@/api/client'
import type { CampaignAnalytics } from '@/api/models'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

function statusBadge(status: string) {
  if (status === 'published') return 'border-emerald-500 text-emerald-400'
  if (status === 'approved') return 'border-blue-500 text-blue-400'
  if (status === 'needs_review') return 'border-amber-500 text-amber-400'
  return ''
}

function CampaignRow({ campaign, onMakeMore, isMaking }: {
  campaign: CampaignAnalytics
  onMakeMore: () => void
  isMaking: boolean
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border p-3">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{campaign.headline}</div>
        <div className="mt-1 flex flex-wrap gap-1.5">
          <Badge variant="outline" className={`text-xs ${statusBadge(campaign.content_status)}`}>
            {campaign.content_status}
          </Badge>
          {campaign.platforms.map((p) => (
            <Badge key={p} variant="secondary" className="text-xs capitalize">{p}</Badge>
          ))}
        </div>
        {campaign.blog_url && (
          <a href={campaign.blog_url} target="_blank" rel="noreferrer"
            className="mt-1 block truncate text-xs text-blue-400 hover:underline">
            {campaign.blog_url}
          </a>
        )}
      </div>
      <div className="flex flex-col items-end gap-2">
        <span className="text-xs text-muted-foreground">{new Date(campaign.created_at).toLocaleDateString()}</span>
        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onMakeMore} disabled={isMaking}>
          {isMaking ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Zap className="h-3 w-3 mr-1" />}
          Make more like this
        </Button>
      </div>
    </div>
  )
}

export default function AnalyticsPage() {
  const qc = useQueryClient()

  const analyticsQuery = useQuery({
    queryKey: ['analytics', 30],
    queryFn: () => api.getAnalytics(30),
    staleTime: 60_000,
  })

  const campaignQuery = useQuery({
    queryKey: ['analytics-campaigns'],
    queryFn: api.getCampaignAnalytics,
    staleTime: 60_000,
  })

  const makeMoreMutation = useMutation({
    mutationFn: (campaign: CampaignAnalytics) => {
      const card = campaign.source_card as any
      return api.createCampaign(card, null, campaign.platforms)
    },
    onSuccess: (data) => {
      if (data.ok) {
        toast.success('New campaign created from the same story')
        qc.invalidateQueries({ queryKey: ['campaigns'] })
        qc.invalidateQueries({ queryKey: ['analytics-campaigns'] })
      } else {
        toast.error(data.error || 'Campaign creation failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const data = analyticsQuery.data
  const campaigns = campaignQuery.data?.campaigns ?? []
  const funnel = data?.editorial_funnel as any
  const social = data?.social as any
  const isLoading = analyticsQuery.isLoading

  const funnelData = funnel ? [
    { name: 'Created', value: funnel.drafts_created },
    { name: 'Reviewed', value: funnel.drafts_reviewed },
    { name: 'Approved', value: funnel.drafts_approved },
    { name: 'Published', value: funnel.blogs_published },
  ] : []

  const socialByPlatform = social?.by_platform
    ? Object.entries(social.by_platform as Record<string, Record<string, number>>)
        .map(([platform, counts]) => ({ name: platform, ...counts }))
    : []

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
          <p className="text-muted-foreground">Content pipeline metrics and campaign performance.</p>
        </div>
        <Button variant="outline" onClick={() => { qc.invalidateQueries({ queryKey: ['analytics'] }); qc.invalidateQueries({ queryKey: ['analytics-campaigns'] }) }}>
          <RefreshCw className="h-4 w-4 mr-1" />Refresh
        </Button>
      </div>

      {isLoading && (
        <div className="space-y-4">
          {[...Array(3)].map((_, i) => <Skeleton key={i} className="h-32" />)}
        </div>
      )}

      {data && (
        <>
          {/* Top-line metrics */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard title="Opportunities" value={String((data.intelligence as any)?.opportunities_processed ?? 0)} icon={BarChart3} />
            <MetricCard title="Drafts Created" value={String(funnel?.drafts_created ?? 0)} icon={FileText} />
            <MetricCard title="Blogs Published" value={String(funnel?.blogs_published ?? 0)} icon={CheckCircle2} accent="emerald" />
            <MetricCard title="Social Published" value={String(social?.total_published ?? 0)} icon={Megaphone} accent="blue" />
          </div>

          {/* Editorial funnel */}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <TrendingUp className="h-4 w-4" />Editorial Funnel
                </CardTitle>
                <CardDescription>
                  {funnel ? `${funnel.overall_conversion_rate ?? 0}% overall conversion` : ''}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {funnelData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={funnelData}>
                      <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-sm text-muted-foreground">No data yet.</p>
                )}
                {funnel?.status_counts && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {Object.entries(funnel.status_counts as Record<string, number>).map(([s, n]) => (
                      <Badge key={s} variant="outline" className={`text-xs ${statusBadge(s)}`}>
                        {s.replace('_', ' ')}: {n}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Megaphone className="h-4 w-4" />Social by Platform
                </CardTitle>
                <CardDescription>
                  {social ? `${social.success_rate ?? 0}% success rate · ${social.total_failed ?? 0} failed` : ''}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {socialByPlatform.length > 0 ? (
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={socialByPlatform}>
                      <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                      <Tooltip />
                      <Bar dataKey="published" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} name="Published" />
                      <Bar dataKey="failed" fill="hsl(var(--destructive))" radius={[4, 4, 0, 0]} name="Failed" />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="text-sm text-muted-foreground">No social data yet.</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Recent activity */}
          {(data.recent_activity?.length ?? 0) > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Recent Activity</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {data.recent_activity.slice(0, 8).map((item, i) => (
                    <div key={i} className="flex items-center justify-between gap-3 text-sm">
                      <div className="flex items-center gap-2 min-w-0">
                        <Badge variant="outline" className="capitalize shrink-0 text-xs">{item.platform}</Badge>
                        <span className="truncate text-muted-foreground">{item.title || item.type}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {item.url && (
                          <a href={item.url} target="_blank" rel="noreferrer">
                            <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                          </a>
                        )}
                        <span className="text-xs text-muted-foreground">
                          {item.published_at ? new Date(item.published_at).toLocaleDateString() : ''}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Campaign loop-closing */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold">Campaign Performance</h2>
          <p className="text-sm text-muted-foreground">
            Stories that became campaigns — track their pipeline and spin up follow-ups.
          </p>
        </div>
        {campaignQuery.isLoading && <Skeleton className="h-40" />}
        {!campaignQuery.isLoading && campaigns.length === 0 && (
          <Card>
            <CardContent className="pt-6 text-center text-sm text-muted-foreground">
              No campaigns yet. Create one from an Intelligence card.
            </CardContent>
          </Card>
        )}
        {campaigns.length > 0 && (
          <Card>
            <CardContent className="pt-4 space-y-2">
              {campaigns.map((c) => (
                <CampaignRow
                  key={c.campaign_id}
                  campaign={c}
                  onMakeMore={() => makeMoreMutation.mutate(c)}
                  isMaking={makeMoreMutation.isPending && (makeMoreMutation.variables as CampaignAnalytics | undefined)?.campaign_id === c.campaign_id}
                />
              ))}
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  )
}

function MetricCard({ title, value, icon: Icon, accent }: {
  title: string; value: string; icon: React.ElementType; accent?: string
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
