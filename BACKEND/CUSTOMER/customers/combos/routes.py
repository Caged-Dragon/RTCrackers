"""Public combo catalogue endpoints.

Reads only active cart-site combos from the shared PostgreSQL catalogue view.
The browser never receives database credentials and display/viewport settings
are deliberately not part of these API contracts.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db

router = APIRouter(prefix="/combos", tags=["Combo packs"])


@router.get("")
async def list_combos(
    homepage_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            """
            SELECT
              to_jsonb(v) || jsonb_build_object(
                'combo_offer_price', c.combo_offer_price,
                'combo_offer_label', c.combo_offer_label,
                'show_on_homepage', c.show_on_homepage,
                'display_price',
                  CASE WHEN c.combo_offer_price IS NOT NULL
                            AND (c.combo_offer_starts_at IS NULL OR c.combo_offer_starts_at <= now())
                            AND (c.combo_offer_ends_at IS NULL OR c.combo_offer_ends_at > now())
                       THEN c.combo_offer_price
                       ELSE v.calculated_price
                  END,
                'is_offer_active',
                  (c.combo_offer_price IS NOT NULL
                   AND (c.combo_offer_starts_at IS NULL OR c.combo_offer_starts_at <= now())
                   AND (c.combo_offer_ends_at IS NULL OR c.combo_offer_ends_at > now()))
              ) AS combo
            FROM public.combo_pack_catalogue AS v
            JOIN public.combo_packs AS c ON c.id = v.id
            WHERE c.website_key = 'cart'
              AND c.is_active = true
              AND (CAST(:homepage_only AS boolean) = false OR c.show_on_homepage = true)
            ORDER BY c.display_order, c.name
            """
        ),
        {"homepage_only": homepage_only},
    )
    items = [row["combo"] for row in result.mappings().all()]
    return {"items": items, "total": len(items)}
