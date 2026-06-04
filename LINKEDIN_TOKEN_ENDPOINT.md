# Server-side task: expose the stored LinkedIn org token to the Pi

The Pi (social-media-kit) needs to read the LinkedIn **organization** access token that the
"Build With Abdallah — Social OAuth" flow saved (encrypted) into the buildwithabdallah.com DB,
so it can post to the showcase page `urn:li:organization:119694084`.

## Endpoint to add

```
GET /api/v1/social/linkedin/token
Authorization: Bearer <Sanctum token>      # same auth as POST /api/v1/posts
Accept: application/json
```

**Response 200:**
```json
{
  "data": {
    "access_token": "<DECRYPTED LinkedIn token>",
    "author_urn": "urn:li:organization:119694084",
    "expires_at": "2026-08-03T12:00:00Z"
  }
}
```
- `404` if no LinkedIn account is connected, `401/403` if the caller isn't authorized.

## Implementation notes

1. **Find where the OAuth callback stored the token.** The "Social OAuth → Account Connected"
   flow wrote a row (the one shown as `ID: ABnvUUsgfB`) — likely a `social_accounts` /
   `social_tokens` / `oauth_tokens` table or model. The `access_token` column is **Laravel-encrypted**
   (the value looks like `eyJpdiI6...` — `Crypt` format).
2. **Controller** (invokable): load that row for provider `linkedin`, decrypt the token:
   ```php
   $token = Crypt::decryptString($row->access_token);   // or $row->access_token if cast 'encrypted'
   ```
   Return it with the org URN and the stored `expires_at`.
3. **Protect it** with the existing Sanctum middleware used by the posts API. If you use token
   abilities/scopes, gate this behind an admin/owner ability — it returns a live credential.
4. HTTPS only (already enforced). Optionally log each access for audit.

## Route

Add to `routes/api.php` inside the `v1` group that already has the posts routes:
```php
Route::middleware('auth:sanctum')->prefix('v1')->group(function () {
    // ...existing posts/categories/tags...
    Route::get('social/linkedin/token', \App\Http\Controllers\Api\LinkedInTokenController::class);
});
```

Once this returns 200 with the decrypted token, the Pi side is already wired:
`social-media-kit/scripts/linkedin_org_poster.py` will fetch it and post automatically.
No further Pi changes needed.
