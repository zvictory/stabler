"""Seed 14 demo CRM deals (+ prerequisite CRM Organizations) for demoable pipeline.

Run:
    bench --site anjan.erpstable.com execute stabler.maintenance.seed_crm_demo.seed
    bench --site smartbox.erpstable.com execute stabler.maintenance.seed_crm_demo.seed

Cleanup:
    bench --site <site> execute stabler.maintenance.seed_crm_demo.unseed

Idempotent: re-running seed() when data already exists prints a skip message and exits.
Marker: every demo CRM Organization ends with " [DEMO]" in its organization_name.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, nowdate

DEMO_SUFFIX = " [DEMO]"
DEMO_ORG_NAMES = [
	"Aurora Foods",
	"Bektemir Logistics",
	"Chinor Retail",
	"Delta Pharma",
	"Eurasia Textile",
	"Farg'ona Mills",
	"Gulshan Trade",
	"Horizon Beverages",
	"Iqbol Construction",
	"Jasmin Cosmetics",
	"Karvon Group",
	"Lola Foods",
	"Murod Hardware",
	"Navoiy Cement",
]

# (org_name, status, deal_value, probability, closure_days_offset, lost_reason)
# Status values must match CRM Deal Status records on prod (case-sensitive).
# lost_reason: Link to "CRM Lost Reason" — required when status is "Lost".
DEMO_DEALS = [
	("Aurora Foods", "Qualification", 12000, 20, 30, None),
	("Bektemir Logistics", "Qualification", 8500, 15, 45, None),
	("Chinor Retail", "Demo/Making", 34000, 35, 25, None),
	("Delta Pharma", "Demo/Making", 21000, 30, 20, None),
	("Eurasia Textile", "Proposal/Quotation", 56000, 50, 15, None),
	("Farg'ona Mills", "Proposal/Quotation", 18000, 45, 18, None),
	("Gulshan Trade", "Negotiation", 72000, 65, 10, None),
	("Horizon Beverages", "Negotiation", 43000, 60, 12, None),
	("Iqbol Construction", "Ready to Close", 95000, 80, 7, None),
	("Jasmin Cosmetics", "Ready to Close", 27000, 75, 5, None),
	("Karvon Group", "Won", 120000, 100, -30, None),
	("Lola Foods", "Won", 64000, 100, -20, None),
	("Murod Hardware", "Lost", 15000, 0, -45, "Pricing"),
	("Navoiy Cement", "Lost", 88000, 0, -60, "Competition"),
]


def _guard():
	"""Raise early if the crm app is not installed (fail loud, Rule 12)."""
	if not frappe.db.table_exists("CRM Deal"):
		frappe.throw(
			"CRM Deal table not found. The 'crm' app must be installed on this site before seeding.\n"
			"  bench get-app crm\n"
			"  bench --site <site> install-app crm"
		)


def _demo_org_exists() -> bool:
	return bool(frappe.db.exists("CRM Organization", {"organization_name": ["like", f"%{DEMO_SUFFIX}"]}))


def _pick_users() -> list[str]:
	"""Return up to 2 non-Administrator System Users (Administrator as fallback)."""
	users = frappe.get_all(
		"User",
		filters={"enabled": 1, "user_type": "System User", "name": ["!=", "Administrator"]},
		fields=["name"],
		limit=2,
		order_by="creation asc",
	)
	result = [u.name for u in users]
	if not result:
		result = ["Administrator"]
	return result


def seed():
	"""Create 14 demo CRM Deals across all 7 statuses (idempotent)."""
	_guard()
	if _demo_org_exists():
		print("Demo CRM data already seeded — skipping. Run unseed() first to recreate.")
		return

	currency = frappe.db.get_single_value("Global Defaults", "default_currency") or "USD"
	owners = _pick_users()
	today = nowdate()

	# 1. Create CRM Organization rows.
	org_name_map: dict[str, str] = {}  # short_name -> frappe doc name
	for short_name in DEMO_ORG_NAMES:
		full_name = short_name + DEMO_SUFFIX
		org = frappe.new_doc("CRM Organization")
		org.organization_name = full_name
		org.insert(ignore_permissions=True)
		org_name_map[short_name] = org.name

	# 2. Create CRM Deal rows.
	for i, (short_name, status, deal_value, probability, closure_days, lost_reason) in enumerate(DEMO_DEALS):
		owner = owners[i % len(owners)]
		org_doc_name = org_name_map[short_name]
		deal = frappe.new_doc("CRM Deal")
		deal.organization = org_doc_name
		deal.status = status
		deal.deal_value = deal_value
		deal.expected_deal_value = deal_value
		deal.currency = currency
		deal.probability = probability
		deal.expected_closure_date = add_days(today, closure_days)
		deal.deal_owner = owner
		if lost_reason:
			deal.lost_reason = lost_reason
		org_slug = short_name.lower().replace(" ", "").replace("'", "")
		deal.email = f"contact@{org_slug}.uz"
		deal.mobile_no = f"+998 9{90 + (i % 9)} {100 + i * 7:03d} {2000 + i * 13:04d}"
		deal.insert(ignore_permissions=True)

	frappe.db.commit()
	print(f"Seeded {len(DEMO_DEALS)} demo CRM deals across {len(DEMO_ORG_NAMES)} demo organizations.")


def unseed():
	"""Delete all demo CRM Deals and their [DEMO] organizations."""
	_guard()
	demo_orgs = frappe.get_all(
		"CRM Organization",
		filters={"organization_name": ["like", f"%{DEMO_SUFFIX}"]},
		fields=["name"],
	)
	demo_org_names = [r.name for r in demo_orgs]

	# Delete deals whose organization is a demo org.
	if demo_org_names:
		deals = frappe.get_all(
			"CRM Deal",
			filters={"organization": ["in", demo_org_names]},
			fields=["name"],
		)
		for d in deals:
			frappe.delete_doc("CRM Deal", d.name, ignore_permissions=True, force=True)
		print(f"Deleted {len(deals)} demo deals.")

	# Delete the demo orgs.
	for org in demo_org_names:
		frappe.delete_doc("CRM Organization", org, ignore_permissions=True, force=True)
	print(f"Deleted {len(demo_org_names)} demo organizations.")

	frappe.db.commit()
	print("Unseed complete.")
