import { Card, CardContent } from '@/components/ui/card'

export default function AnalyticsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
      <p className="text-muted-foreground">Analytics page — coming soon.</p>
      <Card>
        <CardContent className="pt-6 text-muted-foreground">
          Analytics integration will render read-only metrics from persisted snapshots.
        </CardContent>
      </Card>
    </div>
  )
}
