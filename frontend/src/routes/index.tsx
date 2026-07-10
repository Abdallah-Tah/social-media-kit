import { createFileRoute } from '@tanstack/react-router'
import { Card, CardContent, CardHeader, CardDescription } from '@/components/ui/card'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Skeleton } from '@/components/ui/skeleton'

export const Route = createFileRoute('/')({
  component: DashboardPage,
})

function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['analytics', 30],
    queryFn: () => api.getAnalytics(30),
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">Overview of your content pipeline.</p>
      </div>

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              title="Opportunities"
              value={String((data.intelligence as any)?.opportunities_processed ?? 0)}
            />
            <MetricCard
              title="Drafts Created"
              value={String((data.editorial_funnel as any)?.drafts_created ?? 0)}
            />
            <MetricCard
              title="Social Drafts"
              value={String((data.social as any)?.total_social_drafts ?? 0)}
            />
            <MetricCard
              title="Blogs Published"
              value={String((data.editorial_funnel as any)?.blogs_published ?? 0)}
            />
          </div>
        </>
      )}
    </div>
  )
}

function MetricCard({ title, value }: { title: string; value: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-bold">{value}</div>
      </CardContent>
    </Card>
  )
}
