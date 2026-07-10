import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/intelligence')({
  component: IntelligencePage,
})

function IntelligencePage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Intelligence</h1>
      <p className="text-muted-foreground">Feed intelligence engine — coming soon.</p>
    </div>
  )
}
