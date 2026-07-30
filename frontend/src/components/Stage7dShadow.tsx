import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShieldOff, ChevronDown, AlertTriangle } from 'lucide-react'

import { api } from '@/api/client'
import type { Stage7dSlot, Stage7dStatus } from '@/api/models'

/*
 * Stage 7D Live Shadow — styled on the buildwithabdallah design system.
 *
 *   surfaces  #09090b bg · #0e0e10 surface · #161618 panel · #1c1c20 elev
 *   lines     #26262b border · #3a3a42 hover
 *   ink       #fafafa · #d4d4d8 · #a1a1aa · #71717a · #52525b
 *   brand     #005cff · #3d7fff · #7099ff
 *   status    #34d399 live · #fbbf24 warn · #f87171 crit
 *   voice     JetBrains Mono (font-bwa-mono) for data & kickers
 *   radius    tight (3–6px) · glow shadows · terminal motifs
 */

const MONO = 'font-bwa-mono'

// ── Formatting helpers (all null-safe) ──────────────────────────────────────

function fmtCountdown(secs: number | null | undefined): string {
  if (secs === null || secs === undefined || Number.isNaN(secs)) return '—'
  if (secs <= 0) return 'done'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`
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

// ── Status tones ────────────────────────────────────────────────────────────

interface Tone {
  fg: string
  border: string
  bg: string
}

function serviceTone(status: string | undefined): Tone {
  switch (status) {
    case 'running':
      return { fg: '#34d399', border: 'rgba(52,211,153,0.35)', bg: 'rgba(52,211,153,0.08)' }
    case 'completed':
      return { fg: '#3d7fff', border: 'rgba(61,127,255,0.35)', bg: 'rgba(61,127,255,0.08)' }
    case 'failed':
      return { fg: '#f87171', border: 'rgba(248,113,113,0.35)', bg: 'rgba(248,113,113,0.08)' }
    default:
      return { fg: '#71717a', border: '#26262b', bg: 'rgba(255,255,255,0.02)' }
  }
}

function slotTone(status: string | undefined): Tone {
  switch (status) {
    case 'completed':
      return { fg: '#34d399', border: 'rgba(52,211,153,0.35)', bg: 'rgba(52,211,153,0.08)' }
    case 'running':
      return { fg: '#fbbf24', border: 'rgba(251,191,36,0.4)', bg: 'rgba(251,191,36,0.08)' }
    case 'failed':
      return { fg: '#f87171', border: 'rgba(248,113,113,0.35)', bg: 'rgba(248,113,113,0.08)' }
    default:
      return { fg: '#71717a', border: '#26262b', bg: 'rgba(255,255,255,0.02)' }
  }
}

function StatusBadge({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span
      className={`${MONO} text-[11px] uppercase tracking-[0.14em] px-2 py-0.5 rounded-[3px] border whitespace-nowrap`}
      style={{ color: tone.fg, borderColor: tone.border, background: tone.bg }}
    >
      {label}
    </span>
  )
}

// ── Small primitives ────────────────────────────────────────────────────────

function Kicker({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`${MONO} text-[11px] uppercase tracking-[0.2em] text-[#71717a] ${className}`}>
      {children}
    </div>
  )
}

/** A labelled datum: tiny uppercase kicker over a mono value. */
function Datum({ label, value, accent }: { label: string; value: React.ReactNode; accent?: string }) {
  return (
    <div className="min-w-0">
      <Kicker className="mb-1">{label}</Kicker>
      <div className={`${MONO} text-[13px] truncate`} style={{ color: accent ?? '#d4d4d8' }}>
        {value}
      </div>
    </div>
  )
}

/** Big telemetry number with a kicker. */
function Metric({ label, value, sub, accent }: { label: string; value: React.ReactNode; sub?: string; accent?: string }) {
  return (
    <div className="min-w-0">
      <Kicker className="mb-1.5">{label}</Kicker>
      <div className={`${MONO} text-2xl font-semibold leading-none tracking-tight`} style={{ color: accent ?? '#fafafa' }}>
        {value}
      </div>
      {sub && <div className={`${MONO} text-[11px] mt-1.5 text-[#71717a]`}>{sub}</div>}
    </div>
  )
}

/** Pulsing "live" indicator dot. */
function LiveDot({ color }: { color: string }) {
  return (
    <span className="relative flex h-2 w-2 shrink-0">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-60" style={{ background: color }} />
      <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: color }} />
    </span>
  )
}

// ── Segmented slot progress ─────────────────────────────────────────────────

function SlotProgress({ slots }: { slots: Stage7dSlot[] }) {
  return (
    <div className="flex gap-1.5">
      {slots.map((s, i) => {
        const tone = slotTone(s.status)
        const filled = s.status === 'completed' || s.status === 'failed'
        const running = s.status === 'running'
        return (
          <div key={`${s.slot_id}-${i}`} className="flex-1">
            <div
              className={`h-1.5 rounded-[3px] overflow-hidden ${running ? 'animate-pulse' : ''}`}
              style={{
                background: filled ? tone.fg : '#1c1c20',
                boxShadow: filled ? `0 0 12px -2px ${tone.fg}` : 'none',
              }}
            />
            <div className={`${MONO} text-[10px] mt-1 truncate text-[#52525b]`}>{s.slot_id}</div>
          </div>
        )
      })}
      {slots.length === 0 && <div className="flex-1 h-1.5 rounded-[3px] bg-[#1c1c20]" />}
    </div>
  )
}

// ── Top source-confidence scores as mini bars ───────────────────────────────

function ScoreBars({ scores }: { scores: number[] }) {
  if (!scores.length) return <span className={`${MONO} text-[13px] text-[#52525b]`}>—</span>
  return (
    <div className="flex items-end gap-1.5">
      {scores.map((sc, i) => (
        <div key={i} className="flex flex-col items-center gap-1">
          <span className={`${MONO} text-[11px] text-[#a1a1aa]`}>{sc}</span>
          <div className="w-7 h-1 rounded-[2px] bg-[#1c1c20] overflow-hidden">
            <div
              className="h-full rounded-[2px]"
              style={{ width: `${Math.min(100, Math.max(0, sc))}%`, background: '#005cff', boxShadow: '0 0 8px -1px rgba(0,92,255,0.7)' }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Candidate funnel (received → enriched → merged) ─────────────────────────

function Funnel({ received, enriched, merged }: { received: number | null; enriched: number | null; merged: number | null }) {
  // Recovered slots have no persisted funnel metrics.
  if (received == null && enriched == null && merged == null) {
    return <p className={`${MONO} text-[11px] text-[#52525b]`}>// funnel metrics not persisted (recovered slot)</p>
  }
  const max = Math.max(received ?? 0, enriched ?? 0, merged ?? 0, 1)
  const rows: Array<[string, number | null]> = [
    ['received', received],
    ['enriched', enriched],
    ['merged', merged],
  ]
  return (
    <div className="space-y-1">
      {rows.map(([label, n]) => (
        <div key={label} className="flex items-center gap-2">
          <span className={`${MONO} text-[10px] uppercase tracking-[0.12em] text-[#52525b] w-16 shrink-0`}>{label}</span>
          <div className="flex-1 h-1.5 rounded-[2px] bg-[#1c1c20] overflow-hidden">
            <div
              className="h-full rounded-[2px]"
              style={{ width: `${((n ?? 0) / max) * 100}%`, background: label === 'merged' ? '#3d7fff' : '#005cff', opacity: label === 'merged' ? 1 : 0.55 }}
            />
          </div>
          <span className={`${MONO} text-[11px] text-[#a1a1aa] w-7 text-right shrink-0`}>{n ?? '—'}</span>
        </div>
      ))}
    </div>
  )
}

// ── Rejection reason tag ────────────────────────────────────────────────────

function ReasonTag({ reason }: { reason: string }) {
  return (
    <span
      className={`${MONO} text-[10px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded-[3px] border`}
      style={{ color: '#f87171', borderColor: 'rgba(248,113,113,0.3)', background: 'rgba(248,113,113,0.06)' }}
    >
      {reason}
    </span>
  )
}

// ── Per-slot expandable card ────────────────────────────────────────────────

function SlotCard({ slot }: { slot: Stage7dSlot }) {
  const isPending = slot.status === 'waiting' || slot.status === 'running'
  const scores = Array.isArray(slot.top_source_confidence_scores) ? slot.top_source_confidence_scores : []
  const reasons = Array.isArray(slot.admission_reasons) ? slot.admission_reasons : []
  const tone = slotTone(slot.status)
  const [open, setOpen] = useState(true)

  return (
    <div
      className="rounded-[6px] border bg-[#0e0e10] transition-colors duration-200 hover:border-[#3a3a42]"
      style={{ borderColor: '#26262b', boxShadow: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.6)' }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 cursor-pointer text-left"
      >
        <div className="min-w-0">
          <div className={`${MONO} text-[13px] font-medium tracking-tight text-[#fafafa] truncate`}>
            <span className="text-[#3d7fff] mr-1.5">▸</span>
            {slot.slot_id || slot.content_type || 'slot'}
          </div>
          <div className={`${MONO} text-[11px] text-[#52525b] mt-0.5`}>{fmtTime(slot.scheduled_at)}</div>
        </div>
        <div className="flex items-center gap-2.5 shrink-0">
          {slot.recovered && (
            <span
              className={`${MONO} text-[10px] uppercase tracking-[0.1em] px-1.5 py-0.5 rounded-[3px] border`}
              style={{ color: '#fbbf24', borderColor: 'rgba(251,191,36,0.3)', background: 'rgba(251,191,36,0.06)' }}
              title="Recovered from the orchestrator pipeline file; batch metrics unavailable"
            >
              recovered
            </span>
          )}
          <StatusBadge label={slot.status === 'completed' ? '● completed' : slot.status === 'running' ? '● running' : slot.status === 'failed' ? '● failed' : 'waiting'} tone={tone} />
          <ChevronDown className={`h-4 w-4 text-[#71717a] transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 border-t" style={{ borderColor: '#1c1c20' }}>
          {isPending ? (
            <p className={`${MONO} text-[12px] text-[#71717a] pt-3`}>
              {slot.status === 'running' ? '// pipeline running…' : '// waiting for scheduled time.'}
            </p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-4 pt-3">
              <Datum label="Shadow outcome" value={slot.shadow_outcome ?? '—'} accent={tone.fg} />
              <Datum label="Admission" value={slot.admission_result ?? '—'} />
              <Datum label="Selected candidate" value={slot.selected_candidate ? slot.selected_candidate.slice(0, 16) : '—'} />
              <Datum label="Selected format" value={slot.selected_format ?? '—'} />
              <Datum label="Quality score" value={fmtNum(slot.quality_score)} />
              <Datum label="Readiness" value={slot.readiness_status ?? '—'} />
              <Datum label="Evidence URLs" value={`${fmtNum(slot.evidence_urls_fetched)} fetched / ${fmtNum(slot.evidence_fetch_failures)} failed`} />
              <Datum label="Claims +/−" value={`${fmtNum(slot.extraction_successes)} / ${fmtNum(slot.extraction_failures)}`} />
              <Datum label="Extraction calls" value={fmtNum(slot.extraction_llm_calls)} />
              <Datum label="Latency" value={slot.latency_ms != null ? `${slot.latency_ms}ms` : '—'} />
              <Datum label="API cost" value={fmtCost(slot.api_cost_usd)} />
              <Datum label="Result path" value={slot.result_path ? slot.result_path.split('/').slice(-1)[0] : '—'} />

              <div className="col-span-2 sm:col-span-3">
                <Kicker className="mb-2">Candidate funnel</Kicker>
                <Funnel received={slot.candidates_received} enriched={slot.candidates_enriched} merged={slot.candidates_merged} />
              </div>

              <div className="col-span-2 sm:col-span-3">
                <Kicker className="mb-2">Top source-confidence scores</Kicker>
                <ScoreBars scores={scores} />
              </div>

              {reasons.length > 0 && (
                <div className="col-span-2 sm:col-span-3">
                  <Kicker className="mb-2">Rejection reasons</Kicker>
                  <div className="flex flex-wrap gap-1.5">
                    {reasons.map((r) => (
                      <ReasonTag key={r} reason={r} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Safety chips ────────────────────────────────────────────────────────────

function SafetyChip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`${MONO} text-[10px] uppercase tracking-[0.12em] inline-flex items-center gap-1.5 px-2 py-1 rounded-[3px] border`}
      style={
        ok
          ? { color: '#34d399', borderColor: 'rgba(52,211,153,0.25)', background: 'rgba(52,211,153,0.05)' }
          : { color: '#f87171', borderColor: 'rgba(248,113,113,0.3)', background: 'rgba(248,113,113,0.06)' }
      }
    >
      <span>{ok ? '✓' : '✗'}</span>
      {label}
    </span>
  )
}

// ── Aggregate outcomes ──────────────────────────────────────────────────────

function Aggregate({ data }: { data: Stage7dStatus['aggregate'] | undefined }) {
  if (!data) return null
  const items: Array<[string, number, string?]> = [
    ['ready · shadow', data.ready_in_shadow ?? 0, '#34d399'],
    ['ready · warnings', data.ready_with_warnings_hold ?? 0, '#fbbf24'],
    ['manual review', data.requires_manual_review ?? 0, '#fbbf24'],
    ['quality rejected', data.quality_rejected ?? 0, '#f87171'],
    ['skipped · no cand.', data.skipped_no_candidate ?? 0, '#71717a'],
    ['draft failed', data.draft_generation_failed ?? 0, '#f87171'],
  ]
  return (
    <div>
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-px rounded-[6px] overflow-hidden border" style={{ borderColor: '#26262b' }}>
        {items.map(([label, value, accent]) => (
          <div key={label} className="bg-[#0e0e10] px-3 py-3">
            <div className={`${MONO} text-xl font-semibold leading-none`} style={{ color: (value ?? 0) > 0 ? accent : '#52525b' }}>
              {value}
            </div>
            <div className={`${MONO} text-[10px] uppercase tracking-[0.1em] text-[#52525b] mt-1.5`}>{label}</div>
          </div>
        ))}
      </div>
      <div className={`${MONO} text-[11px] text-[#71717a] mt-2`}>
        total api cost <span className="text-[#d4d4d8]">{fmtCost(data.total_api_cost_usd)}</span>
      </div>
    </div>
  )
}

// ── Main card ───────────────────────────────────────────────────────────────

export function Stage7dShadowCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['stage7d-status'],
    queryFn: () => api.getStage7dStatus(),
    refetchInterval: (query) => {
      const s = query.state.data?.service?.status
      return s === 'completed' || s === 'failed' ? false : 30_000
    },
  })

  const svcTone = serviceTone(data?.service?.status)
  const slots = data?.slots ?? []

  return (
    <section
      data-testid="stage7d-shadow-card"
      className="relative rounded-[6px] border overflow-hidden"
      style={{
        borderColor: '#26262b',
        background: '#09090b',
        boxShadow: '0 0 0 1px rgba(0,92,255,0.12), 0 16px 48px -16px rgba(0,0,0,0.7)',
      }}
    >
      {/* signature top accent line */}
      <div className="h-px w-full" style={{ background: 'linear-gradient(90deg, transparent, #005cff 30%, #3d7fff 50%, #005cff 70%, transparent)' }} />
      {/* ambient blue glow + grid texture */}
      <div className="pointer-events-none absolute inset-0" style={{ background: 'radial-gradient(55% 45% at 50% 0%, rgba(0,92,255,0.13), transparent 70%)' }} />
      <div
        className="pointer-events-none absolute inset-0 opacity-60"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.028) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.028) 1px, transparent 1px)',
          backgroundSize: '32px 32px',
        }}
      />

      <div className="relative">
        {/* status strip */}
        <div className="flex items-center justify-between gap-3 px-4 sm:px-5 py-2.5 border-b" style={{ borderColor: '#1c1c20', background: 'rgba(14,14,16,0.7)' }}>
          <div className="flex items-center gap-2.5 min-w-0">
            <LiveDot color={data?.service?.status === 'running' ? '#34d399' : '#52525b'} />
            <span className={`${MONO} text-[11px] uppercase tracking-[0.22em] text-[#a1a1aa] truncate`}>
              stage 7d · live shadow
            </span>
          </div>
          <div className="flex items-center gap-2.5 shrink-0">
            {data?.service?.pid != null && data.service.status === 'running' && (
              <span className={`${MONO} text-[11px] text-[#52525b] hidden sm:inline`}>pid {data.service.pid}</span>
            )}
            <StatusBadge label={data?.service?.status === 'running' ? '● running' : data?.service?.status === 'completed' ? '● completed' : data?.service?.status === 'failed' ? '● failed' : 'not started'} tone={svcTone} />
          </div>
        </div>

        <div className="px-4 sm:px-6 py-5 space-y-5">
          {/* shadow-mode banner */}
          <div
            data-testid="stage7d-shadow-banner"
            className="flex items-center gap-2.5 rounded-[4px] border px-3 py-2"
            style={{ borderColor: 'rgba(251,191,36,0.35)', background: 'rgba(251,191,36,0.07)' }}
          >
            <ShieldOff className="h-4 w-4 shrink-0" style={{ color: '#fbbf24' }} />
            <span className={`${MONO} text-[11px] sm:text-[12px] uppercase tracking-[0.16em] font-medium`} style={{ color: '#fbbf24' }}>
              Shadow mode — no content will be published
            </span>
          </div>

          {isLoading && (
            <div className="space-y-3">
              <div className="h-8 w-64 rounded-[4px] bg-[#161618] animate-pulse" />
              <div className="h-20 rounded-[4px] bg-[#161618] animate-pulse" />
            </div>
          )}

          {isError && !isLoading && (
            <div className="flex items-center gap-2.5 rounded-[4px] border px-3 py-2.5" style={{ borderColor: 'rgba(248,113,113,0.35)', background: 'rgba(248,113,113,0.07)' }}>
              <AlertTriangle className="h-4 w-4 shrink-0" style={{ color: '#f87171' }} />
              <span className={`${MONO} text-[12px]`} style={{ color: '#f87171' }}>Could not load shadow status.</span>
            </div>
          )}

          {data && !isLoading && !isError && (
            <>
              {/* header */}
              <div>
                <Kicker className="mb-1.5">editorial pipeline · read-only telemetry</Kicker>
                <h2 className="text-2xl font-bold tracking-tight text-[#fafafa]">
                  Stage 7D Live Shadow
                  <span className="ml-1 inline-block w-[0.55em] text-[#3d7fff] animate-pulse select-none">▮</span>
                </h2>
              </div>

              {/* telemetry */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-5 rounded-[6px] border bg-[#0e0e10] px-4 sm:px-5 py-4" style={{ borderColor: '#1c1c20' }}>
                <Metric label="Time remaining" value={fmtCountdown(data.service?.time_remaining_seconds)} accent="#3d7fff" />
                <Metric
                  label="Slots complete"
                  value={`${data.progress?.slots_completed ?? 0}/${data.progress?.slots_expected ?? 0}`}
                />
                <Metric
                  label="Next slot"
                  value={data.progress?.next_slot ? data.progress.next_slot.slot_id : '—'}
                  sub={data.progress?.next_slot ? fmtTime(data.progress.next_slot.scheduled_at) : undefined}
                  accent={data.progress?.next_slot ? '#7099ff' : undefined}
                />
                <Metric label="Started" value={fmtTime(data.service?.started_at)} sub={`completes ${fmtTime(data.service?.planned_completion_at)}`} />
              </div>

              {/* slot progress */}
              <div>
                <Kicker className="mb-2">slot progress</Kicker>
                <SlotProgress slots={slots} />
              </div>

              {/* safety chips */}
              <div className="flex flex-wrap gap-1.5">
                <SafetyChip ok={!data.safety?.publishing_enabled} label="publishing off" />
                <SafetyChip ok={!data.safety?.notifications_enabled} label="notifications off" />
                <SafetyChip ok={!data.safety?.editorial_slots_enabled} label="slots flag off" />
                <SafetyChip ok={!!data.safety?.cron_unchanged} label="cron unchanged" />
              </div>

              {/* slots */}
              <div>
                <Kicker className="mb-2">slots</Kicker>
                {slots.length === 0 ? (
                  <p className={`${MONO} text-[12px] text-[#71717a]`}>// no slot schedule available yet.</p>
                ) : (
                  <div className="grid gap-2.5 lg:grid-cols-3">
                    {slots.map((slot, i) => (
                      <SlotCard key={`${slot.slot_id}-${slot.scheduled_at ?? i}`} slot={slot} />
                    ))}
                  </div>
                )}
              </div>

              {/* aggregate */}
              <div>
                <Kicker className="mb-2">aggregate outcomes</Kicker>
                <Aggregate data={data.aggregate} />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  )
}

export default Stage7dShadowCard
