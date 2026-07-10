import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

const AnalyticsPage = lazy(() => import('@/pages/analytics'))

export const Route = createFileRoute('/analytics')({
  component: () => (
    <Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      }
    >
      <AnalyticsPage />
    </Suspense>
  ),
})
