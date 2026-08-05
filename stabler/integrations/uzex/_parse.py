"""Pure parsing/normalisation helpers for the UZEX etender API (Frappe-free).

Kept import-free of Frappe so the mapping, date parsing and keyword filtering can
be unit-tested under plain ``python -m unittest`` — the network + persistence
live in ``client.py`` / ``tasks/uzex_poll.py``.

API shapes (see docs/plans/uzex-api-discovery-2026-07-08.md):
  TradeList item: {id, display_no, name, start_date, end_date, cost,
                   seller_name, seller_tin, currency_codeabc, ...}
  GetTrade:       {id, display_no, status_id, status_name, start_cost,
                   end_date, customer_name, ...}
"""

from __future__ import annotations

import re
from typing import Any

# etender lot URLs look like https://etender.uzex.uz/lot/500606 ; the API detail
# call is GetTrade/500606/0. Accept a full URL, a /lot/<id> path, or a bare id.
_LOT_URL_RE = re.compile(r"/lot/(\d+)")
_GETTRADE_RE = re.compile(r"/GetTrade/(\d+)")


def lot_id_from_url(value: str | int | None) -> int | None:
	"""Extract the numeric UZEX lot id from a pasted URL or a bare id. None if absent."""
	if value is None:
		return None
	s = str(value).strip()
	if not s:
		return None
	if s.isdigit():
		return int(s)
	for rx in (_LOT_URL_RE, _GETTRADE_RE):
		m = rx.search(s)
		if m:
			return int(m.group(1))
	# last resort: a trailing run of digits (e.g. ".../lot/500606?x=1")
	m = re.search(r"(\d{4,})", s)
	return int(m.group(1)) if m else None


def to_float(value) -> float | None:
	"""Coerce a portal numeric (int/str) to float; None on garbage."""
	if value is None or value == "":
		return None
	try:
		return float(value)
	except TypeError, ValueError:
		return None


def parse_uzex_dt(value) -> str | None:
	"""Normalise a UZEX datetime to a Frappe-storable ``YYYY-MM-DD HH:MM:SS``.

	UZEX returns tz-naive ISO like ``2026-07-08T11:47:09`` (Asia/Tashkent wall
	time). We keep it naive — the site runs on Asia/Tashkent — and only swap the
	``T`` separator. A bare date (no time) is padded to midnight. Garbage → None.
	"""
	if not value or not isinstance(value, str):
		return None
	v = value.strip().replace("T", " ")
	if not v:
		return None
	# Drop fractional seconds / trailing zone if present.
	v = v.split(".")[0].split("+")[0].strip()
	if len(v) == 10:  # date only
		v += " 00:00:00"
	return v


def parse_trade_row(row: dict) -> dict:
	"""Normalise one TradeList item to the fields WP-301 stores on CRM Deal.

	Returns a dict with ``lot_id`` (int for the detail call) and the
	``custom_uzex_*`` values. ``lot_no`` is the dedupe key (display_no).
	"""
	if not isinstance(row, dict):
		row = {}
	lot_id = row.get("id")
	return {
		"lot_id": int(lot_id) if isinstance(lot_id, (int, float, str)) and str(lot_id).isdigit() else lot_id,
		"lot_no": str(row.get("display_no") or "").strip(),
		"name": (row.get("name") or "").strip() or None,
		"deadline": parse_uzex_dt(row.get("end_date")),
		"start_price": to_float(row.get("cost")),
		"customer_org": (row.get("seller_name") or "").strip() or None,
		"currency": (row.get("currency_codeabc") or "").strip() or None,
	}


def matches_keywords(name: str | None, keywords) -> bool:
	"""True when ``name`` contains any configured keyword (case-insensitive).

	Empty/misconfigured ``keywords`` → False: an unfiltered site must NOT ingest
	every lot as a Deal (flood guard). Existing tracked Deals are updated
	regardless — this gate only decides whether a *new* lot becomes a Deal.
	"""
	if not keywords or not name:
		return False
	if isinstance(keywords, str):
		keywords = [keywords]
	n = name.lower()
	return any(k and str(k).lower() in n for k in keywords)


def status_from_detail(detail: dict) -> str | None:
	"""Raw portal status string from a GetTrade payload (mapped later, WP-303)."""
	if not isinstance(detail, dict):
		return None
	name = detail.get("status_name")
	sid = detail.get("status_id")
	if name:
		return str(name).strip()
	return str(sid) if sid is not None else None
