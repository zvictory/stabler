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
from decimal import ROUND_HALF_UP, Decimal
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


def _upsert_pair(from_currency: str, to_currency: str, rate: float, on_date: datetime.date) -> bool:
	"""Insert one directional Currency Exchange row if missing. Idempotent."""
	if frappe.db.get_value(
		"Currency Exchange",
		{"from_currency": from_currency, "to_currency": to_currency, "date": on_date},
		"name",
	):
		return False
	frappe.get_doc(
		{
			"doctype": "Currency Exchange",
			"date": on_date,
			"from_currency": from_currency,
			"to_currency": to_currency,
			"exchange_rate": rate,
			"for_buying": 1,
			"for_selling": 1,
		}
	).insert(ignore_permissions=True)
	return True


def _upsert_rate(from_currency: str, rate: float, on_date: datetime.date) -> bool:
	"""Store BOTH directions for the day so a UZS-base *or* USD-base company (or
	any cross-check) always finds a rate:
	  foreign -> UZS = rate       (1 USD = 12 935 UZS)
	  UZS -> foreign = 1 / rate   (1 UZS = 0.0000773 USD)
	Returns True if the primary (foreign->UZS) row was inserted."""
	primary = _upsert_pair(from_currency, _BASE_CURRENCY, rate, on_date)
	if rate:
		# Reciprocal computed in Decimal (not float) so weak-currency inverses
		# (1 UZS -> 0.0000773 USD) keep full significance before the 10-dp
		# quantize; float 1.0/rate drops sub-unit precision on large divisors.
		inverse = (Decimal(1) / Decimal(str(rate))).quantize(Decimal("1E-10"), rounding=ROUND_HALF_UP)
		_upsert_pair(_BASE_CURRENCY, from_currency, float(inverse), on_date)
	return primary


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


def _fetch_cbu_for(on_date: datetime.date) -> dict[str, float]:
	"""Fetch the CBU archive for a specific date → {code: rate}. Empty dict if
	CBU has no publication for that day (weekend/holiday)."""
	url = f"https://cbu.uz/uz/arkhiv-kursov-valyut/json/{on_date.isoformat()}/"
	try:
		req = Request(url, headers={"User-Agent": "stabler/1.0"})
		with urlopen(req, timeout=_TIMEOUT) as resp:
			data = json.loads(resp.read().decode("utf-8"))
	except Exception:  # treat as a non-publishing day; carry forward
		return {}
	out: dict[str, float] = {}
	for row in data if isinstance(data, list) else []:
		code = row.get("Ccy")
		try:
			if code in _TRACKED:
				out[code] = float(row.get("Rate"))
		except (TypeError, ValueError):
			continue
	return out


def backfill(start_date: str, end_date: str | None = None) -> dict[str, Any]:
	"""Backfill Currency Exchange rows (both directions) for every calendar day
	in [start_date, end_date]. Non-publishing days carry forward the last known
	rate, so the +/-3-day staleness check in validate_exchange_rate never trips.

	Run once to seed the year:
	    bench --site anjan.erpstable.com execute \\
	      stabler.tasks.cbu_rate_refresh.backfill --kwargs "{'start_date':'2026-01-01'}"
	"""
	if not frappe.db.exists("DocType", "Currency Exchange"):
		return {"status": "skipped", "reason": "Currency Exchange doctype missing"}

	start = datetime.date.fromisoformat(start_date)
	end = datetime.date.fromisoformat(end_date) if end_date else datetime.date.today()
	last: dict[str, float] = {}
	days = 0
	inserted = 0

	cur = start
	while cur <= end:
		todays = _fetch_cbu_for(cur)
		for code in _TRACKED:
			if code in todays:
				last[code] = todays[code]
			rate = last.get(code)
			if rate:
				_ensure_currency_exists(code)
				if _upsert_rate(code, rate, cur):
					inserted += 1
		days += 1
		if days % 20 == 0:
			frappe.db.commit()
		cur += datetime.timedelta(days=1)

	frappe.db.commit()
	summary = {
		"status": "ok",
		"from": start.isoformat(),
		"to": end.isoformat(),
		"days": days,
		"rows_inserted": inserted,
		"tracked": list(_TRACKED),
	}
	print(f"[stabler.tasks.cbu_rate_refresh.backfill] {summary}")
	return summary


def fill_gap(start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
	"""Close gaps in Currency Exchange WITHOUT calling cbu.uz — carry the most
	recent stored rate forward over every missing day.

	Use this when the daily fetch had a gap and the cbu.uz archive isn't reachable
	for the needed dates (e.g. a system clock that runs ahead of real-world dates).
	For each tracked currency it takes the latest stored foreign->UZS rate and
	writes both directions for each missing day up to `end_date` (default today).
	A real row already present for a day is respected and its rate is carried on.

	    bench --site anjan.erpstable.com execute \\
	      stabler.tasks.cbu_rate_refresh.fill_gap --kwargs "{'start_date':'2026-02-12'}"
	"""
	if not frappe.db.exists("DocType", "Currency Exchange"):
		return {"status": "skipped", "reason": "Currency Exchange doctype missing"}

	end = datetime.date.fromisoformat(end_date) if end_date else datetime.date.today()
	out: dict[str, Any] = {}
	for code in _TRACKED:
		latest = frappe.db.get_value(
			"Currency Exchange",
			{"from_currency": code, "to_currency": _BASE_CURRENCY},
			["exchange_rate", "date"],
			order_by="date desc",
			as_dict=True,
		)
		if not latest or not latest.get("exchange_rate"):
			out[code] = "no stored base rate to carry"
			continue
		last_date = latest["date"]
		if not isinstance(last_date, datetime.date):
			last_date = datetime.date.fromisoformat(str(last_date)[:10])
		start = (
			datetime.date.fromisoformat(start_date)
			if start_date
			else (last_date + datetime.timedelta(days=1))
		)
		rate = float(latest["exchange_rate"])
		filled = 0
		cur = start
		while cur <= end:
			existing = frappe.db.get_value(
				"Currency Exchange",
				{"from_currency": code, "to_currency": _BASE_CURRENCY, "date": cur},
				"exchange_rate",
			)
			if existing:
				rate = float(existing)  # adopt a real row and carry it forward
			else:
				_ensure_currency_exists(code)
				_upsert_rate(code, rate, cur)
				filled += 1
			cur += datetime.timedelta(days=1)
		out[code] = {"filled_days": filled, "rate": rate, "from": start.isoformat()}
	frappe.db.commit()
	summary = {"status": "ok", "to": end.isoformat(), "currencies": out}
	print(f"[stabler.tasks.cbu_rate_refresh.fill_gap] {summary}")
	return summary
