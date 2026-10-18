"""Public read-only theme settings API backed by Supabase RLS-protected tables."""
from __future__ import annotations

import re
import httpx
from fastapi import APIRouter, HTTPException, Path

from core.config import settings

router = APIRouter(prefix="/cms", tags=["Public CMS theme"])
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,80}$")


def _headers():
    if not settings.SUPABASE_URL or not settings.SUPABASE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=503, detail="Public theme service is not configured")
    key = settings.SUPABASE_PUBLISHABLE_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}


async def _get(resource: str, params: dict):
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
            response = await client.get(f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{resource}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Theme service is temporarily unavailable") from exc
    if not response.is_success:
        raise HTTPException(status_code=502, detail="Theme service is temporarily unavailable")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Theme service returned an invalid response") from exc
    if not isinstance(result, list):
        raise HTTPException(status_code=502, detail="Theme service returned an invalid response")
    return result


@router.get("/theme/{website_key}/{page_key}")
async def read_theme(
    website_key: str = Path(pattern=r"^(main|cart|mail|admin)$"),
    page_key: str = Path(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$"),
):
    if not KEY_RE.fullmatch(website_key) or not KEY_RE.fullmatch(page_key):
        raise HTTPException(status_code=400, detail="Invalid theme key")
    pages = await _get(
        "theme_page_settings",
        {
            "select": "*",
            "website_key": f"eq.{website_key}",
            "page_key": f"eq.{page_key}",
            "is_active": "eq.true",
            "limit": "1",
        },
    )
    components = await _get(
        "theme_component_settings",
        {
            "select": "*",
            "website_key": f"eq.{website_key}",
            "page_key": f"eq.{page_key}",
            "is_active": "eq.true",
            "order": "sort_order.asc,theme_component_id.asc",
            "limit": "300",
        },
    )
    return {"page": pages[0] if pages else None, "components": components}
