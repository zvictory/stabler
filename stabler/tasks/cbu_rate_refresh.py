"""Daily Central Bank of Uzbekistan (cbu.uz) exchange rate refresh.

Fetches USD / EUR / RUB → UZS from the CBU public JSON API and upserts
an ERPNext `Currency Exchange` row for today's date. Idempotent: rerun
on the same day is a no-op (existing rows for today are skipped).

CBU returns 1 unit foreign → N UZS, which matches Frappe's
"For Selling" / "For Buying" exchange-rate convention (from_currency,
to_currency, exchange_rate). We set both buying and selling to the same
mid-rate; if the business later needs a spread, add it to the document.

Run on-demand via:
    bench --site stabler execute stabler.tasks.cbu_rate_refresh.fetch_and_store

Registered in hooks.py under scheduler_events.daily.
"""

from __future__ import annotations

import datetime
import json
from typing import Any
from urllib.request import Request, urlopen

import frappe

_CBU_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
_BASE_CURRENCY = "UZS"
_TRACKED = ("USD", "EUR", "RUB")
_TIMEOUT = 15


def _fetch_cbu_payload() -> list[dict[str, Any]]:
	req = Request(_CBU_URL, headers={"User-Agent": "stabler/1.0"})
	with urlopen(req, timeout=_TIMEOUT) as resp:
		raw = resp.read().decode("utf-8")
	data = json.loads(raw)
	if not isinstance(data, list):
		raise ValueError(f"cbu.uz returned non-list payload: {type(data).__name__}")
	return data


def _ensure_currency_exists(code: str) -> None:
	if not frappe.db.exists("Currency", code):
		frappe.get_doc({"doctype": "Currency", "currency_name": code, "enabled": 1}).insert(
			ignore_permissions=True
		)


def _upsert_rate(from_currency: str, rate: float, on_date: datetime.date) -> bool:
	"""Insert today's Currency Exchange row if missing. Returns True if inserted."""
	existing = frappe.db.get_value(
		"Currency Exchange",
		{
			"from_currency": from_currency,
			"to_currency": _BASE_CURRENCY,
			"date": on_date,
		},
		"name",
	)
	if existing:
		return False

	frappe.get_doc(
		{
			"doctype": "Currency Exchange",
			"date": on_date,
			"from_currency": from_currency,
			"to_currency": _BASE_CURRENCY,
			"exchange_rate": rate,
			"for_buying": 1,
			"for_selling": 1,
		}
	).insert(ignore_permissions=True)
	return True


def fetch_and_store() -> dict[str, Any]:
	"""Daily entry point. Returns a summary dict for logs."""
	if not frappe.db.exists("DocType", "Currency Exchange"):
		# ERPNext not installed yet — defer gracefully.
		return {"status": "skipped", "reason": "Currency Exchange doctype missing"}

	today = datetime.date.today()
	payload = _fetch_cbu_payload()
	by_code = {row.get("Ccy"): row for row in payload if isinstance(row, dict) and row.get("Ccy")}

	inserted: dict[str, float] = {}
	skipped: list[str] = []
	missing: list[str] = []

	for code in _TRACKED:
		row = by_code.get(code)
		if not row:
			missing.append(code)
			continue
		try:
			rate = float(row.get("Rate"))
		except (TypeError, ValueError):
			missing.append(code)
			continue

		_ensure_currency_exists(code)
		if _upsert_rate(code, rate, today):
			inserted[code] = rate
		else:
			skipped.append(code)

	frappe.db.commit()
	summary = {
		"status": "ok",
		"date": today.isoformat(),
		"inserted": inserted,
		"skipped": skipped,
		"missing": missing,
	}
	print(f"[stabler.tasks.cbu_rate_refresh] {summary}")
	return summary
