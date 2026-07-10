import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

const IntelligencePage = lazy(() => import('@/pages/intelligence'))

export const Route = createFileRoute('/intelligence')({
  component: () => (
    <Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      }
    >
      <IntelligencePage />
    </Suspense>
  ),
})
