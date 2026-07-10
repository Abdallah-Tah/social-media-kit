# BuildWithAbdallah Blog Analytics API Specification

This document specifies the read-only Laravel API endpoint that the local smkit `agent/analytics_connectors/blog.py` connector consumes.

## Endpoint

```
GET /api/v1/posts/{slug}/analytics
```

Public article URLs follow the pattern `https://buildwithabdallah.com/tutorials/{slug}`. The connector maps each published `blog_url` to this endpoint.

## Authentication

Use the existing **BLOG_API_TOKEN** (Sanctum token) via Bearer header:

```
Authorization: Bearer <BLOG_API_TOKEN>
Accept: application/json
```

## Query parameters (optional)

| Name   | Type   | Description                     | Example      |
|--------|--------|---------------------------------|--------------|
| `from` | string | Start date (YYYY-MM-DD)         | `2026-07-01` |
| `to`   | string | End date (YYYY-MM-DD)             | `2026-07-09` |

When omitted, return all-time analytics for the post.

## Success response — 200 OK

```json
{
  "status": "connected",
  "slug": "example-post",
  "blog_url": "https://buildwithabdallah.com/tutorials/example-post",
  "published_at": "2026-07-09T18:30:00Z",
  "period": {
    "from": "2026-07-01",
    "to": "2026-07-09"
  },
  "metrics": {
    "page_views": 1250,
    "unique_visitors": 930,
    "clicks": 145,
    "average_read_time_seconds": 224,
    "referrers": [
      {"source": "linkedin", "visits": 320},
      {"source": "facebook", "visits": 180},
      {"source": "google", "visits": 410},
      {"source": "direct", "visits": 340}
    ]
  }
}
```

### Field requirements

- `status` — `"connected"` when real analytics data is available.
- `slug` — URL-safe post slug.
- `blog_url` — Canonical public URL.
- `published_at` — ISO-8601 publication timestamp.
- `period.from` / `period.to` — Dates covered by the metrics; match requested range or default to all-time.
- `metrics.page_views` — Integer.
- `metrics.unique_visitors` — Integer.
- `metrics.clicks` — Integer (internal/external link clicks, or `0`).
- `metrics.average_read_time_seconds` — Float/integer.
- `metrics.referrers` — Array of `{source, visits}` objects. Source names should be lowercase (`google`, `linkedin`, `facebook`, `direct`, etc.).

Never fabricate values. If analytics storage is not configured, see the "not connected" response below.

## Not connected response — 200 OK

If analytics tracking is not installed or no data has been collected yet, return HTTP 200 with `status: not_connected` and `null` metrics:

```json
{
  "status": "not_connected",
  "slug": "example-post",
  "blog_url": "https://buildwithabdallah.com/tutorials/example-post",
  "published_at": "2026-07-09T18:30:00Z",
  "period": {
    "from": "2026-07-01",
    "to": "2026-07-09"
  },
  "metrics": {
    "page_views": null,
    "unique_visitors": null,
    "clicks": null,
    "average_read_time_seconds": null,
    "referrers": []
  }
}
```

The smkit connector treats this as "endpoint available but no analytics yet".

## Error responses

### 404 Not Found

Use only when the post slug does not exist.

```json
{
  "message": "Post not found."
}
```

The smkit connector translates 404 to `status: not_connected` to distinguish missing posts from future analytics availability.

### 401 Unauthorized

Invalid or missing Bearer token.

```json
{
  "message": "Unauthenticated."
}
```

### 403 Forbidden

Valid token, but the user/role lacks analytics read permission.

```json
{
  "message": "Forbidden."
}
```

## Laravel implementation notes

1. Add a route inside the Sanctum-protected API group:

```php
Route::get('/posts/{slug}/analytics', [PostAnalyticsController::class, 'show']);
```

2. Controller contract:

```php
class PostAnalyticsController extends Controller
{
    public function show(Request $request, string $slug): JsonResponse
    {
        $post = Post::where('slug', $slug)->firstOrFail();

        $period = $this->resolvePeriod($request);

        if (! config('analytics.enabled')) {
            return response()->json([
                'status' => 'not_connected',
                'slug' => $post->slug,
                'blog_url' => route('tutorial.show', $post->slug),
                'published_at' => $post->published_at?->toIso8601String(),
                'period' => $period,
                'metrics' => [
                    'page_views' => null,
                    'unique_visitors' => null,
                    'clicks' => null,
                    'average_read_time_seconds' => null,
                    'referrers' => [],
                ],
            ]);
        }

        $metrics = $this->fetchMetrics($post, $period);

        return response()->json([
            'status' => 'connected',
            'slug' => $post->slug,
            'blog_url' => route('tutorial.show', $post->slug),
            'published_at' => $post->published_at?->toIso8601String(),
            'period' => $period,
            'metrics' => $metrics,
        ]);
    }
}
```

3. Storage options (read-only):
   - Server-side page-view table (`id`, `post_id`, `ip_hash`, `referrer`, `user_agent_hash`, `created_at`).
   - Google Analytics / Plausible / Cloudflare Web Analytics read via wrapper.
   - Simple file-based counter for MVP.

4. Rules:
   - Read-only endpoint.
   - Authenticate via existing `BLOG_API_TOKEN` Sanctum guard.
   - Never return fabricated numbers.
   - Filter dates by `from`/`to` when present.
   - Return 404 **only** for missing posts, 401/403 for auth issues, 200 otherwise.

## Laravel feature tests

Add tests covering:

- Authenticated request for a published post returns 200 with connected/not_connected status.
- Missing post returns 404.
- Invalid token returns 401.
- Date filtering reduces returned page views.
- Referrer aggregation is correct.
- Unpublished/draft posts return 404 unless policy says otherwise.

Example test skeleton:

```php
class PostAnalyticsTest extends TestCase
{
    use RefreshDatabase;

    public function test_analytics_returns_not_connected_without_tracking()
    {
        $post = Post::factory()->published()->create(['slug' => 'demo-post']);
        $user = User::factory()->create();
        $token = $user->createToken('api')->plainTextToken;

        $response = $this->withHeader('Authorization', "Bearer {$token}")
            ->getJson('/api/v1/posts/demo-post/analytics');

        $response->assertOk()
            ->assertJsonPath('status', 'not_connected')
            ->assertJsonPath('metrics.page_views', null);
    }

    public function test_analytics_returns_metrics_when_tracking_enabled()
    {
        config(['analytics.enabled' => true]);
        $post = Post::factory()->published()->create(['slug' => 'demo-post']);
        // seed page views...

        $response = $this->getJson('/api/v1/posts/demo-post/analytics');

        $response->assertOk()
            ->assertJsonPath('status', 'connected')
            ->assertJsonPath('metrics.page_views', 5);
    }
}
```

## Connector mapping

The local smkit connector stores each response in:

```
content/analytics/connector_cache/{slug}.json
```

Then `agent/analytics.py` merges cached blog metrics into the `/api/analytics` performance section, showing one row per published draft:

```json
{
  "performance": {
    "status": "partial",
    "blog_metrics": [
      {
        "draft_id": "a1b2c3d4",
        "blog_url": "https://buildwithabdallah.com/tutorials/example-post",
        "status": "connected",
        "page_views": 1250,
        "unique_visitors": 930,
        "clicks": 145,
        "average_read_time_seconds": 224,
        "referrers": {...},
        "last_sync_at": "2026-07-10T00:35:00Z"
      }
    ]
  }
}
```

## Status

- Local connector: implemented and tested.
- Live endpoint: not yet present on `buildwithabdallah.com`. Connector correctly reports `not_connected` until implemented.
