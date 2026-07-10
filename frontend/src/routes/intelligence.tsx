import { createFileRoute } from '@tanstack/react-router'
import { IntelligencePage } from '@/pages/intelligence'

export const Route = createFileRoute('/intelligence')({
  component: IntelligencePage,
})
