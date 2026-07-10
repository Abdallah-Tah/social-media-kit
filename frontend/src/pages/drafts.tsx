import { Card, CardContent } from '@/components/ui/card'

export default function DraftsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Drafts</h1>
      <p className="text-muted-foreground">Drafts page — coming soon.</p>
      <Card>
        <CardContent className="pt-6 text-muted-foreground">
          Draft workspace will connect to /api/drafts endpoints.
        </CardContent>
      </Card>
    </div>
  )
}
