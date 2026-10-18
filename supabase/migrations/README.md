# Supabase migration source

Migration files in this directory track additive schema changes applied to the shared Supabase database.

- `20261018042121_server_authorized_combo_admin_api.sql` was applied to project `ypmiinmkyvzdpakbkers` on 18 October 2026 and verified through the Supabase SQL API.
- It configures a public-read-only combo image bucket and adds a combo save RPC executable only by the Supabase `service_role`.
- It does not rewrite/delete any existing combo, product, order, mail, or theme records.

When recreating an environment, first compare the recorded Supabase migration list with these files. Never replay base-schema builds against an existing production database.
