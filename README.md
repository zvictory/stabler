# Stabler

> Financial operations, simplified.

A native Frappe app delivering a polished, standalone-feeling product surface on
top of ERPNext. Users see a calm, focused workspace at `/stabler/*` — never the
word "ERPNext" — backed by the full ERPNext data model.

## Modules

| Area           | Vocabulary used in UI       | Backed by                                                  |
|----------------|-----------------------------|------------------------------------------------------------|
| **Dashboard**  | Cash, Receivable, Payable, Revenue MTD | GL Entry, Sales/Purchase Invoice                |
| **Money**      | Chart of Accounts, Journals, Payments, Reports | Account, Journal Entry, Payment Entry   |
| **Sales**      | Customers, Sales Invoices, AR Aging | Customer, Sales Invoice                              |
| **Purchasing** | Suppliers, Purchase Invoices, AP Aging | Supplier, Purchase Invoice                        |
| **Inventory**  | Items, Warehouses, Stock Ledger, Low Stock Alerts | Item, Warehouse, Bin, Stock Ledger Entry, Item Reorder |

## Tech Stack

- **Server** — Frappe v16 + ERPNext v16 (MariaDB)
- **Shell** — Tabler 1.x (Bootstrap 5, Tabler Icons, ApexCharts)
- **SPA** — Vue 3 (`<script setup>`) + Pinia 2 + Vue Router 4 (hash mode)
- **HTTP** — native `fetch` with `X-Frappe-CSRF-Token` interceptor
- **Build** — `frappe build --app stabler` (esbuild, auto-discovers `*.bundle.{js,css}`)

## Setup

```bash
# Install the app into a site
bench --site <site-name> install-app stabler

# Build assets (rerun after editing public/js or public/css)
bench build --app stabler

# Start the dev server
bench start
```

Navigate to `http://<host>/stabler` — authenticated users land on
`/stabler/#/dashboard`. The `/` redirect at the SPA layer ensures any URL
without a route falls through to a 404 page (see `pages/NotFound.vue`).

## Desk gate

Stabler intentionally hides Frappe's built-in `/app` and `/desk` from non-admin
users so the product feels standalone. This is enforced by a `before_request`
hook in `stabler/middleware/desk_gate.py`.

**Default behavior:**
- Users with the **System Manager** role can still access `/app/*` and
  `/desk/*` to administer the underlying ERPNext install.
- All other users see a 403 if they try to load those URLs directly.

**Opting power users back into `/desk`:**
The gate checks for `System Manager`. To grant a non-admin user access to the
classic desk:
1. Visit `/app/user/<email>` in the admin desk.
2. Add the `System Manager` role (or any role you add to the allowlist in
   `desk_gate.py`).
3. The user can now load `/app` directly while still using `/stabler` as their
   default workspace.

To widen the allowlist (e.g. grant `Accounts Manager` desk access without
making them System Managers), edit the role check in
`stabler/middleware/desk_gate.py` and restart bench.

## Project layout

```
stabler/
├── api/                    # whitelisted Python endpoints per module
├── middleware/desk_gate.py # /app + /desk gate
├── public/
│   ├── css/                # Tabler theme + overrides
│   ├── js/                 # Vue SPA source (bundled by esbuild)
│   │   ├── api/            # fetch client + module SDKs
│   │   ├── stores/         # Pinia stores (session, etc.)
│   │   ├── pages/          # route components
│   │   └── components/     # shared layout + table primitives
│   ├── icons/              # scale.svg (logo)
│   └── illustrations/      # empty-state SVGs (optional)
├── www/                    # /stabler route controller + Tabler shell
└── translations/           # en / ru / uz / uzc CSVs
```

## License

MIT
