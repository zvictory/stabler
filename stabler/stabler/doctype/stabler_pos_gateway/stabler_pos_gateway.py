"""Stabler POS Gateway — maps a POS Mode of Payment to an Uzbek payment
provider (Payme / Click / Uzum Bank) per company. Child table of Stabler
Settings."""

from __future__ import annotations

from frappe.model.document import Document


class StablerPOSGateway(Document):
	pass
