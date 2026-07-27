# Copyright (c) 2026, Stabler and contributors
from __future__ import annotations

from frappe.model.document import Document


class StablerAttendanceProcessingLog(Document):
	"""Append-only record of how a raw event was processed (audit + replay)."""

	pass
