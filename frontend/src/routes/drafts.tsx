import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/drafts')({
  component: DraftsPage,
})

function DraftsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Drafts</h1>
      <p className="text-muted-foreground">Drafts page — coming soon.</p>
    </div>
  )
}
