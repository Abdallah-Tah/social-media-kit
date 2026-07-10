import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/assistant')({
  component: AssistantPage,
})

function AssistantPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Assistant</h1>
      <p className="text-muted-foreground">Assistant page — coming soon.</p>
    </div>
  )
}
