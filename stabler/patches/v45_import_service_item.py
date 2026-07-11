"""Create the "Import Service" service Item for Import Expense Purchase Invoices.

The Import Expense on_update hook books a non-transport expense (customs,
handling, storage, documentation, insurance, border crossing, other) as a DRAFT
Purchase Invoice, and ERPNext rejects item-less PIs — so the expense is a single
non-stock service line against this one shared Item (see
stabler/stabler/imports_module/payment_math.IMPORT_SERVICE_ITEM_CODE). A single
Item keeps the chart simple; the expense category + description ride on the PI
line so the detail is preserved. (Transport-category expenses are billed by the
truck CROSSED_BORDER hook against the "Cross-Border Transport" item from v43.)

Idempotent: no-op if the Item already exists. Best-effort item-group / UOM pick,
mirroring v43. Listed under [post_model_sync]; Item is a core doctype so it is
safe pre- or post-sync.
"""

import frappe

_ITEM_CODE = "Import Service"


def _pick_item_group():
	for group in ("Services", "All Item Groups"):
		if frappe.db.exists("Item Group", group):
			return group
	return frappe.db.get_value("Item Group", {"is_group": 0}, "name") or frappe.db.get_value(
		"Item Group", {}, "name"
	)


def execute():
	if frappe.db.exists("Item", _ITEM_CODE):
		return
	item_group = _pick_item_group()
	if not item_group:
		return

	uom = "Nos"
	if not frappe.db.exists("UOM", uom):
		if frappe.db.exists("UOM", "Dona"):
			uom = "Dona"
		elif frappe.db.exists("UOM", "Unit"):
			uom = "Unit"
		else:
			uom = frappe.db.get_value("UOM", {}, "name")

	doc = frappe.new_doc("Item")
	doc.item_code = _ITEM_CODE
	doc.item_name = _ITEM_CODE
	doc.item_group = item_group
	doc.stock_uom = uom
	doc.is_stock_item = 0
	doc.is_purchase_item = 1
	doc.is_sales_item = 0
	doc.description = (
		"Import expense service — expense-only line for non-transport Import "
		"Expense Purchase Invoices (customs, handling, storage, documentation, etc.)."
	)
	doc.insert(ignore_permissions=True)
