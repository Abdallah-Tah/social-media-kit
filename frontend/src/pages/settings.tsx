import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Automation, AutomationLog } from '@/api/models'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function fmtNext(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  if (diff < 0) return 'overdue'
  if (diff < 60) return 'in <1m'
  if (diff < 3600) return `in ${Math.floor(diff / 60)}m`
  if (diff < 86400) return `in ${Math.floor(diff / 3600)}h`
  return `in ${Math.floor(diff / 86400)}d`
}

function AutomationCard({ job }: { job: Automation }) {
  const qc = useQueryClient()

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => api.updateAutomation(job.job_id, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations'] }),
  })

  const dryRunMutation = useMutation({
    mutationFn: (dry_run: boolean) => api.updateAutomation(job.job_id, { dry_run }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automations'] }),
  })

  const runNowMutation = useMutation({
    mutationFn: () => api.runAutomationNow(job.job_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['automations'] })
      qc.invalidateQueries({ queryKey: ['logs'] })
    },
  })

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <CardTitle className="text-base">{job.label}</CardTitle>
            <CardDescription className="mt-1 text-xs">{job.description}</CardDescription>
          </div>
          <Switch
            checked={job.enabled}
            onCheckedChange={(v) => toggleMutation.mutate(v)}
            disabled={toggleMutation.isPending}
            aria-label={`Toggle ${job.label}`}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
          <span>
            <span className="font-medium text-foreground">Interval</span>{' '}
            {job.interval_hours}h
          </span>
          <span>
            <span className="font-medium text-foreground">Last run</span>{' '}
            {fmtRelative(job.last_run)}
          </span>
          <span>
            <span className="font-medium text-foreground">Next run</span>{' '}
            {job.enabled ? fmtNext(job.next_run) : '—'}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {job.last_result && (
            <Badge variant={job.last_result === 'ok' ? 'default' : 'destructive'} className="text-xs">
              {job.last_result === 'ok' ? 'last ok' : 'last failed'}
            </Badge>
          )}
          <Badge variant="outline" className="text-xs">
            {job.dry_run ? 'dry run' : 'live'}
          </Badge>
          {job.last_error && (
            <span className="truncate text-xs text-destructive" title={job.last_error}>
              {job.last_error.slice(0, 80)}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 pt-1">
          <Button
            size="sm"
            variant="outline"
            onClick={() => runNowMutation.mutate()}
            disabled={runNowMutation.isPending}
            className="h-7 text-xs"
          >
            {runNowMutation.isPending ? 'Running…' : 'Run now'}
          </Button>
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
            <Switch
              checked={!job.dry_run}
              onCheckedChange={(v) => dryRunMutation.mutate(!v)}
              disabled={dryRunMutation.isPending}
              className="h-4 w-7"
              aria-label="Live mode"
            />
            <span className={!job.dry_run ? 'text-orange-400 font-medium' : ''}>
              {job.dry_run ? 'Dry run (safe)' : 'Live — will publish'}
            </span>
          </label>
          {runNowMutation.isSuccess && runNowMutation.data && (
            <span className={`text-xs ${runNowMutation.data.ok ? 'text-green-400' : 'text-destructive'}`}>
              {runNowMutation.data.ok
                ? `✓ ${runNowMutation.data.message ?? 'done'}`
                : `✗ ${runNowMutation.data.error ?? 'failed'}`}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function LogEntry({ log }: { log: AutomationLog }) {
  return (
    <div className="flex items-start gap-3 border-b border-border/50 py-2 text-xs last:border-0">
      <span className={log.ok ? 'text-green-400 mt-0.5' : 'text-destructive mt-0.5'}>
        {log.ok ? '✓' : '✗'}
      </span>
      <span className="w-32 shrink-0 text-muted-foreground">
        {new Date(log.ts).toLocaleTimeString()}
      </span>
      <Badge variant="outline" className="shrink-0 text-xs py-0">
        {log.job_id.replace('_', ' ')}
      </Badge>
      {log.dry_run && (
        <Badge variant="secondary" className="shrink-0 text-xs py-0">dry</Badge>
      )}
      <span className="truncate text-muted-foreground">{log.message}</span>
    </div>
  )
}

export default function SettingsPage() {
  const [showAllLogs, setShowAllLogs] = useState(false)

  const { data: autoData, isLoading: autoLoading } = useQuery({
    queryKey: ['automations'],
    queryFn: () => api.getAutomations(),
    refetchInterval: 30_000,
  })

  const { data: logData, isLoading: logLoading } = useQuery({
    queryKey: ['logs'],
    queryFn: () => api.getLogs(showAllLogs ? 200 : 20),
    refetchInterval: 30_000,
  })

  const automations = autoData?.automations ?? []
  const logs = logData?.logs ?? []

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Manage automations and background jobs.</p>
      </div>

      <section className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold">Automations</h2>
          <p className="text-sm text-muted-foreground">
            All jobs default to <strong>disabled</strong> and <strong>dry run</strong>.
            Enable live mode only when you want real publishing.
          </p>
        </div>

        {autoLoading && (
          <p className="text-sm text-muted-foreground">Loading automations…</p>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          {automations.map((job) => (
            <AutomationCard key={job.job_id} job={job} />
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Run log</h2>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs"
            onClick={() => setShowAllLogs((v) => !v)}
          >
            {showAllLogs ? 'Show recent' : 'Show more'}
          </Button>
        </div>

        {logLoading && (
          <p className="text-sm text-muted-foreground">Loading logs…</p>
        )}

        {!logLoading && logs.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No automation runs yet. Enable a job and click "Run now" to start.
          </p>
        )}

        {logs.length > 0 && (
          <Card>
            <CardContent className="pt-4">
              {logs.map((log, i) => (
                <LogEntry key={`${log.ts}-${i}`} log={log} />
              ))}
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  )
}
