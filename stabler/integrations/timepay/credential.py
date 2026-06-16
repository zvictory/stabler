from __future__ import annotations

from typing import Any

import frappe

from stabler.integrations.timepay.client import API_BASE, ORIGIN, decode_jwt_exp

DOCTYPE = "Stabler Timepay Credential"


class FrappeTimepayTokenStore:
	def get_tokens(self) -> dict[str, Any] | None:
		if not frappe.db.exists("DocType", DOCTYPE):
			return None
		doc = frappe.get_single(DOCTYPE)
		access = doc.get_password("access_token")
		refresh = doc.get_password("refresh_token")
		if not access or not refresh:
			return None
		return {
			"access": access,
			"refresh": refresh,
			"access_expires_at": int(doc.access_expires_at or decode_jwt_exp(access)),
			"refresh_expires_at": int(doc.refresh_expires_at or decode_jwt_exp(refresh)),
		}

	def save_refreshed(self, next_tokens: dict[str, Any]) -> None:
		doc = frappe.get_single(DOCTYPE)
		if next_tokens.get("access"):
			doc.access_token = next_tokens["access"]
			doc.access_expires_at = int(next_tokens["access_expires_at"])
		if next_tokens.get("refresh"):
			doc.refresh_token = next_tokens["refresh"]
			doc.refresh_expires_at = int(next_tokens["refresh_expires_at"])
		doc.save(ignore_permissions=True)
		frappe.db.commit()


def get_client_config() -> dict[str, str]:
	if not frappe.db.exists("DocType", DOCTYPE):
		return {"api_base": API_BASE, "origin": ORIGIN}
	doc = frappe.get_single(DOCTYPE)
	return {
		"api_base": (doc.api_base or API_BASE).rstrip("/"),
		"origin": doc.origin or ORIGIN,
	}
