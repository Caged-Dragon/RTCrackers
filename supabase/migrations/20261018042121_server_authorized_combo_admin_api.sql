-- Reproducible source for production migration 20261018042121_server_authorized_combo_admin_api.
-- This migration is already applied to production; table counts and privileges verified.
BEGIN;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('combo-pack-images', 'combo-pack-images', true, 5242880, ARRAY['image/jpeg','image/png','image/webp','image/avif']::text[])
ON CONFLICT (id) DO UPDATE SET public=EXCLUDED.public,file_size_limit=EXCLUDED.file_size_limit,allowed_mime_types=EXCLUDED.allowed_mime_types;

CREATE OR REPLACE FUNCTION public.api_admin_save_combo_pack(p_combo_id uuid, p_combo jsonb, p_items jsonb)
 RETURNS combo_packs
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
DECLARE
  v_combo public.combo_packs%rowtype;
  v_combo_id uuid;
  v_item jsonb;
  v_product_id uuid;
  v_product_rate numeric(12,2);
  v_quantity integer;
  v_base_price numeric(12,2) := 0;
  v_bundle_price numeric(12,2);
  v_manual_price numeric(12,2);
  v_offer_price numeric(12,2);
  v_pricing_mode text;
  v_claims jsonb;
  v_role text;
  v_seen uuid[] := ARRAY[]::uuid[];
BEGIN
  v_claims := nullif(current_setting('request.jwt.claims', true), '')::jsonb;
  v_role := COALESCE(v_claims ->> 'role', current_setting('request.jwt.claim.role', true), '');
  IF v_role <> 'service_role' THEN
    RAISE EXCEPTION 'Server-side service authorization required' USING ERRCODE = '42501';
  END IF;

  IF jsonb_typeof(p_combo) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'Combo details are required' USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(p_items) IS DISTINCT FROM 'array' OR jsonb_array_length(p_items) < 1 OR jsonb_array_length(p_items) > 100 THEN
    RAISE EXCEPTION 'Add between 1 and 100 products to a combo' USING ERRCODE = '22023';
  END IF;

  v_pricing_mode := COALESCE(NULLIF(p_combo->>'pricing_mode', ''), 'LIVE_SUM');
  IF v_pricing_mode NOT IN ('LIVE_SUM', 'MANUAL') THEN
    RAISE EXCEPTION 'Invalid combo pricing mode' USING ERRCODE = '22023';
  END IF;
  v_manual_price := NULLIF(p_combo->>'manual_price', '')::numeric;
  v_offer_price := NULLIF(p_combo->>'combo_offer_price', '')::numeric;

  IF NULLIF(btrim(p_combo->>'name'), '') IS NULL
     OR NULLIF(btrim(p_combo->>'slug'), '') IS NULL
     OR NULLIF(btrim(p_combo->>'combo_code'), '') IS NULL THEN
    RAISE EXCEPTION 'Combo name, slug and code are required' USING ERRCODE = '22023';
  END IF;
  IF v_pricing_mode = 'MANUAL' AND (v_manual_price IS NULL OR v_manual_price <= 0) THEN
    RAISE EXCEPTION 'Manual pricing requires a positive bundle price' USING ERRCODE = '22023';
  END IF;

  FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
    v_product_id := NULLIF(v_item->>'product_id', '')::uuid;
    v_quantity := (v_item->>'quantity')::integer;
    IF v_product_id IS NULL OR v_quantity IS NULL OR v_quantity < 1 OR v_quantity > 10000 THEN
      RAISE EXCEPTION 'Combo item has an invalid product or quantity' USING ERRCODE = '22023';
    END IF;
    IF v_product_id = ANY(v_seen) THEN
      RAISE EXCEPTION 'Each product can only appear once per combo' USING ERRCODE = '22023';
    END IF;
    v_seen := array_append(v_seen, v_product_id);

    SELECT p.factory_rate INTO v_product_rate
    FROM public.products AS p
    WHERE p.id = v_product_id AND p.is_active = true;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'A selected product is inactive or unavailable' USING ERRCODE = '22023';
    END IF;
    v_base_price := v_base_price + v_product_rate * v_quantity;
  END LOOP;

  v_bundle_price := CASE WHEN v_pricing_mode = 'MANUAL' THEN v_manual_price ELSE v_base_price END;
  IF v_offer_price IS NOT NULL AND (v_offer_price <= 0 OR v_offer_price >= v_bundle_price) THEN
    RAISE EXCEPTION 'Offer price must be positive and below the combo price' USING ERRCODE = '22023';
  END IF;
  IF NULLIF(p_combo->>'combo_offer_starts_at', '') IS NOT NULL
     AND NULLIF(p_combo->>'combo_offer_ends_at', '') IS NOT NULL
     AND (p_combo->>'combo_offer_ends_at')::timestamptz <= (p_combo->>'combo_offer_starts_at')::timestamptz THEN
    RAISE EXCEPTION 'Offer end time must be later than start time' USING ERRCODE = '22023';
  END IF;

  IF p_combo_id IS NOT NULL THEN
    UPDATE public.combo_packs AS c SET
      combo_code = btrim(p_combo->>'combo_code'),
      name = btrim(p_combo->>'name'),
      slug = btrim(p_combo->>'slug'),
      short_title = NULLIF(btrim(p_combo->>'short_title'), ''),
      description = NULLIF(btrim(p_combo->>'description'), ''),
      tagline = NULLIF(btrim(p_combo->>'tagline'), ''),
      image_url = NULLIF(btrim(p_combo->>'image_url'), ''),
      budget_tier = NULLIF(p_combo->>'budget_tier', ''),
      pricing_mode = v_pricing_mode,
      manual_price = CASE WHEN v_pricing_mode = 'MANUAL' THEN v_manual_price ELSE NULL END,
      badge_text = NULLIF(btrim(p_combo->>'badge_text'), ''),
      is_active = COALESCE(NULLIF(p_combo->>'is_active', '')::boolean, true),
      is_featured = COALESCE(NULLIF(p_combo->>'is_featured', '')::boolean, false),
      show_on_homepage = COALESCE(NULLIF(p_combo->>'show_on_homepage', '')::boolean, false),
      display_order = GREATEST(0, COALESCE(NULLIF(p_combo->>'display_order', '')::integer, 0)),
      combo_offer_price = v_offer_price,
      combo_offer_label = NULLIF(btrim(p_combo->>'combo_offer_label'), ''),
      combo_offer_starts_at = NULLIF(p_combo->>'combo_offer_starts_at', '')::timestamptz,
      combo_offer_ends_at = NULLIF(p_combo->>'combo_offer_ends_at', '')::timestamptz,
      metadata = COALESCE(p_combo->'metadata', c.metadata, '{}'::jsonb),
      updated_at = now()
    WHERE c.id = p_combo_id AND c.website_key = 'cart'
    RETURNING c.* INTO v_combo;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'Combo pack not found or not editable' USING ERRCODE = 'P0002';
    END IF;
    v_combo_id := v_combo.id;
  ELSE
    INSERT INTO public.combo_packs (
      website_key, combo_code, name, slug, short_title, description, tagline,
      image_url, budget_tier, pricing_mode, manual_price, badge_text, is_active,
      is_featured, show_on_homepage, display_order, combo_offer_price, combo_offer_label,
      combo_offer_starts_at, combo_offer_ends_at, metadata
    ) VALUES (
      'cart', btrim(p_combo->>'combo_code'), btrim(p_combo->>'name'), btrim(p_combo->>'slug'),
      NULLIF(btrim(p_combo->>'short_title'), ''), NULLIF(btrim(p_combo->>'description'), ''),
      NULLIF(btrim(p_combo->>'tagline'), ''), NULLIF(btrim(p_combo->>'image_url'), ''),
      NULLIF(p_combo->>'budget_tier', ''), v_pricing_mode,
      CASE WHEN v_pricing_mode = 'MANUAL' THEN v_manual_price ELSE NULL END,
      NULLIF(btrim(p_combo->>'badge_text'), ''),
      COALESCE(NULLIF(p_combo->>'is_active', '')::boolean, true),
      COALESCE(NULLIF(p_combo->>'is_featured', '')::boolean, false),
      COALESCE(NULLIF(p_combo->>'show_on_homepage', '')::boolean, false),
      GREATEST(0, COALESCE(NULLIF(p_combo->>'display_order', '')::integer, 0)),
      v_offer_price, NULLIF(btrim(p_combo->>'combo_offer_label'), ''),
      NULLIF(p_combo->>'combo_offer_starts_at', '')::timestamptz,
      NULLIF(p_combo->>'combo_offer_ends_at', '')::timestamptz,
      COALESCE(p_combo->'metadata', '{}'::jsonb)
    ) RETURNING * INTO v_combo;
    v_combo_id := v_combo.id;
  END IF;

  DELETE FROM public.combo_pack_items AS i WHERE i.combo_id = v_combo_id;
  FOR v_item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
    INSERT INTO public.combo_pack_items (
      combo_id, product_id, quantity, display_order, item_label, item_note, updated_at
    ) VALUES (
      v_combo_id,
      (v_item->>'product_id')::uuid,
      (v_item->>'quantity')::integer,
      GREATEST(0, COALESCE(NULLIF(v_item->>'display_order', '')::integer, 0)),
      NULLIF(btrim(v_item->>'item_label'), ''),
      NULLIF(btrim(v_item->>'item_note'), ''),
      now()
    );
  END LOOP;

  SELECT * INTO v_combo FROM public.combo_packs WHERE id = v_combo_id;
  RETURN v_combo;
END;
$function$;

REVOKE ALL ON FUNCTION public.api_admin_save_combo_pack(uuid, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.api_admin_save_combo_pack(uuid, jsonb, jsonb) TO service_role;
NOTIFY pgrst, 'reload schema';

COMMIT;
