"""Admin API for combo-pack CRUD, scoped to the cart website.

Authorization is enforced by the existing FastAPI admin RBAC dependency. SQL is
parameterized, all writes happen in one request transaction, and deleting a
pack is a soft-deactivation so catalogue history is retained.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from ADMINS.auth.dependencies import require_permission

router = APIRouter(prefix="/combos", tags=["Admin Combo Packs"])


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
            or self.image_url.startswith("data:image/")
        ):
            raise ValueError("Use an HTTPS image URL or an app-managed /media URL")
        return self


async def _combo_detail(db: AsyncSession, combo_id: str) -> dict:
    result = await db.execute(
        text(
            """
            SELECT
              c.id, c.website_key, c.combo_code, c.name, c.slug, c.short_title,
              c.description, c.tagline, c.image_url, c.budget_tier, c.pricing_mode,
              c.manual_price, c.badge_text, c.is_active, c.is_featured,
              c.show_on_homepage, c.display_order, c.combo_offer_price,
              c.combo_offer_label, c.combo_offer_starts_at, c.combo_offer_ends_at,
              c.metadata, c.created_at, c.updated_at,
              COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                  'id', i.id, 'product_id', i.product_id, 'product_code', p.product_code,
                  'name', p.name, 'category', p.category, 'quantity', i.quantity,
                  'unit_rate', p.factory_rate, 'image_url', COALESCE(p.image_url,p.product_image),
                  'display_order', i.display_order, 'item_label', i.item_label, 'item_note', i.item_note
                ) ORDER BY i.display_order, i.id)
                FROM public.combo_pack_items i
                LEFT JOIN public.products p ON p.id = i.product_id
                WHERE i.combo_id = c.id
              ), '[]'::jsonb) AS items
            FROM public.combo_packs c
            WHERE c.id = CAST(:combo_id AS uuid) AND c.website_key = 'cart'
            """
        ),
        {"combo_id": combo_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Combo pack not found")
    return dict(row)


async def _save(db: AsyncSession, payload: ComboInput, combo_id: str | None) -> dict:
    params = payload.model_dump(exclude={"items"})
    # Never let a request select or overwrite a different site's namespace.
    params["image_url"] = params["image_url"] or None

    try:
        await db.execute(text("SET LOCAL statement_timeout = '15s'"))
        if combo_id:
            exists = await db.execute(
                text("SELECT id FROM public.combo_packs WHERE id=CAST(:id AS uuid) AND website_key='cart' FOR UPDATE"),
                {"id": combo_id},
            )
            if not exists.first():
                await db.rollback()
                raise HTTPException(status_code=404, detail="Combo pack not found")
            await db.execute(
                text(
                    """
                    UPDATE public.combo_packs SET
                      combo_code=:combo_code, name=:name, slug=:slug, short_title=:short_title,
                      description=:description, tagline=:tagline, image_url=:image_url,
                      budget_tier=:budget_tier, pricing_mode=:pricing_mode,
                      manual_price=CASE WHEN :pricing_mode='MANUAL' THEN :manual_price ELSE NULL END,
                      badge_text=:badge_text, is_active=:is_active, is_featured=:is_featured,
                      show_on_homepage=:show_on_homepage, display_order=:display_order,
                      combo_offer_price=:combo_offer_price, combo_offer_label=:combo_offer_label,
                      combo_offer_starts_at=:combo_offer_starts_at,
                      combo_offer_ends_at=:combo_offer_ends_at, updated_at=now()
                    WHERE id=CAST(:combo_id AS uuid) AND website_key='cart'
                    """
                ),
                {**params, "combo_id": combo_id},
            )
            current_id = combo_id
        else:
            inserted = await db.execute(
                text(
                    """
                    INSERT INTO public.combo_packs (
                      website_key, combo_code, name, slug, short_title, description, tagline,
                      image_url, budget_tier, pricing_mode, manual_price, badge_text,
                      is_active, is_featured, show_on_homepage, display_order,
                      combo_offer_price, combo_offer_label, combo_offer_starts_at, combo_offer_ends_at
                    ) VALUES (
                      'cart', :combo_code, :name, :slug, :short_title, :description, :tagline,
                      :image_url, :budget_tier, :pricing_mode,
                      CASE WHEN :pricing_mode='MANUAL' THEN :manual_price ELSE NULL END,
                      :badge_text, :is_active, :is_featured, :show_on_homepage, :display_order,
                      :combo_offer_price, :combo_offer_label, :combo_offer_starts_at, :combo_offer_ends_at
                    ) RETURNING id
                    """
                ),
                params,
            )
            current_id = str(inserted.scalar_one())

        await db.execute(
            text("DELETE FROM public.combo_pack_items WHERE combo_id=CAST(:combo_id AS uuid)"),
            {"combo_id": current_id},
        )

        total = Decimal("0")
        for item in payload.items:
            product = await db.execute(
                text(
                    "SELECT factory_rate FROM public.products WHERE id=CAST(:id AS uuid) AND is_active=true"
                ),
                {"id": str(item.product_id)},
            )
            rate = product.scalar_one_or_none()
            if rate is None:
                raise HTTPException(status_code=422, detail="A selected product is inactive or does not exist")
            total += Decimal(rate) * item.quantity

        bundle_price = payload.manual_price if payload.pricing_mode == "MANUAL" else total
        if payload.combo_offer_price is not None and payload.combo_offer_price >= bundle_price:
            raise HTTPException(status_code=422, detail="Offer price must be below the combo price")

        for item in payload.items:
            await db.execute(
                text(
                    """
                    INSERT INTO public.combo_pack_items
                      (combo_id, product_id, quantity, display_order, item_label, item_note, updated_at)
                    VALUES (
                      CAST(:combo_id AS uuid), CAST(:product_id AS uuid),
                      :quantity, :display_order, :item_label, :item_note, now()
                    )
                    """
                ),
                {"combo_id": current_id, **item.model_dump(mode="json")},
            )
        await db.commit()
    except HTTPException:
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Combo code or slug is already in use, or a database constraint was violated",
        ) from exc
    except Exception:
        await db.rollback()
        raise

    return await _combo_detail(db, current_id)


@router.get("/products")
async def combo_product_options(
    admin=Depends(require_permission("products.read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            """
            SELECT id, product_code, name, category, pack_type, factory_rate,
                   COALESCE(image_url, product_image) AS image_url
            FROM public.products
            WHERE is_active = true
            ORDER BY category, product_code, name
            LIMIT 500
            """
        )
    )
    return {"items": [dict(row) for row in result.mappings().all()]}


@router.get("")
async def list_combo_packs(
    admin=Depends(require_permission("products.read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            """
            SELECT c.id, c.website_key, c.combo_code, c.name, c.slug, c.short_title,
                   c.description, c.tagline, c.image_url, c.budget_tier, c.pricing_mode,
                   c.manual_price, c.badge_text, c.is_active, c.is_featured,
                   c.show_on_homepage, c.display_order, c.combo_offer_price,
                   c.combo_offer_label, c.combo_offer_starts_at, c.combo_offer_ends_at,
                   c.created_at, c.updated_at,
                   COALESCE((
                     SELECT jsonb_agg(jsonb_build_object(
                       'id', i.id, 'product_id', i.product_id, 'product_code', p.product_code,
                       'name', p.name, 'category', p.category, 'quantity', i.quantity,
                       'unit_rate', p.factory_rate, 'image_url', COALESCE(p.image_url,p.product_image),
                       'display_order', i.display_order, 'item_label', i.item_label, 'item_note', i.item_note
                     ) ORDER BY i.display_order, i.id)
                     FROM public.combo_pack_items i
                     LEFT JOIN public.products p ON p.id = i.product_id
                     WHERE i.combo_id = c.id
                   ), '[]'::jsonb) AS items
            FROM public.combo_packs c
            WHERE c.website_key = 'cart'
            ORDER BY c.display_order, c.created_at DESC
            """
        )
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"items": items, "total": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_combo_pack(
    payload: ComboInput,
    admin=Depends(require_permission("products.write")),
    db: AsyncSession = Depends(get_db),
):
    return await _save(db, payload, None)


@router.put("/{combo_id}")
async def update_combo_pack(
    combo_id: UUID,
    payload: ComboInput,
    admin=Depends(require_permission("products.write")),
    db: AsyncSession = Depends(get_db),
):
    return await _save(db, payload, str(combo_id))


@router.delete("/{combo_id}")
async def deactivate_combo_pack(
    combo_id: UUID,
    admin=Depends(require_permission("products.write")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            """
            UPDATE public.combo_packs
            SET is_active=false, show_on_homepage=false, updated_at=now()
            WHERE id=:id AND website_key='cart'
            RETURNING id
            """
        ),
        {"id": combo_id},
    )
    if not result.first():
        await db.rollback()
        raise HTTPException(status_code=404, detail="Combo pack not found")
    await db.commit()
    return {"ok": True, "message": "Combo pack deactivated"}
