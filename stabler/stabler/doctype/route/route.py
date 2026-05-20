import frappe
from frappe import _
from frappe.model.document import Document


class Route(Document):
	def validate(self):
		self._dedupe_outlet_sequences()

	def _dedupe_outlet_sequences(self):
		seen_seq: set[int] = set()
		seen_outlet: set[str] = set()
		for row in self.outlets or []:
			if row.sequence in seen_seq:
				frappe.throw(_("Duplicate sequence {0} on this route.").format(row.sequence))
			if row.outlet in seen_outlet:
				frappe.throw(_("Outlet {0} appears twice on this route.").format(row.outlet))
			seen_seq.add(row.sequence)
			seen_outlet.add(row.outlet)
