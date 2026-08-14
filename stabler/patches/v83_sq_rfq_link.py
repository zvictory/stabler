"""Link Supplier Quotation records to the specific RFQ they answer.

Mirrors v68 (custom_crm_deal on Request for Quotation) and v30 (custom_crm_deal
on Supplier Quotation). This provides round-based response tracking so that
an RFQ can distinguish responses to a specific request round from quotations
submitted in other rounds of the same lot.

Idempotent: guarded by a Custom Field existence check, a DocType check, and a
backfill that only ever writes rows whose `custom_rfq` is still empty.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	if not frappe.db.exists("DocType", "Supplier Quotation"):
		return
	if not frappe.db.exists("DocType", "Request for Quotation"):
		return
	already_installed = {"dt": "Supplier Quotation", "fieldname": "custom_rfq"}
	if not frappe.db.exists("Custom Field", already_installed):
		create_custom_fields(
			{
				"Supplier Quotation": [
					{
						"fieldname": "custom_rfq",
						"label": "RFQ",
						"fieldtype": "Link",
						"options": "Request for Quotation",
						"insert_after": "custom_crm_deal",
						"no_copy": 1,
						"in_list_view": 1,
					}
				]
			},
			ignore_validate=True,
		)
	_backfill_rfq_from_deal()


def _backfill_rfq_from_deal():
	"""Point pre-v83 quotations at their RFQ where that RFQ is unambiguous.

	A custom field's default only reaches new documents, so every quotation
	recorded before this patch carries an empty `custom_rfq`. Where the deal
	has exactly one open RFQ there is only one answer it can be, so write it.
	Deals with several RFQs (or none) are left alone — guessing a round is
	worse than the `get_rfq` fallback that keeps unstamped quotations visible.

	Idempotent: only ever fills rows that are still empty.
	"""
	if not frappe.db.has_column("Supplier Quotation", "custom_rfq"):
		return
	if not frappe.db.has_column("Supplier Quotation", "custom_crm_deal"):
		return
	if not frappe.db.has_column("Request for Quotation", "custom_crm_deal"):
		return

	rfqs = frappe.db.sql(
		"""
		select custom_crm_deal as deal, name
		from `tabRequest for Quotation`
		where docstatus < 2 and ifnull(custom_crm_deal, '') != ''
		""",
		as_dict=True,
	)
	by_deal: dict[str, list[str]] = {}
	for row in rfqs:
		by_deal.setdefault(row.deal, []).append(row.name)

	for deal, names in by_deal.items():
		if len(names) != 1:
			continue
		frappe.db.sql(
			"""
			update `tabSupplier Quotation`
			set custom_rfq = %s
			where ifnull(custom_rfq, '') = '' and custom_crm_deal = %s
			""",
			(names[0], deal),
		)
