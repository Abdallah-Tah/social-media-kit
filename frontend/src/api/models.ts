export interface IntelligenceFilters {
  topic?: string
  include_seen?: boolean
  min_score?: number
  trend?: 'all' | 'up' | 'down' | 'stable' | 'exploding' | 'growing'
  format?: 'all' | 'blog' | 'linkedin' | 'linkedin_post' | 'facebook' | 'x' | 'threads' | 'reddit' | 'newsletter' | 'youtube' | 'youtube_short' | 'twitter_thread' | 'reel' | 'skip'
}

export interface SnapshotSummary {
  name: string
  path?: string
  when?: string
}

export interface ScoreBreakdownItem {
  name?: string
  score?: number
  label?: string
  points?: number
  weight: number
}

export interface PlatformFit {
  platform: string
  score: number
  reason?: string
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
  signals?: string[]
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
  markdown?: string
  draft_body?: string
  excerpt?: string
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

export interface FeedItem {
  title: string
  url: string
  source: string
  published_at: string
  summary: string
  score: number
  matched_interests: string[]
  reason: string
}

export interface FeedSnapshot {
  generated_at: string | null
  count: number
  items: FeedItem[]
  snapshot_file?: string
  snapshots?: Array<{ name: string; generated_at: string | null; count: number }>
}

export interface PlatformConnection {
  id: string
  name: string
  description: string
  env_vars: string[]
  connected: boolean
  missing_vars: string[]
  last_publish_status: 'published' | 'failed' | null
  last_publish_at: string | null
  last_publish_url: string | null
  last_publish_error?: string | null
}

export interface IntelligenceSourceConfig {
  enable_reddit: boolean
  enable_hacker_news: boolean
  enable_github_trending: boolean
  enable_newsletters: boolean
  enable_newsletter_mining: boolean
  reddit_subreddits: string[]
  hacker_news_queries: string[]
  github_trending_topics: string[]
  newsletters: string[]
}

export interface CampaignAnalytics {
  campaign_id: string
  headline: string
  created_at: string
  content_status: string
  blog_url: string
  platforms: string[]
  source_card: Record<string, unknown>
}

export interface Automation {
  job_id: string
  label: string
  description: string
  enabled: boolean
  interval_hours: number
  dry_run: boolean
  last_run?: string | null
  last_result?: 'ok' | 'error' | null
  last_error?: string | null
  next_run?: string | null
}

export interface AutomationLog {
  ts: string
  job_id: string
  ok: boolean
  message: string
  dry_run: boolean
}

export interface CampaignSocialStatus {
  draft_id: string
  status: SocialDraftStatus
  published_url: string
  scheduled_at: string
}

export interface CampaignPipeline {
  content: { draft_id: string; status: ContentDraftStatus }
  social: Record<string, CampaignSocialStatus>
  overall: 'draft' | 'needs_review' | 'in_progress' | 'published' | 'failed' | 'incomplete'
}

export interface Campaign {
  campaign_id: string
  headline: string
  content_draft_id: string
  social_draft_ids: Record<string, string>
  source_card: Record<string, unknown>
  created_at: string
  updated_at: string
  pipeline?: CampaignPipeline
}

export type ContentDraftStatus = 'idea' | 'draft' | 'needs_review' | 'approved' | 'published'

export interface ContentDraft {
  draft_id: string
  source_cluster: Record<string, unknown>
  recommendation: Record<string, unknown>
  content_type: string
  title: string
  slug: string
  brief: Record<string, unknown>
  body: string
  source_urls: string[]
  status: ContentDraftStatus
  blog_url: string
  published_at: string
  created_at: string
  updated_at: string
}

export type SocialDraftStatus = 'idea' | 'draft' | 'needs_review' | 'approved' | 'scheduled' | 'published' | 'failed'

export interface SocialDraft {
  draft_id: string
  source_draft_id: string
  platform: string
  blog_url: string
  title: string
  text: string
  description: string
  tags: string[]
  hashtags: string[]
  status: SocialDraftStatus
  scheduled_at: string
  published_url: string
  published_at: string
  error: string
  created_at: string
  updated_at: string
}

export interface MutationResult {
  ok: boolean
  error?: string
  results?: Record<string, { ok: boolean; error?: string; skipped?: boolean; published_url?: string }>
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
  draft?: ContentDraft
  error?: string
}

export interface Snapshot {
  generated_at: string
  count: number
  cards: IntelligenceCard[]
  top_brief?: Brief | null
}

// ── Stage 7D Live Shadow (read-only) ────────────────────────────────────────

export type Stage7dServiceStatus = 'not_started' | 'running' | 'completed' | 'failed'
export type Stage7dSlotStatus = 'waiting' | 'running' | 'completed' | 'failed'

export interface Stage7dService {
  status: Stage7dServiceStatus
  pid: number | null
  started_at: string | null
  planned_completion_at: string | null
  time_remaining_seconds: number | null
}

export interface Stage7dSafety {
  shadow_mode: boolean
  editorial_slots_enabled: boolean
  publishing_enabled: boolean
  notifications_enabled: boolean
  cron_unchanged: boolean
}

export interface Stage7dNextSlot {
  slot_id: string
  scheduled_at: string | null
}

export interface Stage7dProgress {
  slots_expected: number
  slots_completed: number
  next_slot: Stage7dNextSlot | null
}

export interface Stage7dSlot {
  slot_id: string
  content_type: string
  scheduled_at: string | null
  completed_at: string | null
  status: Stage7dSlotStatus
  recovered?: boolean
  candidates_received: number | null
  candidates_enriched: number | null
  candidates_merged: number | null
  evidence_urls_fetched: number | null
  evidence_fetch_failures: number | null
  extraction_successes: number | null
  extraction_failures: number | null
  extraction_llm_calls: number | null
  top_source_confidence_scores: number[]
  selected_candidate: string | null
  selected_format: string | null
  admission_result: string | null
  admission_reasons: string[]
  quality_score: number | null
  readiness_status: string | null
  shadow_outcome: string | null
  latency_ms: number | null
  api_cost_usd: number | null
  result_path: string | null
}

export interface Stage7dAggregate {
  ready_in_shadow: number
  ready_with_warnings_hold: number
  requires_manual_review: number
  quality_rejected: number
  skipped_no_candidate: number
  draft_generation_failed: number
  total_api_cost_usd: number
}

export interface Stage7dStatus {
  ok: boolean
  error?: string
  service: Stage7dService
  safety: Stage7dSafety
  progress: Stage7dProgress
  slots: Stage7dSlot[]
  aggregate: Stage7dAggregate
}
