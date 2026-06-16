from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from stabler.integrations.timepay.client import decode_jwt_exp


class StablerTimepayCredential(Document):
	def _password_value(self, fieldname: str) -> str | None:
		current = self.get(fieldname)
		if current and not str(current).startswith("*"):
			return current
		return self.get_password(fieldname)

	def validate(self):
		access = self._password_value("access_token")
		refresh = self._password_value("refresh_token")
		if access:
			self.access_expires_at = decode_jwt_exp(access)
		if refresh:
			self.refresh_expires_at = decode_jwt_exp(refresh)
		if access and refresh and self.access_expires_at >= self.refresh_expires_at:
			frappe.throw(_("Timepay refresh token must expire after the access token."))
