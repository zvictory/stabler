"""One cash account per desk PER CURRENCY.

A desk that handles USD and UZS holds two drawers, so it needs two accounts. Sharing
one account across currencies is what makes a desk's book balance stop matching the
physical count in the drawer, which is the whole point of reconciliation.

Uniqueness of (branch, currency) is enforced on the parent — Frappe's `unique` flag
is a single-column index and does not apply to child rows. See
`RemittanceSettings.validate`.
"""

from __future__ import annotations

from frappe.model.document import Document


class RemittanceCashDeskAccount(Document):
	pass
