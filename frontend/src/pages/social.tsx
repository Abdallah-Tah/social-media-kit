import { Card, CardContent } from '@/components/ui/card'

export default function SocialPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Social</h1>
      <p className="text-muted-foreground">Social drafts page — coming soon.</p>
      <Card>
        <CardContent className="pt-6 text-muted-foreground">
          Social drafts will connect to /api/social_drafts endpoints.
        </CardContent>
      </Card>
    </div>
  )
}
