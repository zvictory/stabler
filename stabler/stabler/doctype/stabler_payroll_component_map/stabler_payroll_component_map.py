# Copyright (c) 2026, Stabler and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class StablerPayrollComponentMap(Document):
	"""Per-company mapping from Stabler payroll quantities to ERPNext Salary Components.

	Validation note: a quantity that produces a non-zero amount but whose
	component field is left blank will be silently skipped at generation time
	(enforced by the payroll generation API, not here). This keeps the map
	record itself permissive so partial maps can be saved as drafts.
	"""

	def validate(self):
		"""Ensure enabled maps have at least a company set."""
		if self.enabled and not self.company:
			frappe.throw(frappe._("Company is required for an enabled Payroll Component Map."))
