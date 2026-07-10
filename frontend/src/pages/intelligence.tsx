import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useForm, Controller } from 'react-hook-form'
import { toast } from 'sonner'
import {
  Brain,
  Search,
  Filter,
  ChevronDown,
  ChevronUp,
  FileText,
  Plus,
  ExternalLink,
  Save,
  Sparkles,
  BarChart3,
  TrendingUp,
  Users,
  Clock,
  Target,
  Shield,
  Megaphone,
  Download,
  RefreshCw,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/api/client'
import type { Brief, IntelligenceCard, IntelligenceFilters } from '@/api/models'

interface FilterForm {
  topic: string
  include_seen: boolean
  min_score: number
  trend: IntelligenceFilters['trend']
  format: IntelligenceFilters['format']
}

const defaultFilters: FilterForm = {
  topic: 'AI',
  include_seen: false,
  min_score: 0,
  trend: 'all',
  format: 'all',
}

export function IntelligencePage() {
  const [filters, setFilters] = useState<FilterForm>(defaultFilters)
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  const { register, handleSubmit, control, watch } = useForm<FilterForm>({
    defaultValues: defaultFilters,
  })

  const runIntelligenceMutation = useMutation({
    mutationFn: (values: FilterForm) =>
      api.runIntelligence({
        topic: values.topic,
        include_seen: values.include_seen,
      }),
    onSuccess: () => {
      toast.success('Intelligence run complete')
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const cards = runIntelligenceMutation.data?.cards || []
  const filteredCards = applyLocalFilters(cards, filters)
  const isRunning = runIntelligenceMutation.isPending
  const runError = runIntelligenceMutation.error
  const refetch = () => runIntelligenceMutation.mutate(filters)

  const briefMutation = useMutation({
    mutationFn: (rank: number) => api.generateBrief(rank),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success('Brief generated')
      } else {
        toast.error(data.error || 'Brief failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const draftMutation = useMutation({
    mutationFn: ({ rank, brief }: { rank: number; brief?: Brief | null }) =>
      api.createDraftFromBrief(rank, (brief || {}) as Record<string, unknown>),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success(`Draft created${data.draft_id ? `: ${data.draft_id}` : ''}`)
      } else {
        toast.error(data.error || 'Draft failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const snapshotMutation = useMutation({
    mutationFn: () => api.saveSnapshot(),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success(`Snapshot saved${data.path ? ` to ${data.path}` : ''}`)
      } else {
        toast.error(data.error || 'Snapshot failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const bulkBriefMutation = useMutation({
    mutationFn: () =>
      api.generateBriefs(filteredCards.slice(0, 5).map((c) => c.rank)),
    onSuccess: (data) => {
      if (data.ok) {
        toast.success(`Generated ${data.briefs.length} briefs`)
      } else {
        toast.error(data.error || 'Bulk brief failed')
      }
    },
    onError: (err: Error) => toast.error(err.message),
  })

  const onSubmit = (values: FilterForm) => {
    setFilters(values)
    runIntelligenceMutation.mutate(values)
  }

  const toggleExpand = (rank: number) => {
    setExpanded((prev) => ({ ...prev, [rank]: !prev[rank] }))
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-primary" />
            Intelligence
          </h1>
          <p className="text-muted-foreground">Discover, score, and convert opportunities into content.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => api.exportIntelligence('csv')}>
            <Download className="h-4 w-4 mr-1" />
            CSV
          </Button>
          <Button variant="outline" size="sm" onClick={() => api.exportIntelligence('json')}>
            <Download className="h-4 w-4 mr-1" />
            JSON
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Filters
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">Topic</label>
                <div className="relative">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                  <Input className="pl-9" placeholder="e.g. AI, Laravel, Raspberry Pi" {...register('topic')} />
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">Trend</label>
                <Controller
                  name="trend"
                  control={control}
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All trends</SelectItem>
                        <SelectItem value="up">Up</SelectItem>
                        <SelectItem value="down">Down</SelectItem>
                        <SelectItem value="stable">Stable</SelectItem>
                        <SelectItem value="exploding">Exploding</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">Format</label>
                <Controller
                  name="format"
                  control={control}
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All formats</SelectItem>
                        <SelectItem value="blog">Blog</SelectItem>
                        <SelectItem value="linkedin">LinkedIn</SelectItem>
                        <SelectItem value="facebook">Facebook</SelectItem>
                        <SelectItem value="x">X</SelectItem>
                        <SelectItem value="threads">Threads</SelectItem>
                        <SelectItem value="reddit">Reddit</SelectItem>
                        <SelectItem value="newsletter">Newsletter</SelectItem>
                        <SelectItem value="youtube">YouTube</SelectItem>
                        <SelectItem value="reel">Reel</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs text-muted-foreground">Min Score: {watch('min_score')}</label>
                <Controller
                  name="min_score"
                  control={control}
                  render={({ field }) => (
                    <Slider
                      value={[field.value]}
                      min={0}
                      max={100}
                      step={5}
                      onValueChange={(v) => field.onChange(v[0])}
                    />
                  )}
                />
              </div>
            </div>

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Controller
                  name="include_seen"
                  control={control}
                  render={({ field }) => (
                    <div className="flex items-center gap-2">
                      <Switch id="include-seen" checked={field.value} onCheckedChange={field.onChange} />
                      <label htmlFor="include-seen" className="text-sm text-muted-foreground cursor-pointer">
                        Include seen stories
                      </label>
                    </div>
                  )}
                />
              </div>
              <div className="flex items-center gap-2">
                <Button type="submit" disabled={isRunning}>
                  {isRunning ? <RefreshCw className="h-4 w-4 mr-1 animate-spin" /> : <Sparkles className="h-4 w-4 mr-1" />}
                  Run Intelligence
                </Button>
                <Button type="button" variant="outline" onClick={() => snapshotMutation.mutate()} disabled={cards.length === 0}>
                  <Save className="h-4 w-4 mr-1" />
                  Save Snapshot
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => bulkBriefMutation.mutate()}
                  disabled={filteredCards.length === 0 || bulkBriefMutation.isPending}
                >
                  <Sparkles className="h-4 w-4 mr-1" />
                  Bulk Top 5
                </Button>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>

      {isRunning && <IntelligenceSkeleton />}

      {runError && !isRunning && (
        <Card className="border-destructive/50">
          <CardContent className="pt-6">
            <div className="text-destructive font-medium">Failed to run intelligence</div>
            <p className="text-sm text-muted-foreground mt-1">{(runError as Error).message}</p>
            <Button variant="outline" size="sm" className="mt-3" onClick={() => refetch()}>
              <RefreshCw className="h-4 w-4 mr-1" />
              Retry
            </Button>
          </CardContent>
        </Card>
      )}

      {!isRunning && cards.length > 0 && (
        <KpiStrip cards={filteredCards} total={cards.length} />
      )}

      {!isRunning && runIntelligenceMutation.isSuccess && filteredCards.length === 0 && cards.length > 0 && (
        <Card>
          <CardContent className="pt-6 text-center text-muted-foreground">
            No cards match the current filters. Try relaxing them.
          </CardContent>
        </Card>
      )}

      {!isRunning && cards.length === 0 && runIntelligenceMutation.isSuccess && (
        <Card>
          <CardContent className="pt-6 text-center text-muted-foreground">
            No opportunities found. Try a different topic or enable Include seen.
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4">
        {filteredCards.map((card) => (
          <OpportunityCard
            key={card.rank}
            card={card}
            expanded={!!expanded[card.rank]}
            onToggle={() => toggleExpand(card.rank)}
            onBrief={() => briefMutation.mutate(card.rank)}
            onDraft={() => draftMutation.mutate({ rank: card.rank, brief: card.brief })}
            isBriefLoading={briefMutation.isPending && briefMutation.variables === card.rank}
            isDraftLoading={draftMutation.isPending && draftMutation.variables?.rank === card.rank}
          />
        ))}
      </div>
    </div>
  )
}

function applyLocalFilters(cards: IntelligenceCard[], filters: FilterForm): IntelligenceCard[] {
  return cards.filter((card) => {
    const score = card.opportunity?.opportunity_score ?? 0
    if (score < filters.min_score) return false
    if (filters.trend !== 'all' && card.trend?.direction !== filters.trend) return false
    if (filters.format !== 'all' && card.recommendation?.recommendation !== filters.format) return false
    return true
  })
}

function KpiStrip({ cards, total }: { cards: IntelligenceCard[]; total: number }) {
  const avgScore =
    cards.length > 0
      ? Math.round(cards.reduce((sum, c) => sum + (c.opportunity?.opportunity_score || 0), 0) / cards.length)
      : 0
  const high = cards.filter((c) => (c.opportunity?.opportunity_score || 0) >= 70).length
  const exploding = cards.filter((c) => (c.opportunity?.opportunity_score || 0) >= 85).length

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Kpi label="Total Opportunities" value={total} icon={BarChart3} />
      <Kpi label="Avg Score" value={avgScore} icon={Target} />
      <Kpi label="High ≥70" value={high} icon={TrendingUp} />
      <Kpi label="Exploding ≥85" value={exploding} icon={Sparkles} />
    </div>
  )
}

function Kpi({ label, value, icon: Icon }: { label: string; value: number; icon: React.ElementType }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-4">
        <div className="rounded-lg bg-primary/10 p-2">
          <Icon className="h-5 w-5 text-primary" />
        </div>
        <div>
          <div className="text-2xl font-bold">{value}</div>
          <div className="text-xs text-muted-foreground">{label}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function OpportunityCard({
  card,
  expanded,
  onToggle,
  onBrief,
  onDraft,
  isBriefLoading,
  isDraftLoading,
}: {
  card: IntelligenceCard
  expanded: boolean
  onToggle: () => void
  onBrief: () => void
  onDraft: () => void
  isBriefLoading: boolean
  isDraftLoading: boolean
}) {
  const score = card.opportunity?.opportunity_score ?? 0
  const scoreColor = score >= 70 ? 'text-emerald-400' : score >= 50 ? 'text-amber-400' : 'text-red-400'
  const scoreBarColor = score >= 70 ? 'bg-emerald-400' : score >= 50 ? 'bg-amber-400' : 'bg-red-400'

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-0">
        <div className="p-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-lg font-semibold leading-snug">{card.cluster?.headline || 'Untitled'}</h3>
                {card.previously_seen && <Badge variant="secondary">Seen</Badge>}
              </div>
              <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{card.cluster?.summary}</p>

              <div className="flex flex-wrap gap-2 mt-3">
                <Badge variant="outline" className="capitalize">
                  {card.recommendation?.recommendation || 'blog'}
                </Badge>
                <Badge variant="outline" className="flex items-center gap-1">
                  <TrendingUp className="h-3 w-3" />
                  {card.trend?.direction || 'unknown'}
                </Badge>
                <Badge variant="outline" className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {card.story_age || 'unknown age'}
                </Badge>
                <Badge variant="outline" className="flex items-center gap-1">
                  <Shield className="h-3 w-3" />
                  Auth {card.authority?.final_score ?? 0}
                </Badge>
                {card.estimated_difficulty && (
                  <Badge variant="outline">{card.estimated_difficulty}</Badge>
                )}
              </div>
            </div>

            <div className="text-right min-w-[80px]">
              <div className={`text-3xl font-bold ${scoreColor}`}>{score}</div>
              <div className="text-xs text-muted-foreground">opportunity</div>
              <div className="h-1.5 w-20 bg-muted rounded-full mt-2 overflow-hidden ml-auto">
                <div className={`h-full ${scoreBarColor}`} style={{ width: `${score}%` }} />
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 mt-4">
            {card.platform_fit?.slice(0, 4).map((fit) => (
              <TooltipProvider key={fit.platform}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Badge variant="secondary" className="capitalize">
                      <Megaphone className="h-3 w-3 mr-1" />
                      {fit.platform} {fit.score}
                    </Badge>
                  </TooltipTrigger>
                  <TooltipContent>{fit.reason}</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ))}
          </div>

          <div className="flex flex-wrap gap-2 mt-4">
            <Button size="sm" variant="outline" onClick={onToggle}>
              {expanded ? <ChevronUp className="h-4 w-4 mr-1" /> : <ChevronDown className="h-4 w-4 mr-1" />}
              Details
            </Button>
            <Button size="sm" variant="outline" onClick={onBrief} disabled={isBriefLoading}>
              {isBriefLoading ? <RefreshCw className="h-4 w-4 mr-1 animate-spin" /> : <FileText className="h-4 w-4 mr-1" />}
              Generate Brief
            </Button>
            <Button size="sm" onClick={onDraft} disabled={isDraftLoading || !card.brief}>
              {isDraftLoading ? <RefreshCw className="h-4 w-4 mr-1 animate-spin" /> : <Plus className="h-4 w-4 mr-1" />}
              Create Draft
            </Button>
            {card.cluster?.urls?.[0] && (
              <Button size="sm" variant="ghost" asChild>
                <a href={card.cluster.urls[0]} target="_blank" rel="noreferrer">
                  <ExternalLink className="h-4 w-4 mr-1" />
                  Open Source
                </a>
              </Button>
            )}
          </div>
        </div>

        {expanded && (
          <div className="border-t bg-card/50 p-4">
            <div className="grid gap-6 lg:grid-cols-2">
              <div className="space-y-4">
                <div>
                  <h4 className="text-sm font-semibold mb-2">Why care</h4>
                  <ul className="list-disc pl-5 space-y-1 text-sm text-muted-foreground">
                    {card.why_care?.bullets?.map((b, i) => <li key={i}>{b}</li>) || <li>{card.why_care?.summary}</li>}
                  </ul>
                </div>

                <div>
                  <h4 className="text-sm font-semibold mb-2">Score breakdown</h4>
                  <div className="space-y-2">
                    {card.score_breakdown?.map((item) => (
                      <div key={item.name} className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">{item.name}</span>
                        <div className="flex items-center gap-2 flex-1 mx-3">
                          <div className="h-1.5 flex-1 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary"
                              style={{ width: `${Math.min(item.score, 100)}%` }}
                            />
                          </div>
                          <span className="text-xs w-8 text-right">{item.score}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <DetailBox label="Reach" value={card.estimated_reach} icon={Users} />
                  <DetailBox label="Confidence" value={`${card.confidence_meter}%`} icon={Target} />
                  <DetailBox label="Sources" value={card.cluster?.sources?.length || 0} icon={Shield} />
                  <DetailBox label="URLs" value={card.cluster?.urls?.length || 0} icon={ExternalLink} />
                </div>

                <div>
                  <h4 className="text-sm font-semibold mb-2">Platform fit</h4>
                  <div className="space-y-2">
                    {card.platform_fit?.map((fit) => (
                      <div key={fit.platform} className="grid grid-cols-[100px_1fr_40px] items-center gap-3 text-sm">
                        <span className="capitalize text-muted-foreground">{fit.platform}</span>
                        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                          <div className="h-full bg-primary" style={{ width: `${fit.score}%` }} />
                        </div>
                        <span className="text-right font-medium">{fit.score}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {card.brief && (
                  <div className="rounded-lg border bg-background p-3">
                    <h4 className="text-sm font-semibold mb-1 flex items-center gap-1">
                      <FileText className="h-4 w-4" />
                      Generated brief
                    </h4>
                    <p className="text-sm font-medium">{card.brief.title}</p>
                    <p className="text-xs text-muted-foreground mt-1">{card.brief.hook}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DetailBox({ label, value, icon: Icon }: { label: string; value: React.ReactNode; icon: React.ElementType }) {
  return (
    <div className="rounded-lg border bg-background p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  )
}

function IntelligenceSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-40" />
      ))}
    </div>
  )
}
