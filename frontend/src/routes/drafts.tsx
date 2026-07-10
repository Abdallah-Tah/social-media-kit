import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

const DraftsPage = lazy(() => import('@/pages/drafts'))

export const Route = createFileRoute('/drafts')({
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
      <DraftsPage />
    </Suspense>
  ),
})
