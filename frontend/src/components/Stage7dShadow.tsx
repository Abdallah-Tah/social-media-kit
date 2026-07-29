import { useQuery } from '@tanstack/react-query'
import {
  ShieldOff, Activity, CheckCircle2, XCircle, Clock, AlertTriangle, Eye, Loader2,
} from 'lucide-react'

import { api } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { Stage7dSlot, Stage7dStatus } from '@/api/models'

// ── Formatting helpers (all null-safe) ──────────────────────────────────────

function fmtCountdown(secs: number | null | undefined): string {
  if (secs === null || secs === undefined || Number.isNaN(secs)) return '—'
  if (secs <= 0) return 'done'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m`
  return `${Math.floor(secs)}s`
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function fmtCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined || Number.isNaN(usd)) return '—'
  return `$${Number(usd).toFixed(4)}`
}

function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return String(n)
}

// ── Badges ──────────────────────────────────────────────────────────────────

function ServiceBadge({ status }: { status: string | undefined }) {
  switch (status) {
    case 'running':
      return <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">● running</Badge>
    case 'completed':
      return <Badge className="bg-blue-500/15 text-blue-400 border-blue-500/30">completed</Badge>
    case 'failed':
      return <Badge className="bg-red-500/15 text-red-400 border-red-500/30">failed</Badge>
    default:
      return <Badge variant="outline">not started</Badge>
  }
}

function SlotBadge({ status }: { status: string | undefined }) {
  switch (status) {
    case 'completed':
      return <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/30">completed</Badge>
    case 'running':
      return <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/30">running</Badge>
    case 'failed':
      return <Badge className="bg-red-500/15 text-red-400 border-red-500/30">failed</Badge>
    default:
      return <Badge variant="outline">waiting</Badge>
  }
}

// ── Progress bar ────────────────────────────────────────────────────────────

function ProgressBar({ completed, expected }: { completed: number; expected: number }) {
  const pct = expected > 0 ? Math.min(100, Math.round((completed / expected) * 100)) : 0
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{completed} / {expected} slots completed</span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ── Per-slot card ───────────────────────────────────────────────────────────

function SlotDetail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-mono truncate">{value}</span>
    </div>
  )
}

function SlotCard({ slot }: { slot: Stage7dSlot }) {
  const isPending = slot.status === 'waiting' || slot.status === 'running'
  const scores = Array.isArray(slot.top_source_confidence_scores) ? slot.top_source_confidence_scores : []
  return (
    <div className="rounded-lg border bg-muted/10 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-medium truncate">{slot.slot_id || slot.content_type || 'slot'}</div>
          <div className="text-xs text-muted-foreground">{fmtTime(slot.scheduled_at)}</div>
        </div>
        <SlotBadge status={slot.status} />
      </div>

      {isPending ? (
        <p className="text-xs text-muted-foreground">
          {slot.status === 'running' ? 'Pipeline running…' : 'Waiting for scheduled time.'}
        </p>
      ) : (
        <div className="space-y-1">
          <SlotDetail label="Shadow outcome" value={slot.shadow_outcome ?? '—'} />
          <SlotDetail label="Admission" value={slot.admission_result ?? '—'} />
          <SlotDetail label="Selected candidate" value={slot.selected_candidate ? slot.selected_candidate.slice(0, 16) : '—'} />
          <SlotDetail label="Selected format" value={slot.selected_format ?? '—'} />
          <SlotDetail label="Quality score" value={fmtNum(slot.quality_score)} />
          <SlotDetail label="Readiness" value={slot.readiness_status ?? '—'} />
          <SlotDetail label="Top SC scores" value={scores.length ? scores.join(', ') : '—'} />
          <SlotDetail label="Candidates recv/enriched" value={`${fmtNum(slot.candidates_received)} / ${fmtNum(slot.candidates_enriched)}`} />
          <SlotDetail label="Evidence URLs" value={fmtNum(slot.evidence_urls_fetched)} />
          <SlotDetail label="Extraction +/−" value={`${fmtNum(slot.extraction_successes)} / ${fmtNum(slot.extraction_failures)}`} />
          <SlotDetail label="Latency" value={slot.latency_ms != null ? `${slot.latency_ms}ms` : '—'} />
          <SlotDetail label="API cost" value={fmtCost(slot.api_cost_usd)} />
          <SlotDetail label="Result path" value={slot.result_path ? slot.result_path.split('/').slice(-1)[0] : '—'} />
        </div>
      )}
    </div>
  )
}

// ── Aggregate totals ────────────────────────────────────────────────────────

function AggregateRow({ data }: { data: Stage7dStatus['aggregate'] | undefined }) {
  if (!data) return null
  const items: Array<[string, number]> = [
    ['Ready (shadow)', data.ready_in_shadow ?? 0],
    ['Ready w/ warnings', data.ready_with_warnings_hold ?? 0],
    ['Manual review', data.requires_manual_review ?? 0],
    ['Quality rejected', data.quality_rejected ?? 0],
    ['Skipped (no candidate)', data.skipped_no_candidate ?? 0],
    ['Draft failed', data.draft_generation_failed ?? 0],
  ]
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {items.map(([label, value]) => (
          <div key={label} className="rounded border bg-muted/10 px-2 py-1.5">
            <div className="text-lg font-bold">{value}</div>
            <div className="text-[10px] text-muted-foreground leading-tight">{label}</div>
          </div>
        ))}
      </div>
      <div className="text-xs text-muted-foreground">
        Total API cost: <span className="font-mono text-foreground">{fmtCost(data.total_api_cost_usd)}</span>
      </div>
    </div>
  )
}

// ── Main card ───────────────────────────────────────────────────────────────

export function Stage7dShadowCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['stage7d-status'],
    queryFn: () => api.getStage7dStatus(),
    // Poll every 30s while the run is active; stop once completed/failed.
    refetchInterval: (query) => {
      const s = query.state.data?.service?.status
      return s === 'completed' || s === 'failed' ? false : 30_000
    },
  })

  return (
    <Card data-testid="stage7d-shadow-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Eye className="h-4 w-4 text-violet-400" />Stage 7D Live Shadow
        </CardTitle>
        <CardDescription>Read-only view of the 24-hour shadow pipeline evaluation.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Prominent safety banner — always visible. */}
        <div
          data-testid="stage7d-shadow-banner"
          className="flex items-center gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-sm font-semibold text-amber-300"
        >
          <ShieldOff className="h-4 w-4 shrink-0" />
          SHADOW MODE — NO CONTENT WILL BE PUBLISHED
        </div>

        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-24" />
          </div>
        )}

        {isError && !isLoading && (
          <div className="flex items-center gap-2 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            <AlertTriangle className="h-4 w-4" />
            Could not load shadow status.
          </div>
        )}

        {data && !isLoading && !isError && (
          <>
            {/* Service status + timing */}
            <div className="grid gap-2 sm:grid-cols-2 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">Service</span>
                <ServiceBadge status={data.service?.status} />
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">Time remaining</span>
                <span className="font-mono">{fmtCountdown(data.service?.time_remaining_seconds)}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">Started</span>
                <span className="font-mono">{fmtTime(data.service?.started_at)}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">Planned completion</span>
                <span className="font-mono">{fmtTime(data.service?.planned_completion_at)}</span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">Next slot</span>
                <span className="font-mono">
                  {data.progress?.next_slot
                    ? `${data.progress.next_slot.slot_id} · ${fmtTime(data.progress.next_slot.scheduled_at)}`
                    : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground">Safety</span>
                <span className="flex items-center gap-1">
                  {data.safety?.cron_unchanged ? (
                    <><CheckCircle2 className="h-3 w-3 text-emerald-400" /> cron unchanged</>
                  ) : (
                    <><XCircle className="h-3 w-3 text-red-400" /> cron changed</>
                  )}
                </span>
              </div>
            </div>

            {/* Publishing-disabled confirmation */}
            <div className="flex flex-wrap gap-2 text-[10px]">
              <Badge variant="outline" className="text-emerald-400 border-emerald-500/30">
                publishing: {data.safety?.publishing_enabled ? 'ON' : 'off'}
              </Badge>
              <Badge variant="outline" className="text-emerald-400 border-emerald-500/30">
                notifications: {data.safety?.notifications_enabled ? 'ON' : 'off'}
              </Badge>
              <Badge variant="outline" className="text-emerald-400 border-emerald-500/30">
                slots flag: {data.safety?.editorial_slots_enabled ? 'ON' : 'off'}
              </Badge>
            </div>

            {/* Progress */}
            <ProgressBar
              completed={data.progress?.slots_completed ?? 0}
              expected={data.progress?.slots_expected ?? 0}
            />

            {/* Per-slot cards */}
            <div className="space-y-2">
              <div className="text-xs font-semibold flex items-center gap-1.5 text-muted-foreground">
                <Activity className="h-3.5 w-3.5" />Slots
              </div>
              {(data.slots ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                  <Clock className="h-3.5 w-3.5" />No slot schedule available yet.
                </p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {(data.slots ?? []).map((slot, i) => (
                    <SlotCard key={`${slot.slot_id}-${slot.scheduled_at ?? i}`} slot={slot} />
                  ))}
                </div>
              )}
            </div>

            {/* Aggregate totals */}
            <div className="space-y-2">
              <div className="text-xs font-semibold flex items-center gap-1.5 text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5" />Aggregate outcomes
              </div>
              <AggregateRow data={data.aggregate} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export default Stage7dShadowCard
