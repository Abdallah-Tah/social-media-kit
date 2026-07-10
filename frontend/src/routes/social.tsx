import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/social')({
  component: SocialPage,
})

function SocialPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Social</h1>
      <p className="text-muted-foreground">Social page — coming soon.</p>
    </div>
  )
}
