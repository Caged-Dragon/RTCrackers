"""Public read-only Supabase combo catalogue.

This endpoint uses only a Supabase publishable key and reads RLS-protected
public views/tables. The browser never receives a service-role credential.
"""
from __future__ import annotations

import asyncio
import httpx
from fastapi import APIRouter, HTTPException, Query

from core.config import settings

router = APIRouter(prefix="/combos", tags=["Combo packs"])


def _public_headers() -> dict[str, str]:
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_PUBLISHABLE_KEY
    if not url or not key:
        raise HTTPException(
            status_code=503,
            detail="Public combo catalogue is not configured on this server",
        )
    return {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}


async def _rest_get(client: httpx.AsyncClient, path: str, params: dict[str, str]) -> list[dict]:
    try:
        response = await client.get(
            f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{path}",
            params=params,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Combo catalogue service is temporarily unavailable") from exc
    if not response.is_success:
        # Keep upstream response bodies and configuration values out of public errors.
        raise HTTPException(status_code=502, detail="Combo catalogue service is temporarily unavailable")
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Combo catalogue returned an invalid response") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Combo catalogue returned an invalid response")
    return data


@router.get("")
async def list_combos(homepage_only: bool = Query(default=False)):
    headers = _public_headers()
    async with httpx.AsyncClient(headers=headers, timeout=12.0) as client:
        view_rows, pack_rows = await asyncio.gather(
            _rest_get(
                client,
                "combo_pack_catalogue",
                {"select": "*", "website_key": "eq.cart", "order": "display_order.asc,name.asc"},
            ),
            _rest_get(
                client,
                "combo_packs",
                {
                    "select": "id,combo_offer_price,combo_offer_label,combo_offer_starts_at,combo_offer_ends_at,show_on_homepage",
                    "website_key": "eq.cart",
                    "is_active": "eq.true",
                },
            ),
        )

    by_id = {str(row.get("id")): row for row in pack_rows}
    items: list[dict] = []
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    for row in view_rows:
        extra = by_id.get(str(row.get("id")), {})
        if homepage_only and not extra.get("show_on_homepage", False):
            continue
        combo = {**row, **extra}
        try:
            starts = datetime.fromisoformat(str(extra["combo_offer_starts_at"]).replace("Z", "+00:00")) if extra.get("combo_offer_starts_at") else None
            ends = datetime.fromisoformat(str(extra["combo_offer_ends_at"]).replace("Z", "+00:00")) if extra.get("combo_offer_ends_at") else None
            valid_offer = bool(extra.get("combo_offer_price")) and (starts is None or starts <= now) and (ends is None or ends > now)
        except (TypeError, ValueError):
            valid_offer = False
        combo["is_offer_active"] = valid_offer
        combo["display_price"] = extra.get("combo_offer_price") if valid_offer else row.get("calculated_price")
        items.append(combo)

    return {"items": items, "total": len(items)}
