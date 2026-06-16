# Copyright (c) 2026, Stabler and contributors
# For license information, please see license.txt

from __future__ import annotations

from frappe.model.document import Document


class StablerBankImport(Document):
	"""Audit record of one bank-statement import (file → Bank Transaction rows)."""

	pass
