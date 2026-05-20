"""Equipment doctype controller.

Cooler / Freezer / Rack / POSM assets placed at outlets. ``utilization_pct``
is recomputed on every save so the value is idempotent across re-saves.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, nowdate


class Equipment(Document):
	def validate(self) -> None:
		self.utilization_pct = self._compute_utilization_pct()

	def _compute_utilization_pct(self) -> float:
		"""Return a 0..100 utilization percentage for cold-chain equipment.

		Placeholder formula: counts submitted Sales Invoices issued to the
		outlet's customer in the last 30 days and multiplies by 10, clamped at
		100. The real business formula (qty of cooler-required SKUs / shelf
		capacity) is not yet defined and there is no ``Item.is_cooler_required``
		field in the system. Re-running this on the same data yields the same
		result, which keeps the controller idempotent.

		Returns 0.0 when the equipment has no outlet, is not a cooler/freezer,
		or the outlet has no linked customer.
		"""
		if not self.outlet:
			return 0.0
		if self.category not in ("Cooler", "Freezer"):
			return 0.0

		customer = frappe.db.get_value("Outlet", self.outlet, "customer")
		if not customer:
			return 0.0

		thirty_days_ago = add_days(nowdate(), -30)
		count = frappe.db.count(
			"Sales Invoice",
			filters={
				"customer": customer,
				"docstatus": 1,
				"posting_date": [">=", thirty_days_ago],
			},
		)
		return float(min(100, int(count) * 10))
