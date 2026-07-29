from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class CRMActivity(Document):
	_ALLOWED_REFERENCE_DOCTYPES = {"CRM Deal", "CRM Lead"}

	def before_insert(self):
		self.created_by = frappe.session.user
		self.status = "Planned"

	def validate(self):
		if self.reference_doctype not in self._ALLOWED_REFERENCE_DOCTYPES or not self.reference_name:
			frappe.throw(_("A valid CRM reference is required."))
		if not frappe.db.exists(self.reference_doctype, self.reference_name):
			frappe.throw(_("The referenced CRM record does not exist."))
		if not frappe.has_permission(self.reference_doctype, "read", self.reference_name):
			frappe.throw(_("Not permitted"), frappe.PermissionError)
		reference_company = frappe.db.get_value(
			self.reference_doctype,
			self.reference_name,
			"company",
		)
		if reference_company != self.company:
			frappe.throw(_("The activity company must match the referenced CRM record company."))

	def before_save(self):
		if not self.is_new() and not getattr(frappe.flags, "crm_activity_completion", False):
			frappe.throw(_("CRM Activity records may only be completed through the CRM API."))

	def on_trash(self):
		frappe.throw(_("CRM Activity records are immutable."))
