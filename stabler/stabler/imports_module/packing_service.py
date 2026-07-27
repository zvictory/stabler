from __future__ import annotations

from contextlib import contextmanager

import frappe

from stabler.stabler.imports_module import packing_math


@contextmanager
def allow_expected_snapshot_update():
	"""Authorize one server-side GRN snapshot write in the current request."""
	previous = frappe.flags.get("in_grn_snapshot_update")
	frappe.flags.in_grn_snapshot_update = True
	try:
		yield
	finally:
		if previous is None:
			frappe.flags.pop("in_grn_snapshot_update", None)
		else:
			frappe.flags.in_grn_snapshot_update = previous


def lock_commercial_invoices(commercial_invoices) -> None:
	"""Serialize packing readers and writers on canonical CI rows."""
	for commercial_invoice in sorted({name for name in commercial_invoices if name}):
		frappe.db.sql(
			"""SELECT name
			FROM `tabCommercial Invoice`
			WHERE name = %s
			FOR UPDATE""",
			commercial_invoice,
		)


def summary_for_ci(commercial_invoice: str, company: str, *, for_update: bool = False) -> dict:
	containers = frappe.get_list(
		"Import Container",
		filters={"commercial_invoice": commercial_invoice, "company": company},
		fields=["name", "container_number"],
		order_by="creation asc",
		limit_page_length=0,
	)
	container_names = [row.name for row in containers]
	scoped_count = frappe.db.count(
		"Import Container",
		filters={"commercial_invoice": commercial_invoice, "company": company},
	)
	if scoped_count != len(container_names):
		frappe.throw(frappe._("Cannot verify all container packing lists with your current permissions."))
	if for_update:
		containers = _lock_visible_containers(commercial_invoice, company, container_names)
	rows = (
		frappe.db.get_values(
			"Import Container Item",
			filters={
				"parent": ["in", container_names],
				"parenttype": "Import Container",
				"parentfield": "items",
			},
			fieldname=[
				"parent as container",
				"item_code",
				"item_name",
				"box_qty",
				"box_kg",
				"total_kg",
			],
			for_update=True,
			as_dict=True,
		)
		if for_update and container_names
		else frappe.get_all(
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
	ci_item_filters = {
		"parent": commercial_invoice,
		"parenttype": "Commercial Invoice",
		"parentfield": "items",
	}
	ci_items = (
		frappe.db.get_values(
			"Commercial Invoice Item",
			filters=ci_item_filters,
			fieldname=["item as item_code", "qty"],
			for_update=True,
			as_dict=True,
		)
		if for_update
		else frappe.get_all(
			"Commercial Invoice Item",
			filters=ci_item_filters,
			fields=["item as item_code", "qty"],
		)
	)
	reconciliation = packing_math.reconcile_ci_items(ci_items, expected)
	containers_with_rows = {row.container for row in rows}
	return {
		"status": packing_math.packing_readiness(container_names, containers_with_rows, reconciliation),
		"container_count": len(container_names),
		"containers_with_items": len(containers_with_rows),
		"expected_items": expected,
		"reconciliation": reconciliation,
	}


def _lock_visible_containers(commercial_invoice: str, company: str, container_names: list[str]) -> list:
	if not container_names:
		return []
	placeholders = ", ".join(["%s"] * len(container_names))
	containers = frappe.db.sql(
		f"""SELECT name, container_number
		FROM `tabImport Container`
		WHERE commercial_invoice = %s
			AND company = %s
			AND name IN ({placeholders})
		ORDER BY creation ASC
		FOR UPDATE SKIP LOCKED""",
		(commercial_invoice, company, *container_names),
		as_dict=True,
	)
	if len(containers) != len(container_names):
		frappe.throw(frappe._("Container packing is being changed by another user. Please try again."))
	return containers


def replace_grn_expected_rows(grn, expected_items: list[dict]) -> None:
	grn.set("grn_items", [])
	for item in expected_items:
		grn.append("grn_items", item)


def create_or_get_grn(ci, *, ignore_permissions: bool) -> dict:
	existing = frappe.db.get_value("GRN Checklist", {"commercial_invoice": ci.name, "company": ci.company})
	if existing:
		return {"name": existing, "created": False}

	summary = summary_for_ci(ci.name, ci.company)
	grn = frappe.new_doc("GRN Checklist")
	grn.company = ci.company
	grn.commercial_invoice = ci.name
	grn.supplier = ci.supplier
	grn.expected_arrival_date = ci.get("eta_transit_port")
	replace_grn_expected_rows(grn, summary["expected_items"])
	try:
		grn.insert(ignore_permissions=ignore_permissions)
	except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
		winner = frappe.db.get_value("GRN Checklist", {"commercial_invoice": ci.name, "company": ci.company})
		if not winner:
			raise
		return {"name": winner, "created": False}
	return {
		"name": grn.name,
		"created": True,
		"packing_status": summary["status"],
		"expected_snapshot_locked": False,
	}
