import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

const SourcesPage = lazy(() => import('@/pages/sources'))

export const Route = createFileRoute('/sources')({
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
      <SourcesPage />
    </Suspense>
  ),
})
