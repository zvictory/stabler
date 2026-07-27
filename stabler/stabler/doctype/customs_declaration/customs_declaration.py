"""Customs Declaration (GTD) controller.

Non-submittable operational document: the clearance lifecycle is enforced as a
one-way status pipeline via the shared ``assert_transition`` helper (Draft ->
Submitted -> Under Review -> Approved, with Rejected as a dead end and a
privileged single-step backward correction for an Imports Manager).

The GTD is the source of the Uzbekistan import duty + excise that feed the
Landed Cost Voucher (see imports_module/lcv_math.apply_gtd_customs_precedence);
the child lines carry SNAPSHOT fields (HS code, country of origin, weights,
statistical value, rates) captured at filing time and are never read live from
the CI — an official declaration must not silently change if the CI is edited.
"""

import re

import frappe
from frappe.model.document import Document
from frappe.utils import flt

from stabler.stabler.imports_module.status_pipeline import assert_transition

_ALLOWED_TRANSITIONS = {
	"Draft": {"Submitted"},
	"Submitted": {"Under Review", "Approved", "Rejected"},
	"Under Review": {"Approved", "Rejected"},
	"Approved": set(),
	"Rejected": set(),
}

# XXXXX/DDMMYY/NNNNNNN — 5 digits / 6-digit date / 7-digit serial.
_GTD_NUMBER_RE = re.compile(r"^\d{5}/\d{6}/\d{7}$")


class CustomsDeclaration(Document):
	def validate(self) -> None:
		self._validate_gtd_number()
		self.total_duties = flt(self.duty_amount) + flt(self.vat_amount) + flt(self.excise_amount)
		if self.is_new():
			return
		previous_status = frappe.db.get_value("Customs Declaration", self.name, "status")
		assert_transition("Customs Declaration", previous_status, self.status, _ALLOWED_TRANSITIONS, self)

	def _validate_gtd_number(self) -> None:
		if self.gtd_number and not _GTD_NUMBER_RE.match(self.gtd_number.strip()):
			frappe.throw(
				frappe._("GTD number must be in the format XXXXX/DDMMYY/NNNNNNN (e.g. 26010/110726/1234567).")
			)


def approved_gtd_for_ci(commercial_invoice):
	"""Return (duty_amount, excise_amount) for the CI's cleared GTD, else None.

	A GTD counts only when it is Approved AND has a cleared_date — that is the
	precedence trigger for the Landed Cost Voucher build. Uses the most recently
	cleared declaration when several exist.
	"""
	if not commercial_invoice:
		return None
	rows = frappe.get_all(
		"Customs Declaration",
		filters={
			"commercial_invoice": commercial_invoice,
			"status": "Approved",
			"cleared_date": ["is", "set"],
		},
		fields=["duty_amount", "excise_amount"],
		order_by="cleared_date desc",
		limit=1,
	)
	if not rows:
		return None
	return flt(rows[0].duty_amount), flt(rows[0].excise_amount)
