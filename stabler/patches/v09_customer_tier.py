"""Multi-tier Customer Custom Fields.

Bootstraps:
  - Customer.tier (Select) — Manufacturer / Distributor / SubDistributor /
    Retailer. Blank default.
  - Customer.parent_distributor (Link to Customer) — for upstream-tier link.

Uses `create_custom_field(...)` which is idempotent — calling it twice is
safe.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute() -> None:
	create_custom_field(
		"Customer",
		{
			"fieldname": "tier",
			"label": "Tier",
			"fieldtype": "Select",
			"options": "\nManufacturer\nDistributor\nSubDistributor\nRetailer",
			"insert_after": "customer_name",
			"description": "Distribution tier for this customer",
		},
	)
	create_custom_field(
		"Customer",
		{
			"fieldname": "parent_distributor",
			"label": "Parent Distributor",
			"fieldtype": "Link",
			"options": "Customer",
			"insert_after": "tier",
			"description": "Upstream distributor for this customer (if any)",
		},
	)
	frappe.db.commit()
