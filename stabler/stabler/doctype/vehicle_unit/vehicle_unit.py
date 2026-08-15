"""Vehicle Unit — the 1:1 operational/legal facade over an ERPNext Serial No.

Stock truth (warehouse, quantity, status) lives in Serial No / Purchase Receipt
/ Delivery Note and is read live through the link. This doctype never copies it.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

_AGREEMENT_FIELDS = ("acquisition_agreement", "disposition_agreement")


class VehicleUnit(Document):
	def validate(self) -> None:
		self._validate_serial_no()
		self._validate_agreement_links()

	def _validate_serial_no(self) -> None:
		if not frappe.db.exists("Serial No", self.serial_no):
			frappe.throw(_("Serial No {0} does not exist.").format(self.serial_no))
		sn_company = frappe.db.get_value("Serial No", self.serial_no, "company")
		if sn_company and sn_company != self.company:
			frappe.throw(
				_("Serial No {0} belongs to company {1}, not {2}.").format(
					self.serial_no, sn_company, self.company
				)
			)

	def _validate_agreement_links(self) -> None:
		"""Agreement links are written only by activation (Phase 2) via
		`flags.vf_internal` — a hand edit must never redirect a vehicle's
		legal chain."""
		if getattr(self.flags, "vf_internal", False):
			return
		for field in _AGREEMENT_FIELDS:
			if self.get(field) and self.has_value_changed(field):
				frappe.throw(
					_("{0} is set by agreement activation and cannot be edited here.").format(
						self.meta.get_label(field)
					)
				)
