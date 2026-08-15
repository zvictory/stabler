---
description: Multi-tenant discipline — module gating, tenant/feature ownership map, and SPA module access.
paths:
  - "**/router.js"
  - "**/api/**/*.py"
  - "**/doctype/**/*.json"
  - "**/hooks.py"
  - "**/patches.txt"
---

# Tenant & module discipline

Moved verbatim out of CLAUDE.md on 2026-08-15.
Original: `docs/archive/CLAUDE.md.2026-08-15.bak`.

### Module access
- SPA page visibility = `company-enabled AND user-role-allowed`. Admins (System Manager
  / Stabler Admin) always see every module.
- The role→module map lives in `stabler/api/organization.py:_MODULE_ROLES`. When adding
  a new module, register it there.
- Every module's parent route in `router.js` MUST carry `meta: { module: "<key>" }`.
  Without it the route guard can't block direct-URL access.
- This is a **UX access layer**, not a security boundary. Real data security lives in
  Frappe's `has_permission`, which runs on every backend endpoint regardless of what
  the SPA shows.

### Tenant & feature ownership (multi-tenant discipline)
- Stabler is ONE shared app across **7 tenants with different businesses**. Code is
  shared (one `bench restart` hits all 7); DBs are per-site. A feature built for one
  tenant ships to all — so **every tenant-specific feature MUST be module-gated**
  (`enable_*` + role + route `meta.module`) and MUST NOT change shared-core behavior
  for tenants that don't use it.
- **Feature → owner-module → owner-tenant** (know who you're changing things for):

  | Tenant | Business | Owns (primary modules) |
  |--------|----------|------------------------|
  | anjan | Ice-cream **manufacturing** (main prod) | manufacturing, inventory, sales, money |
  | msa | Meat **import**/distribution | imports (PI, PI Groups, Vendor Category, CI, containers), money, purchasing |
  | mikas | **Tender** / kassa | tender, money (kassa bot), purchasing, crm |
  | dts | Industrial belting **sales** | sales, inventory, money |
  | horeca | **HoReCa** services | service, sales, field_sales, money |
  | laminor | *(confirm with owner)* | *(confirm)* |
  | smartbox | *(confirm with owner)* | *(confirm)* |

  So: PI/PI-Groups/Vendor-Category = `imports` = **msa**. Tender boards/bid/landed +
  kassa bot = `tender`/`money` = **mikas**. These must be invisible where the module is off.
- **Module defaults are opt-IN (measured 2026-08-07):** `Stabler Company Modules` carries
  **23** `enable_*` fields and only **4** default to `1` — `money`, `sales`, `purchasing`,
  `inventory`. The other 19 (`tender`, `imports`, `crm`, `hr`, `manufacturing`, `service`,
  `bpm`, …) are OFF for a new company and are enabled per owner-tenant. Keep it that way:
  gate a new module OFF by default. Don't add a **reqd** field to a doctype a non-owner
  tenant also carries. Count it from the doctype JSON, not from memory.
- **Never branch on tenant name** (`if company == "mikas"`). Parametrize by module +
  company-setting (`Stabler Company Modules`), the way currency precision is read as
  metadata. Tenant variance lives in config/data, never in code constants.
- Full rationale + the professional playbook (opt-in defaults, blast-radius / release
  governance, leakage tests, fork criteria): `docs/plans/2026-07-18-multitenant-governance.md`.
