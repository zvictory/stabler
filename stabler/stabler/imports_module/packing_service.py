from __future__ import annotations

import frappe

from stabler.stabler.imports_module import packing_math


def summary_for_ci(commercial_invoice: str, company: str) -> dict:
	containers = frappe.get_list(
		"Import Container",
		filters={"commercial_invoice": commercial_invoice, "company": company},
		fields=["name", "container_number"],
		order_by="creation asc",
		limit_page_length=0,
	)
	container_names = [row.name for row in containers]
	rows = (
		frappe.get_all(
			"Import Container Item",
			filters={
				"parent": ["in", container_names],
				"parenttype": "Import Container",
				"parentfield": "items",
			},
			fields=[
				"parent as container",
				"item_code",
				"item_name",
				"box_qty",
				"box_kg",
				"total_kg",
			],
		)
		if container_names
		else []
	)
	expected = packing_math.aggregate_container_items(rows)
	ci_items = frappe.get_all(
		"Commercial Invoice Item",
		filters={
			"parent": commercial_invoice,
			"parenttype": "Commercial Invoice",
			"parentfield": "items",
		},
		fields=["item as item_code", "qty"],
	)
	reconciliation = packing_math.reconcile_ci_items(ci_items, expected)
	containers_with_rows = {row.container for row in rows}
	return {
		"status": packing_math.packing_readiness(
			container_names, containers_with_rows, reconciliation
		),
		"container_count": len(container_names),
		"containers_with_items": len(containers_with_rows),
		"expected_items": expected,
		"reconciliation": reconciliation,
	}


def replace_grn_expected_rows(grn, expected_items: list[dict]) -> None:
	grn.set("grn_items", [])
	for item in expected_items:
		grn.append("grn_items", item)


def create_or_get_grn(ci, *, ignore_permissions: bool) -> dict:
	existing = frappe.db.get_value(
		"GRN Checklist", {"commercial_invoice": ci.name, "company": ci.company}
	)
	summary = summary_for_ci(ci.name, ci.company)
	if existing:
		locked = bool(
			frappe.db.get_value("GRN Checklist", existing, "expected_snapshot_locked")
		)
		return {
			"name": existing,
			"created": False,
			"packing_status": summary["status"],
			"expected_snapshot_locked": locked,
		}

	grn = frappe.new_doc("GRN Checklist")
	grn.company = ci.company
	grn.commercial_invoice = ci.name
	grn.supplier = ci.supplier
	grn.expected_arrival_date = ci.get("eta_transit_port")
	replace_grn_expected_rows(grn, summary["expected_items"])
	grn.insert(ignore_permissions=ignore_permissions)
	return {
		"name": grn.name,
		"created": True,
		"packing_status": summary["status"],
		"expected_snapshot_locked": False,
	}
