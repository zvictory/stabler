"""UZEX etender read-only REST client (public JSON API, no auth).

Mirrors the didox client's shape (HTTPS-guarded urllib, config from
``frappe.conf``, no ``requests`` dependency) but this API needs no signature and
no token — it only READS public lot data. See
docs/plans/uzex-api-discovery-2026-07-08.md.

Endpoints:
  POST {base}/common/TradeList          body {TypeId, From, To, System_Id}
  GET  {base}/common/GetTrade/{id}/0

Config (site_config.json):
  uzex_endpoint     base URL, default https://apietender.uzex.uz/api (HTTPS only)
  uzex_user_agent   optional UA override (portal may filter default agents)
  uzex_token        optional bearer (only if an official API is granted later)
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import frappe

from stabler.integrations.uzex._parse import (  # re-export for callers
	matches_keywords,
	parse_trade_row,
	status_from_detail,
)

# etender lot types (docs §2.1): 1 best-offer, 2 tender, 3 haddi, 5 master-plan,
# 6 document discussion. Overridable via frappe.conf.uzex_type_ids.
UZEX_TYPE_IDS: tuple[int, ...] = (1, 2, 3, 5, 6)

_DEFAULT_ENDPOINT = "https://apietender.uzex.uz/api"
_DEFAULT_UA = "Mozilla/5.0 (compatible; StablerBot/1.0; +https://erpstable.com)"
_TIMEOUT = 30


def _endpoint() -> str:
	ep = getattr(frappe.conf, "uzex_endpoint", None) or _DEFAULT_ENDPOINT
	if not str(ep).lower().startswith("https://"):
		# Never talk to the portal over plaintext.
		frappe.throw("UZEX endpoint must use HTTPS.")
	return str(ep).rstrip("/")


def _headers() -> dict[str, str]:
	# A browser-like UA + Referer dodges the portal's anonymous-agent filter
	# (bare swagger fetches came back empty — see discovery report).
	headers = {
		"Accept": "application/json",
		"Content-Type": "application/json",
		"User-Agent": getattr(frappe.conf, "uzex_user_agent", None) or _DEFAULT_UA,
		"Referer": "https://etender.uzex.uz/",
	}
	token = getattr(frappe.conf, "uzex_token", None)
	if token:
		headers["Authorization"] = f"Bearer {token}"
	return headers


def _read(req: Request) -> Any:
	try:
		with urlopen(req, timeout=_TIMEOUT) as resp:
			text = resp.read().decode("utf-8")
	except HTTPError as e:
		raise frappe.ValidationError(f"UZEX HTTP {e.code}: {e.reason}") from e
	except URLError as e:
		raise frappe.ValidationError(f"UZEX unreachable: {e.reason}") from e
	try:
		return json.loads(text)
	except json.JSONDecodeError as e:
		raise frappe.ValidationError(f"UZEX returned non-JSON: {text[:200]}") from e


def list_trades(type_id: int, frm: int = 1, to: int = 50, system_id: int = 0) -> list[dict]:
	"""POST TradeList for one lot type; returns the raw item list (may be empty)."""
	body = json.dumps(
		{"TypeId": int(type_id), "From": int(frm), "To": int(to), "System_Id": int(system_id)}
	).encode("utf-8")
	req = Request(f"{_endpoint()}/common/TradeList", data=body, headers=_headers(), method="POST")
	data = _read(req)
	return data if isinstance(data, list) else []


def get_trade(lot_id) -> dict:
	"""GET the full detail of one lot (carries status_id/status_name)."""
	req = Request(f"{_endpoint()}/common/GetTrade/{int(lot_id)}/0", headers=_headers(), method="GET")
	data = _read(req)
	return data if isinstance(data, dict) else {}
