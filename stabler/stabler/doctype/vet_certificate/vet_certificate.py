"""Vet Certificate controller.

Regulatory document blocking GRN Checklist completion until an approved,
unexpired certificate exists for the Commercial Invoice (meat-import vet
requirement). Non-submittable — a plain reviewed master.

`has_valid_vet_cert(commercial_invoice)` is the single source of truth for the
GRN before_submit gate (imports_module/hooks.grn_before_submit).
"""

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, today


class VetCertificate(Document):
	def validate(self) -> None:
		# Auto-expire: an Approved certificate past its expiry is no longer valid.
		if self.status == "Approved" and self.expiry_date and getdate(self.expiry_date) < getdate(today()):
			self.status = "Expired"


def has_valid_vet_cert(commercial_invoice) -> bool:
	"""True when an Approved, unexpired Vet Certificate exists for the CI."""
	if not commercial_invoice:
		return False
	return bool(
		frappe.db.exists(
			"Vet Certificate",
			{
				"commercial_invoice": commercial_invoice,
				"status": "Approved",
				"expiry_date": [">=", today()],
			},
		)
	)
