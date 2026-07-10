export interface IntelligenceFilters {
  topic?: string
  include_seen?: boolean
  min_score?: number
  trend?: 'all' | 'up' | 'down' | 'stable' | 'exploding'
  format?: 'all' | 'blog' | 'linkedin' | 'facebook' | 'x' | 'threads' | 'reddit' | 'newsletter' | 'youtube' | 'reel' | 'skip'
}

export interface ScoreBreakdownItem {
  name: string
  score: number
  weight: number
}

export interface PlatformFit {
  platform: string
  score: number
  reason: string
}

export interface Referrer {
  source: string
  visits: number
}

export interface BlogMetric {
  draft_id: string
  blog_url: string
  status: 'connected' | 'not_connected' | 'not_found' | 'unauthorized' | 'error'
  page_views?: number | null
  unique_visitors?: number | null
  clicks?: number | null
  average_read_time_seconds?: number | null
  referrers: Referrer[]
  period?: { from?: string; to?: string }
  last_sync_at?: string
  error?: string | null
}

export interface IntelligenceOpportunity {
  opportunity_score: number
  signal: string
  urgency: number
  originality: number
  commercial_value: number
  authority_boost: number
  recommendation: string
}

export interface IntelligenceTrend {
  direction: string
  strength: number
  velocity: number
  sparkline: number[]
  age_hours: number
}

export interface IntelligenceAuthority {
  final_score: number
  source_trust: number
  recency_score: number
  domain_authority: number
}

export interface WhyCare {
  summary: string
  bullets: string[]
}

export interface Brief {
  content_type: string
  title: string
  hook: string
  angle: string
  key_points: string[]
  call_to_action: string
}

export interface IntelligenceCard {
  rank: number
  previously_seen: boolean
  cluster: {
    headline: string
    summary: string
    sources: string[]
    urls: string[]
    latest: string
  }
  authority: IntelligenceAuthority
  trend: IntelligenceTrend
  opportunity: IntelligenceOpportunity
  recommendation: {
    recommendation: string
    confidence_score: number
    suggested_angle: string
    suggested_hook: string
    reason: string
  }
  brief?: Brief | null
  score_breakdown: ScoreBreakdownItem[]
  platform_fit: PlatformFit[]
  why_care: WhyCare
  estimated_reach: number
  estimated_difficulty: string
  history_delta: {
    previous?: number | null
    delta?: number | null
    trend: string
  }
  story_age: string
  confidence_meter: number
}

export interface IntelligenceSnapshot {
  generated_at: string
  count: number
  cards: IntelligenceCard[]
  top_brief?: Brief
}

export interface AnalyticsSnapshot {
  generated_at: string
  start_date: string
  end_date: string
  platform_filter: string | null
  intelligence: {
    opportunities_processed: number
    average_opportunity_score: number
    high_opportunities: number
    exploding_count: number
    top_formats: [string, number][]
    top_topics: [string, number][]
  }
  editorial_funnel: {
    drafts_created: number
    drafts_reviewed: number
    drafts_approved: number
    blogs_published: number
    draft_to_reviewed_rate: number
    reviewed_to_approved_rate: number
    approved_to_published_rate: number
    overall_conversion_rate: number
    status_counts: Record<string, number>
  }
  social: {
    total_social_drafts: number
    by_platform: Record<string, { created: number; approved: number; scheduled: number; published: number; failed: number }>
    success_rate: number
    total_published: number
    total_failed: number
  }
  timing: {
    opportunity_to_draft_minutes: number | null
    draft_to_approval_minutes: number | null
    approval_to_publish_minutes: number | null
    scheduled_vs_immediate: { scheduled: number; immediate: number }
  }
  performance: {
    status: string
    message: string
    metrics: Record<string, unknown>
    blog_metrics: BlogMetric[]
  }
  recent_activity: Array<{
    type: string
    title?: string
    url?: string
    platform: string
    published_at?: string
  }>
}

export interface RunIntelligenceResponse {
  ok: boolean
  cards?: IntelligenceCard[]
  snapshot?: string
  count?: number
  total?: number
  filtered?: number
  error?: string
}

export interface GenerateBriefResponse {
  ok: boolean
  brief?: Brief | null
  error?: string
}

export interface CreateDraftResponse {
  ok: boolean
  draft_id?: string
  draft?: Record<string, unknown>
  error?: string
}

export interface Snapshot {
  generated_at: string
  count: number
  cards: IntelligenceCard[]
}
