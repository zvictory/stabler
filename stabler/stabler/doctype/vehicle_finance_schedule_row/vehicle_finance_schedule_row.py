"""Schedule Row — child of Vehicle Finance Schedule Version.

Deliberately carries no `paid_amount` / `outstanding` columns: paid and
outstanding are derived by summing Vehicle Finance Payment Applications, so a
mutable competing ledger (the legacy engine's pattern) cannot exist.
"""

from __future__ import annotations

from frappe.model.document import Document


class VehicleFinanceScheduleRow(Document):
	pass
