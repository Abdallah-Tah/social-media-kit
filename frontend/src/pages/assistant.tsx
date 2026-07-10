import { Card, CardContent } from '@/components/ui/card'

export default function AssistantPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight">Assistant</h1>
      <p className="text-muted-foreground">AI Assistant page — coming soon.</p>
      <Card>
        <CardContent className="pt-6 text-muted-foreground">
          The AI assistant will surface daily briefs, recommendations, and next actions.
        </CardContent>
      </Card>
    </div>
  )
}
