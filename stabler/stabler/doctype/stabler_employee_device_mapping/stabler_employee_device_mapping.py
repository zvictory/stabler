# Copyright (c) 2026, Stabler and contributors
from __future__ import annotations

from frappe.model.document import Document


class StablerEmployeeDeviceMapping(Document):
	"""Effective-dated link from a device/Timepay user id to an ERPNext Employee.
	Seeded from the one-time reconciliation; the ingestion hot path matches only
	through this table (never by name)."""

	pass
