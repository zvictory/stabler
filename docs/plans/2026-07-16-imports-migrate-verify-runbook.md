# Imports (WP-I1…I7) — Local Migrate & Verify Runbook

Scope: **local `frappe-bench-local` only** — NOT prod. Nothing here touches
`anjan.erpstable.com`, rsync, or `git push`. Run from the bench root
(`/Users/zafar/frappe-bench-local`), not the app dir.

What this exercises: 2 new doctypes (Proforma Invoice + child), 2 patches
(v50 CI cash/bank earmark, v51 CI↔Proforma link), and the SPA (Proforma page,
Vendor Center exposure + Convert-to-Invoice).

---

## 0. Pick the site

```bash
cd /Users/zafar/frappe-bench-local
ls sites | grep -v -E 'assets|apps.txt|common_site|\.json|\.pem'   # your local site name
SITE=<local-site>            # e.g. stabler.localhost — set once for the commands below
bench --site "$SITE" list-apps | grep stabler   # confirm stabler is installed here
```

## 1. Migrate (doctype sync + patches)

```bash
bench --site "$SITE" migrate
```

Watch for a clean run. The two patches are registered under `[post_model_sync]`
(patches.txt L55–56), so they run **after** the DDL adds the new columns — no
"unknown column" abort. Expected new schema:

- `tabProforma Invoice` + `tabProforma Invoice Item` tables created.
- `Commercial Invoice`: `custom_bank_agreed`, `custom_cash_agreed` (v50),
  `custom_proforma_invoice` (v51).

Spot-check:

```bash
bench --site "$SITE" mariadb -e "SHOW COLUMNS FROM \`tabCommercial Invoice\` LIKE 'custom_%agreed';"
bench --site "$SITE" mariadb -e "SELECT name FROM tabDocType WHERE name LIKE 'Proforma%';"
```

## 2. Build the SPA

```bash
bench build --app stabler
```

Compiles the new `ProformaInvoices.vue`, the `Suppliers.vue` exposure/convert
changes, the router route, and the status map. If build fails, it prints the
offending file — fix before browser testing.

## 3. Unit tests (fast, no browser)

```bash
cd /Users/zafar/frappe-bench-local/apps/stabler
PYTHONPATH=$PWD python3 -m unittest \
  stabler.tests.test_ci_to_pinv \
  stabler.tests.test_import_exposure \
  stabler.tests.test_vendor_exposure_isolation \
  stabler.tests.test_proforma_transition \
  stabler.tests.test_proforma_invoice_doctype
```

Expect `OK`. These cover the no-double-count invariant, advance-allocation
capping, the earmark identity, and tenant isolation.

## 4. Enable the module on a company

The whole imports surface is gated on `enable_imports`. This is **not** a
`Company` field — it lives on the `Stabler Company Modules` child row
(`company_modules` table of the `Stabler Settings` Single doctype), one row
per company. `set-value Company ... enable_imports 1` will fail with
`Unknown column 'enable_imports' in tabCompany`. Use the app's own accessor
instead, via `bench console`:

```bash
bench --site "$SITE" console
```

```python
import frappe
from stabler.stabler.doctype.stabler_settings.stabler_settings import get_company_module_row

row = get_company_module_row("<Your Company>")
row.enable_imports = 1
row.save(ignore_permissions=True)
frappe.db.commit()
print("SAVED", row.company, row.enable_imports)
```

(or toggle it in the SPA's company settings if that page exposes it). Your user
must be **System Manager** or hold an imports role, and be **cost-visible**, or
the Convert preview will refuse.

## 5. Browser smoke — the I1→I6 arc

Open `…/stabler#/imports/proformas`.

1. **Create a Proforma** — supplier, PI date, `agreed_total`, and a bank/cash
   split. The Save button stays disabled until `bank_agreed + cash_agreed ==
   agreed_total` (earmark identity). Save → it appears in the list.
2. **Supersede** — on that PI, "Link CI" → pick a Commercial Invoice for the
   same supplier → confirm. PI status flips to `SUPERSEDED_BY_CI`; the CI now
   carries `custom_proforma_invoice`.
3. **Vendor Center** (`…/stabler#/purchasing/suppliers`) → select that supplier.
   The **Import Exposure** panel shows open commitment + cash/bank paid; the
   **Open commitments** table lists the CI (link opens the CI *inside* Stabler,
   never the Desk).
4. **Convert to Invoice** — click it. The preview modal is a **dry run**
   (nothing is written): it shows agreed total, invoice-lines total, the
   reconciliation check, and the advance-allocation plan. If the lines don't
   reconcile to `agreed_total`, the Confirm button is disabled by design.
5. **Confirm** → a **DRAFT** Purchase Invoice is created (not submitted). Verify:

```bash
bench --site "$SITE" mariadb -e "SELECT name, docstatus, grand_total, custom_commercial_invoice FROM \`tabPurchase Invoice\` WHERE custom_commercial_invoice IS NOT NULL ORDER BY creation DESC LIMIT 3;"
```

   - `docstatus = 0` (draft — Accounts submits it to post GL).
   - `grand_total == agreed_total` of the CI (docs_total is NOT used).
   - Back in the Vendor Center, the CI has **dropped out** of Open commitments
     (the no-double-count seam: it's now on the PInv, not in virtual exposure).
6. **Idempotency** — click Convert on the same CI again → it returns the
   existing draft, doesn't make a second one.

## 6. Regression smoke (CLAUDE.md record-form class)

Direct-URL refresh must open populated, not a blank "New" form. Paste an
existing CI URL and hit refresh:

```
…/stabler#/imports/commercial-invoices/<an existing CI name>
```

It must render the CI in view/edit state.

---

## Notes / known follow-ups

- **i18n**: new UI strings currently render in English (their `t()` source).
  ru/uz/uzc/tr are deferred to **WP-I8** (CSV harvest) because the translation
  CSVs are mid-churn from another work stream.
- **set_advances()** on the draft PInv is ERPNext's own method (guarded, degrades
  to no advances if it can't run). On the first real conversion, eyeball that it
  pulled the right Payment Entry rows into the draft's Advances table.
- **Rollback (local)**: none needed for a bad smoke — the patches are
  idempotent and the only writes are a draft PInv you can delete. To re-run a
  patch: `bench --site "$SITE" execute stabler.patches.v51_ci_proforma_link.execute`.
- **Prod**: out of scope here. When you're ready, follow the CLAUDE.md deploy
  procedure (backup tar → rsync → build → migrate → restart) — and remember
  `bench restart` blips all 6 stabler tenants.
```
