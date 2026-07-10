import { createFileRoute } from '@tanstack/react-router'
import { lazy, Suspense } from 'react'
import { Skeleton } from '@/components/ui/skeleton'

const SocialPage = lazy(() => import('@/pages/social'))

export const Route = createFileRoute('/social')({
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
      <SocialPage />
    </Suspense>
  ),
})
