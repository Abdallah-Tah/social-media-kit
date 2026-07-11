"""Campaign API route handlers for the dashboard."""
from __future__ import annotations

from typing import Any

from .campaigns import create_campaign, get_campaign_pipeline, list_campaigns, load_campaign


def register_routes(
    path: str,
    query: dict[str, list[str]],
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if path == "/api/campaigns":
        if body:
            # POST /api/campaigns — create from intelligence card
            card = body.get("card")
            if not card:
                return {"ok": False, "error": "card is required"}
            brief = body.get("brief")
            platforms = body.get("platforms")
            try:
                campaign = create_campaign(card, brief=brief, platforms=platforms)
                pipeline = get_campaign_pipeline(campaign)
                return {"ok": True, "campaign": {**campaign.to_dict(), "pipeline": pipeline}}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        # GET /api/campaigns
        raw = list_campaigns()
        # Attach live pipeline status to each listing
        out = []
        for item in raw:
            from .campaigns import load_campaign as _load
            c = _load(item["campaign_id"])
            if c:
                out.append({**c.to_dict(), "pipeline": get_campaign_pipeline(c)})
        return {"ok": True, "campaigns": out}

    if path.startswith("/api/campaigns/"):
        campaign_id = path[len("/api/campaigns/"):]
        campaign = load_campaign(campaign_id)
        if campaign is None:
            return {"error": "not found"}
        pipeline = get_campaign_pipeline(campaign)
        return {"ok": True, "campaign": {**campaign.to_dict(), "pipeline": pipeline}}

    return {"error": "not found"}
