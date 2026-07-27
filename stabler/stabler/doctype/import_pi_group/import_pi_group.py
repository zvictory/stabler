import frappe
from frappe import _
from frappe.model.document import Document


class ImportPIGroup(Document):
	def validate(self):
		self._validate_code_unique()

	def _validate_code_unique(self):
		"""``code`` is optional but must be unique per company when set (MSA
		CONTRACT-2025-04-style short reference)."""
		code = (self.code or "").strip()
		if not code:
			self.code = None
			return
		self.code = code
		dup = frappe.db.exists(
			"Import PI Group",
			{
				"code": code,
				"company": self.company,
				"name": ("!=", self.name or ""),
			},
		)
		if dup:
			frappe.throw(_("PI Group code {0} is already used in this company.").format(code))
