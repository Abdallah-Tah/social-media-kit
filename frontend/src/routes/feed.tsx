import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

const FeedPage = lazy(() => import('@/pages/feed'))

export const Route = createFileRoute('/feed')({
  component: () => (
    <Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      }
    >
      <FeedPage />
    </Suspense>
  ),
})
