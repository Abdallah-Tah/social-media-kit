import { Card, CardContent } from '@/components/ui/card'

export default function SettingsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
      <p className="text-muted-foreground">Settings page — coming soon.</p>
      <Card>
        <CardContent className="pt-6 text-muted-foreground">
          Settings will expose profile, API, and appearance preferences.
        </CardContent>
      </Card>
    </div>
  )
}
