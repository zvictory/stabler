"""Create the "Cross-Border Transport" service Item.

The Import Truck CROSSED_BORDER hook books the trucking cost as a Purchase
Invoice, and ERPNext rejects item-less PIs — so the transport is a single
non-stock service line against this Item (see
stabler/stabler/imports_module/hooks.py and payment_math.XBORDER_ITEM_CODE).

Idempotent: no-op if the Item already exists. Best-effort item group pick
(Services -> All Item Groups -> any non-group), so the patch works on a bench
whose Item Group tree differs. Listed under [post_model_sync]; Item is a core
doctype so it is safe pre- or post-sync.
"""

import frappe

_ITEM_CODE = "Cross-Border Transport"


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
		"Cross-border (Iran to Uzbekistan) trucking service — expense-only line "
		"for cross-border transport Purchase Invoices."
	)
	doc.insert(ignore_permissions=True)
