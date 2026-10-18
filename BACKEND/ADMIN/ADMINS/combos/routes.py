"""Server-side combo-pack administration backed by the shared Supabase project.

The existing FastAPI permission checks authorize an administrator first. All
Supabase writes use a server-only service-role key; that key is never returned
to the browser. Bundle updates are sent to a single transaction-safe RPC.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, model_validator

from core.config import settings
from ADMINS.auth.dependencies import require_permission

router = APIRouter(prefix="/combos", tags=["Admin Combo Packs"])

IMAGE_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}


class ComboItemInput(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=10000)
    display_order: int = Field(default=0, ge=0)
    item_label: str | None = Field(default=None, max_length=120)
    item_note: str | None = Field(default=None, max_length=500)


class ComboInput(BaseModel):
    combo_code: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=180, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    short_title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2500)
    tagline: str | None = Field(default=None, max_length=240)
    image_url: str | None = Field(default=None, max_length=2000)
    budget_tier: Literal["STARTER", "FAMILY", "FESTIVAL", "PREMIUM", "GRAND"] | None = None
    pricing_mode: Literal["LIVE_SUM", "MANUAL"] = "LIVE_SUM"
    manual_price: Decimal | None = Field(default=None, ge=0)
    badge_text: str | None = Field(default=None, max_length=80)
    is_active: bool = True
    is_featured: bool = False
    show_on_homepage: bool = False
    display_order: int = Field(default=0, ge=0)
    combo_offer_price: Decimal | None = Field(default=None, gt=0)
    combo_offer_label: str | None = Field(default=None, max_length=100)
    combo_offer_starts_at: datetime | None = None
    combo_offer_ends_at: datetime | None = None
    items: list[ComboItemInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_combo(self):
        if self.pricing_mode == "MANUAL" and (self.manual_price is None or self.manual_price <= 0):
            raise ValueError("Manual pricing requires a positive manual_price")
        if self.combo_offer_starts_at and self.combo_offer_ends_at and self.combo_offer_ends_at <= self.combo_offer_starts_at:
            raise ValueError("Offer end time must be later than start time")
        ids = [str(item.product_id) for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("A product can only appear once in a combo; increase its quantity instead")
        if self.image_url and not (
            self.image_url.startswith("https://")
            or self.image_url.startswith("http://")
            or self.image_url.startswith("/media/")
        ):
            raise ValueError("Use an HTTPS image URL or upload an image with the image uploader")
        return self


def _service_headers() -> dict[str, str]:
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    if not url or not key:
        raise HTTPException(
            status_code=503,
            detail="Server-side Supabase catalogue access is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.",
        )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }


async def _request_supabase(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    content: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
):
    url = settings.SUPABASE_URL.rstrip("/") + path if settings.SUPABASE_URL else ""
    headers = _service_headers()
    headers.update(extra_headers or {})
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method, url, headers=headers, params=params, json=json_body, content=content
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Supabase catalogue service is unavailable") from exc

    if not response.is_success:
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("code") or "")
        message = str(body.get("message") or body.get("details") or "")
        if code == "23505":
            raise HTTPException(status_code=409, detail="Combo code or slug is already in use")
        if code in {"22023", "23514", "P0001"}:
            raise HTTPException(status_code=422, detail=message or "Combo data failed validation")
        if code == "42501" or response.status_code == 403:
            raise HTTPException(status_code=403, detail="The database rejected this administrative operation")
        if response.status_code == 404 and path.endswith("/rpc/api_admin_save_combo_pack"):
            raise HTTPException(status_code=503, detail="The combo administration database migration has not been applied")
        # Do not return upstream response text, request headers, or project secrets.
        raise HTTPException(status_code=502, detail="Supabase catalogue request failed")

    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Supabase returned an invalid response") from exc


async def _save(payload: ComboInput, combo_id: str | None):
    combo = payload.model_dump(mode="json", exclude={"items"})
    items = [item.model_dump(mode="json") for item in payload.items]
    result = await _request_supabase(
        "POST",
        "/rest/v1/rpc/api_admin_save_combo_pack",
        json_body={"p_combo_id": combo_id, "p_combo": combo, "p_items": items},
    )
    if isinstance(result, list):
        return result[0] if result else {}
    return result


@router.get("/products")
async def combo_product_options(admin=Depends(require_permission("products.read"))):
    rows = await _request_supabase(
        "GET",
        "/rest/v1/products",
        params={
            "select": "id,product_code,name,category,pack_type,factory_rate,image_url,product_image",
            "is_active": "eq.true",
            "order": "category.asc,product_code.asc",
            "limit": "500",
        },
    )
    return {"items": rows or []}


@router.get("")
async def list_combo_packs(admin=Depends(require_permission("products.read"))):
    rows = await _request_supabase(
        "GET",
        "/rest/v1/combo_packs",
        params={
            "select": "*,combo_pack_items(id,combo_id,product_id,quantity,display_order,item_label,item_note,products(id,product_code,name,category,pack_type,factory_rate,image_url,product_image))",
            "website_key": "eq.cart",
            "order": "display_order.asc,created_at.desc",
            "limit": "500",
        },
    )
    return {"items": rows or [], "total": len(rows or [])}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_combo_pack(
    payload: ComboInput,
    admin=Depends(require_permission("products.write")),
):
    return await _save(payload, None)


@router.put("/{combo_id}")
async def update_combo_pack(
    combo_id: UUID,
    payload: ComboInput,
    admin=Depends(require_permission("products.write")),
):
    return await _save(payload, str(combo_id))


@router.delete("/{combo_id}")
async def deactivate_combo_pack(
    combo_id: UUID,
    admin=Depends(require_permission("products.write")),
):
    rows = await _request_supabase(
        "PATCH",
        "/rest/v1/combo_packs",
        params={"id": f"eq.{combo_id}", "website_key": "eq.cart"},
        json_body={"is_active": False, "show_on_homepage": False},
        extra_headers={"Prefer": "return=representation"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Combo pack not found")
    return {"ok": True, "message": "Combo pack deactivated"}


@router.post("/image", status_code=status.HTTP_201_CREATED)
async def upload_combo_image(
    file: UploadFile = File(...),
    admin=Depends(require_permission("products.write")),
):
    """Upload a compressed raster image to the public combo-image bucket."""
    content_type = (file.content_type or "").lower()
    extension = IMAGE_MIME_EXT.get(content_type)
    if not extension:
        raise HTTPException(status_code=415, detail="Use a JPG, PNG, WebP, or AVIF image")
    limit = max(1, min(int(settings.MAX_UPLOAD_MB), 10)) * 1024 * 1024
    data = await file.read(limit + 1)
    await file.close()
    if not data or len(data) > limit:
        raise HTTPException(status_code=413, detail=f"Image must be no larger than {limit // (1024 * 1024)} MB")
    valid = (
        (content_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"))
        or (content_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"))
        or (content_type == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
        or (content_type == "image/avif" and (b"ftypavif" in data[:24] or b"ftypavis" in data[:24]))
    )
    if not valid:
        raise HTTPException(status_code=415, detail="The uploaded file does not match its declared image type")

    bucket = quote(settings.SUPABASE_STORAGE_BUCKET, safe="")
    object_path = f"combos/{uuid4().hex}{extension}"
    safe_path = "/".join(quote(segment, safe="") for segment in object_path.split("/"))
    await _request_supabase(
        "POST",
        f"/storage/v1/object/{bucket}/{safe_path}",
        content=data,
        extra_headers={"Content-Type": content_type, "x-upsert": "false"},
    )
    public_url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/public/{bucket}/{safe_path}"
    return {"url": public_url, "content_type": content_type, "bytes": len(data)}
