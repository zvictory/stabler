"""Vehicle Finance Settings — one row per company (`autoname: field:company`).

`installment_engine` defaults to Legacy, so Agreement V1 stays dormant until a
company explicitly opts in. Rows are created lazily (no seed patch: a patch
runs pre-DDL-sync on fresh installs and the table would not exist yet).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now

LEGACY = "Legacy"
AGREEMENT_V1 = "Agreement V1"


def get_engine(company: str) -> str:
	"""Engine for `company`, defaulting to Legacy when no row exists yet."""
	engine = frappe.db.get_value("Vehicle Finance Settings", {"company": company}, "installment_engine")
	return engine or LEGACY


class VehicleFinanceSettings(Document):
	def validate(self) -> None:
		if self.has_value_changed("accounting_policy_approved") and self.accounting_policy_approved:
			self.accounting_policy_approved_by = frappe.session.user
			self.accounting_policy_approved_on = now()
		if self.installment_engine == AGREEMENT_V1 and not self.accounting_policy_approved:
			frappe.throw(
				_("Agreement V1 cannot be enabled before the accounting policy is approved.")
			)
