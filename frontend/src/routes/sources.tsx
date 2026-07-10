import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/sources')({
  component: SourcesPage,
})

function SourcesPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Sources</h1>
      <p className="text-muted-foreground">Sources page — coming soon.</p>
    </div>
  )
}
