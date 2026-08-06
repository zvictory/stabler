import frappe

from stabler.api._common import _company_default_warehouse
from stabler.api.lcv import create_additional_lcv
from stabler.api.purchasing import create_purchase_receipt_from_po, submit_purchase_receipt


def run():
	po_name = "PUR-ORD-2026-00005"
	po = frappe.get_doc("Purchase Order", po_name)
	wh = _company_default_warehouse(po.company)
	po.set_warehouse = wh
	for item in po.items:
		item.warehouse = wh

	if po.docstatus == 0:
		po.submit()
		print("Submitted PO:", po.name)

	# Create Purchase Receipt
	pr_res = create_purchase_receipt_from_po(po_name)
	pr_name = pr_res.get("name")
	print("Created PR:", pr_name)

	# Submit Purchase Receipt
	pr_sub = submit_purchase_receipt(pr_name)
	print("Submitted PR:", pr_sub)

	# Create Landed Cost Voucher
	lcv_res = create_additional_lcv("Purchase Receipt", pr_name)
	print("Created LCV:", lcv_res)

	frappe.db.commit()
