"""Link existing tender lots to Tender Master parents (one-time data migration).

Why
---
The Tender Master module (v61) defines a tender lot as `CRM Deal.deal_type ==
"Tender"` with a `custom_parent_tender` link. Every lot created BEFORE v61
carries v60's default `deal_type = "Standard"` and no parent, so the new
`#/tender/crm` board and its orphan queue see nothing — while the funnel
dashboard (which classifies lots by tagged SO/PO/SQ evidence and intake) still
counts them. This script closes that definition gap for ONE company:

  1. finds every deal the funnel already treats as a tender lot
     (`stabler.api.tender._tender_deal_names`) plus any deal already typed
     Tender but parentless (the orphan queue);
  2. groups them into parent tenders — by the deal's `tender_no` when set,
     otherwise one parent per lot keyed by the intake `lot_no` (or the deal
     name as a last resort);
  3. creates the missing `Tender Master` records and links each lot
     (`deal_type = "Tender"`, `custom_parent_tender = <master>`).

Safety
------
- DRY-RUN BY DEFAULT: without `apply=1` nothing is written; the full plan is
  printed so it can be reviewed first.
- Idempotent: already-linked lots are skipped; parents are matched by
  (company, tender_number) before anything is created, so re-running after a
  partial failure is safe.
- Tenant-safe: parametrized by `company`; refuses to run where the tender
  module is off; never branches on a tenant name (CLAUDE.md rule).
- Writes use `frappe.db.set_value(update_modified=False)` — no hooks fire, no
  modified-stamp churn on historical lots. The conditional parent requirement
  in `validate_deal_parent_tender` only guards NEW documents, so this
  migration neither trips it nor needs to bypass validation.

Usage
-----
  # dry-run (prints the plan, writes nothing):
  bench --site mikas.erpstable.com execute \
    stabler.maintenance.link_tender_lots.run --kwargs "{'company': 'Mikas'}"

  # apply:
  bench --site mikas.erpstable.com execute \
    stabler.maintenance.link_tender_lots.run --kwargs "{'company': 'Mikas', 'apply': 1}"

  # optionally leave demo records alone (organization prefix match):
  ... --kwargs "{'company': 'Mikas', 'apply': 1, 'skip_org_prefix': 'ZDEMO'}"
"""

from __future__ import annotations

import frappe

_logger = frappe.logger("stabler.link_tender_lots")

#: CRM Deal `tender_source` → Tender Master `source` select option.
_SOURCE_MAP = {
	"Portal": "Portal",
	"Direct": "Direct",
	"Web": "Portal",
	"Telegram": "Other",
}


def run(company: str, apply: int = 0, skip_org_prefix: str | None = None):
	from stabler.api.tender import _read_intake, _tender_deal_names
	from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

	apply = bool(int(apply or 0))

	if not frappe.db.exists("Company", company):
		frappe.throw(f"Unknown company: {company}")
	if not module_map_for(company).get("tender"):
		frappe.throw(f"Tender module is not enabled for {company} — refusing to migrate.")
	for column in ("deal_type", "custom_parent_tender"):
		if not frappe.db.has_column("CRM Deal", column):
			frappe.throw(f"CRM Deal.{column} is missing — run `bench migrate` first (v60/v61).")
	if not frappe.db.exists("DocType", "Tender Master"):
		frappe.throw("Tender Master doctype is missing — run `bench migrate` first (v61).")

	# --- 1 · candidates: funnel-recognised lots ∪ typed-but-orphaned lots ----
	names = set(_tender_deal_names(company))
	for row in frappe.get_all(
		"CRM Deal",
		filters={"company": company, "deal_type": "Tender", "custom_parent_tender": ["is", "not set"]},
		fields=["name"],
		limit_page_length=0,
	):
		names.add(row.name)

	# `tender_no` / `tender_source` come from the v27 Custom Field patch, which
	# returns early on sites where `CRM Deal` did not yet exist when it ran — so
	# they are genuinely absent on some tenants. Select them only when present
	# (same guard `sales.py` already applies to `tender_no`); when missing, the
	# group key falls back to the intake `lot_no`, i.e. one parent per lot.
	fields = ["name", "company", "organization", "deal_type", "custom_parent_tender"]
	for optional in ("tender_no", "tender_source"):
		if frappe.db.has_column("CRM Deal", optional):
			fields.append(optional)

	deals = (
		frappe.get_all(
			"CRM Deal",
			filters={"name": ["in", sorted(names)]},
			fields=fields,
			limit_page_length=0,
		)
		if names
		else []
	)

	default_currency = frappe.get_cached_value("Company", company, "default_currency")
	plan: list[dict] = []
	skipped_linked = skipped_foreign = skipped_prefix = 0

	for deal in deals:
		if deal.company != company:
			skipped_foreign += 1
			continue
		if skip_org_prefix and str(deal.organization or "").startswith(skip_org_prefix):
			skipped_prefix += 1
			continue
		if deal.custom_parent_tender:
			skipped_linked += 1
			continue

		intake = _read_intake(deal.name)
		lot_no = str(intake.get("lot_no") or "").strip()
		buyer = str(intake.get("buyer") or "").strip()

		# Group key: an explicit tender number groups sibling lots under one
		# parent; otherwise every lot becomes its own tender (safe default —
		# merging parents later is a UI action, splitting them is not).
		group_key = str(deal.get("tender_no") or "").strip() or lot_no or deal.name

		plan.append(
			{
				"deal": deal.name,
				"organization": deal.organization or "",
				"group_key": group_key,
				"buyer": buyer or (deal.organization or "—"),
				"deadline": intake.get("bid_deadline") or None,
				"source": _SOURCE_MAP.get(
					str(deal.get("tender_source") or ""),
					"UZEX" if lot_no.upper().startswith("UZEX") else "Other",
				),
				"needs_type": deal.deal_type != "Tender",
			}
		)

	groups: dict[str, list[dict]] = {}
	for row in plan:
		groups.setdefault(row["group_key"], []).append(row)

	mode = "APPLY" if apply else "DRY-RUN"
	print(
		f"[{mode}] {company}: {len(deals)} candidates — "
		f"{len(plan)} to link across {len(groups)} parent tenders; "
		f"skipped: {skipped_linked} already linked, {skipped_foreign} foreign-company, "
		f"{skipped_prefix} by prefix."
	)

	created = linked = reused = 0
	for group_key, rows in sorted(groups.items()):
		master_name = frappe.db.get_value(
			"Tender Master", {"company": company, "tender_number": group_key}, "name"
		)
		if master_name:
			reused += 1
			action = f"reuse {master_name}"
		elif apply:
			master = frappe.new_doc("Tender Master")
			master.update(
				{
					"company": company,
					"title": (f"{rows[0]['buyer']} · {group_key}")[:140],
					"tender_number": group_key,
					"buyer_name": rows[0]["buyer"][:140] or "—",
					"source": rows[0]["source"],
					"submission_deadline": rows[0]["deadline"],
					"currency": default_currency,
				}
			)
			master.insert(ignore_permissions=True)
			master_name = master.name
			created += 1
			action = f"create {master_name}"
		else:
			master_name = "<new>"
			created += 1
			action = "create <new>"

		print(f"  {action}  «{group_key}»  ← {len(rows)} lot(s)")
		for row in rows:
			suffix = " (+deal_type)" if row["needs_type"] else ""
			print(f"     · {row['deal']}  {row['organization'][:60]}{suffix}")
			if not apply:
				continue
			if row["needs_type"]:
				frappe.db.set_value("CRM Deal", row["deal"], "deal_type", "Tender", update_modified=False)
			frappe.db.set_value(
				"CRM Deal", row["deal"], "custom_parent_tender", master_name, update_modified=False
			)
			linked += 1

	if apply:
		frappe.db.commit()
		_logger.info("link_tender_lots %s: created=%s reused=%s linked=%s", company, created, reused, linked)
	print(
		f"[{mode}] done — parents created: {created}, reused: {reused}, "
		f"lots linked: {linked if apply else len(plan)}{'' if apply else ' (planned)'}"
	)
	return {"created": created, "reused": reused, "linked": linked, "planned": len(plan)}
