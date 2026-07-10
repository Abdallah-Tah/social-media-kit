import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

const SchedulerPage = lazy(() => import('@/pages/scheduler'))

export const Route = createFileRoute('/scheduler')({
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
      <SchedulerPage />
    </Suspense>
  ),
})
