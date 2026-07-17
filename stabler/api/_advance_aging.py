"""Supplier advance aging / repatriation-deadline math (WP-I10, Frappe-free).

Uzbek currency-control (valyuta nazorati): an import advance paid abroad must be
"closed" by goods arriving (or the money returning) within the contract term —
commonly 180 days. An advance Payment Entry that is still unallocated (no
Purchase Invoice absorbed it) as its age approaches that horizon is a legal
risk, not just a working-capital one.

Buckets:
  OK      age < warn_days   (default 150)
  WARN    warn_days <= age < breach_days
  BREACH  age >= breach_days (default 180)

The Frappe layer feeds submitted supplier Payment Entries with an unallocated
balance; this module only computes ages, buckets and totals.
"""

from __future__ import annotations

from datetime import date, datetime

WARN_DAYS = 150
BREACH_DAYS = 180


def _as_date(v) -> date:
	if isinstance(v, datetime):
		return v.date()
	if isinstance(v, date):
		return v
	return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def age_days(posting_date, today) -> int:
	"""Whole days elapsed since the advance left the company (never negative)."""
	return max((_as_date(today) - _as_date(posting_date)).days, 0)


def classify(age: int, warn_days: int = WARN_DAYS, breach_days: int = BREACH_DAYS) -> str:
	if age >= breach_days:
		return "BREACH"
	if age >= warn_days:
		return "WARN"
	return "OK"


def _amt(v) -> float:
	try:
		return float(v or 0)
	except (TypeError, ValueError):
		return 0.0


def aging_rows(rows, today, warn_days: int = WARN_DAYS, breach_days: int = BREACH_DAYS) -> list[dict]:
	"""Annotate advance rows with age + bucket, oldest (most at risk) first.

	``rows`` = iterable of {name, party, supplier_name, posting_date,
	unallocated_amount, ...} — extra keys pass through untouched.
	"""
	out = []
	for r in rows or []:
		row = dict(r or {})
		age = age_days(row.get("posting_date"), today)
		row["age_days"] = age
		row["bucket"] = classify(age, warn_days, breach_days)
		row["days_to_breach"] = max(breach_days - age, 0)
		out.append(row)
	out.sort(key=lambda r: -r["age_days"])
	return out


def aging_summary(annotated_rows) -> dict:
	"""Totals for the dashboard header: counts + money at risk per bucket."""
	total = warn_amt = breach_amt = 0.0
	warn_n = breach_n = 0
	for r in annotated_rows or []:
		amt = _amt((r or {}).get("unallocated_amount"))
		total += amt
		b = (r or {}).get("bucket")
		if b == "WARN":
			warn_n += 1
			warn_amt += amt
		elif b == "BREACH":
			breach_n += 1
			breach_amt += amt
	return {
		"total_unallocated": round(total, 2),
		"warn_count": warn_n,
		"warn_amount": round(warn_amt, 2),
		"breach_count": breach_n,
		"breach_amount": round(breach_amt, 2),
		"at_risk_amount": round(warn_amt + breach_amt, 2),
	}
