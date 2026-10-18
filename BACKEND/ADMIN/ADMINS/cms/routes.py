"""Admin CMS API, including allowlisted updates to persisted theme/component settings."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from core.database import get_db
from core.config import settings
from ADMINS.auth.dependencies import require_permission
from ADMINS.cms.schemas import Create, Update
from ADMINS.cms.service import Service
import httpx

router = APIRouter(prefix="/cms", tags=["Admin CMS"])

PAGE_FIELDS = {
    "is_active", "mode", "background_color", "surface_color", "surface_elevated_color",
    "section_color", "header_color", "footer_color", "text_color", "muted_text_color",
    "heading_color", "primary_color", "primary_dark_color", "secondary_color",
    "accent_color", "link_color", "button_background_color", "button_text_color",
    "border_color", "border_strong_color", "input_background_color",
    "input_border_color", "card_shadow_color", "hero_background_color",
    "banner_background_color", "nav_background_color", "nav_text_color",
    "font_heading", "font_body", "radius_small", "radius_medium", "radius_large",
    "component_tokens",
}
COMPONENT_FIELDS = {
    "section_name", "component_name", "component_type", "font_family", "font_size",
    "font_weight", "line_height", "letter_spacing", "text_color", "background_color",
    "border_color", "border_width", "border_radius", "box_shadow", "padding", "margin",
    "width", "max_width", "text_align", "component_tokens", "content_value", "is_active",
    "sort_order",
}
JSON_FIELDS = {"component_tokens"}


def _headers():
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(status_code=503, detail="Server-side Supabase access is not configured")
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}


async def _theme_rest(method: str, table: str, *, params: dict | None = None, payload: dict | None = None):
    try:
        async with httpx.AsyncClient(timeout=15, headers=_headers()) as client:
            response = await client.request(
                method,
                f"{settings.SUPABASE_URL.rstrip('/')}/rest/v1/{table}",
                params=params,
                json=payload,
                headers={"Prefer": "return=representation"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Supabase theme service is unavailable") from exc
    if not response.is_success:
        raise HTTPException(status_code=502, detail="Supabase theme update failed")
    if not response.content:
        return []
    try:
        rows = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Supabase returned an invalid theme response") from exc
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Supabase returned an invalid theme response")
    return rows


def _clean_payload(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    result = {key: value for key, value in payload.items() if key in allowed}
    if not result:
        raise HTTPException(status_code=422, detail="No editable theme fields were supplied")
    return result


@router.get("/theme-pages")
async def list_theme_pages(admin=Depends(require_permission("CMS.READ"))):
    rows = await _theme_rest(
        "GET", "theme_page_settings",
        params={"select": "*", "order": "website_key.asc,page_key.asc", "limit": "300"},
    )
    return rows


@router.get("/theme-components")
async def list_theme_components(admin=Depends(require_permission("CMS.READ"))):
    rows = await _theme_rest(
        "GET", "theme_component_settings",
        params={"select": "*", "order": "website_key.asc,page_key.asc,sort_order.asc", "limit": "500"},
    )
    return rows


@router.patch("/theme-pages/{theme_page_id}")
async def update_theme_page(theme_page_id: int, payload: dict = Body(...), admin=Depends(require_permission("CMS.WRITE"))):
    clean = _clean_payload(payload, PAGE_FIELDS)
    rows = await _theme_rest(
        "PATCH", "theme_page_settings",
        params={"theme_page_id": f"eq.{theme_page_id}"},
        payload=clean,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Theme page not found")
    return rows[0]


@router.patch("/theme-components/{theme_component_id}")
async def update_theme_component(theme_component_id: int, payload: dict = Body(...), admin=Depends(require_permission("CMS.WRITE"))):
    clean = _clean_payload(payload, COMPONENT_FIELDS)
    rows = await _theme_rest(
        "PATCH", "theme_component_settings",
        params={"theme_component_id": f"eq.{theme_component_id}"},
        payload=clean,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Theme component not found")
    return rows[0]


@router.get("/{kind}")
async def list_kind(kind: str, admin=Depends(require_permission("CMS.READ")), db: AsyncSession=Depends(get_db)):
    return await Service(db, admin.admin_id).list(kind)


@router.post("/{kind}", status_code=201)
async def create_kind(kind: str, p: Create, admin=Depends(require_permission("CMS.WRITE")), db: AsyncSession=Depends(get_db)):
    return await Service(db, admin.admin_id).create(kind, p.data)


@router.patch("/{kind}/{id}")
async def update_kind(kind: str, id: int, p: Update, admin=Depends(require_permission("CMS.WRITE")), db: AsyncSession=Depends(get_db)):
    return await Service(db, admin.admin_id).update(kind, id, p.data)


@router.delete("/{kind}/{id}")
async def delete_kind(kind: str, id: int, admin=Depends(require_permission("CMS.DELETE")), db: AsyncSession=Depends(get_db)):
    return await Service(db, admin.admin_id).delete(kind, id)
