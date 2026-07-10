import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/scheduler')({
  component: SchedulerPage,
})

function SchedulerPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Scheduler</h1>
      <p className="text-muted-foreground">Scheduler page — coming soon.</p>
    </div>
  )
}
