# RTCrackers integrated platform guide

This branch connects the existing storefront, mail portal, admin workspace and Supabase-backed content settings. The portfolio remains at the domain root; the active shop, combo catalogue, admin login and mail portal are served at same-origin paths.

## Entry points

- Portfolio / main website: `/`
- Active shopping website: `/cart/`
- Combo catalogue: `/combos`
- Administrator login: `/admin`
- Mail portal: `/mail`

The Nginx configuration serves `FRONTEND/WEB` at the root, mounts `FRONTEND/SITE` under `/cart/`, and mounts `FRONTEND/EMAIL` under `/FRONTEND/EMAIL/`. The public APIs stay same-origin, while the admin API is routed separately from the customer API.

## Combo-pack management

The catalogue reads public, active cart-site combo data from `public.combo_pack_catalogue`. The admin API reads and writes combo records through a server-only Supabase key and the transaction-safe `api_admin_save_combo_pack` RPC.

Supported fields: code, name, slug, image, budget tier, item list and quantities, live-sum or manual price, homepage/featured flags, display order, active state, and dated offer price/label. Deactivation is a soft state change; it does not delete history or item rows.

Image upload accepts JPG, PNG, WebP and AVIF up to 5 MB. Uploads use the public-read `combo-pack-images` Storage bucket; writes use the server-side service-role credential only.

## Database-backed themes and content

The customer API exposes public read-only `GET /api/v1/cms/theme/{website_key}/{page_key}` with the publishable key and RLS policies. The admin API exposes:
- `GET /api/v1/admin/cms/theme-pages`
- `GET /api/v1/admin/cms/theme-components`
- `PATCH /api/v1/admin/cms/theme-pages/{theme_page_id}`
- `PATCH /api/v1/admin/cms/theme-components/{theme_component_id}`

The PATCH endpoints use field allowlists and cannot change a row's `website_key`, `page_key`, or component identity. The theme loader only changes colors, typography, component copy and CSS; viewport dimensions and zoom are local browser presentation state, never database fields.

## Mail portal

The mail UI uses `/api/v1/admin/mail` and the existing `mailboxes`, `email_messages`, and `email_recipients` tables. The API supports mailbox list, inbox/sent/starred/archive/trash/drafts/search, message detail, read/unread, star/unstar, archive/restore/trash, draft creation, send, and provider status updates. Untrusted HTML message content is rendered in a sandboxed iframe.

Resend integration:
- Outbound API: `RESEND_API_KEY` and a verified `RESEND_FROM_NAME` / sending mailbox.
- Inbound/status webhook: `POST /api/v1/admin/mail/webhook/resend`.
- Configure the Resend webhook signing secret as `RESEND_WEBHOOK_SECRET` and subscribe to `email.received`, `email.delivered`, `email.bounced`, `email.complained`, `email.failed`, and `email.sent` events.
- The webhook validates Svix signature and timestamp, records inbound message bodies and recipients, and deduplicates retries by webhook ID.

Provider credentials and domain/webhook configuration are environment-specific and are intentionally not checked into this repository.

## Required Admin API environment

Configure these in the Admin API deployment environment (not browser JS):

```dotenv
SUPABASE_URL=https://ypmiinmkyvzdpakbkers.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<secret service-role key>
SUPABASE_STORAGE_BUCKET=combo-pack-images
MAX_UPLOAD_MB=5
RESEND_API_KEY=<server-side Resend API key>
RESEND_FROM_NAME=RT Crackers
RESEND_WEBHOOK_SECRET=<Resend/Svix webhook signing secret>
```

The customer API needs `SUPABASE_URL` and the Supabase publishable key (`SUPABASE_PUBLISHABLE_KEY`) for public theme and combo reads. Never put the service-role key in static assets or browser bundles.

The HTTP-only cookie defaults assume HTTPS in production. Terminate TLS at the hosting edge and ensure forwarded protocol/cookie settings match that deployment.

## Supabase migration status

Migration source: `supabase/migrations/20261018042121_server_authorized_combo_admin_api.sql`.

This additive migration has already been applied to the connected production project and verified. It adds the bucket and server-role-only combo-save RPC. It does not delete or rewrite existing products, orders, combo packs, mail messages, or theme rows. Always inspect `supabase_migrations.schema_migrations` before replaying a migration; do not replay base schema builds into an existing database.

## Final production validation steps

1. Add the server secrets listed above to the hosting environment, redeploy/restart Admin and Customer APIs and Nginx.
2. Add the Resend inbound webhook URL and event types in the Resend dashboard.
3. Sign in at `/admin`; verify combo list shows 24 existing active packs, edit a test pack, upload an image, save and reload it.
4. Check `/combos` and the home combo section from an anonymous session; verify offers and contents.
5. Sign in at `/mail`; verify folder operations, send a test message, then receive a message through the configured Resend webhook.
6. Test browser zoom/resize at multiple viewports; confirm no layout preferences are sent to the database.

Live production counts and RLS are checked via Supabase tooling. End-to-end sending, receiving, image upload from the deployed app and cross-device browser checks cannot be claimed until the hosting credentials and provider configuration above are supplied to the deployed service.
