"""Period-end unrealized-FX math for open supplier payables (WP-I11, Frappe-free).

IAS 21: monetary items (an open A/P balance in USD) are retranslated at the
closing rate; the difference is unrealized FX gain/loss. Non-monetary items —
ADVANCES PAID FOR GOODS — are NOT retranslated: the prepayment fixed its rate
on payment day. The Frappe layer therefore feeds only open Purchase Invoice
balances (never unallocated advance Payment Entries) into this module.

Sign convention (payables, company currency = UZS):
  closing rate > booked rate → the UZS value of the debt grew → unrealized LOSS
  (positive ``unrealized_loss``); a negative value is a gain.
"""

from __future__ import annotations


def _amt(v) -> float:
	try:
		return float(v or 0)
	except TypeError, ValueError:
		return 0.0


def reval_row(outstanding_foreign, booked_rate, closing_rate) -> dict:
	"""Unrealized FX for one open payable balance."""
	out = _amt(outstanding_foreign)
	booked = _amt(booked_rate)
	closing = _amt(closing_rate)
	booked_base = round(out * booked, 2)
	closing_base = round(out * closing, 2)
	return {
		"outstanding_foreign": round(out, 2),
		"booked_rate": booked,
		"closing_rate": closing,
		"booked_base": booked_base,
		"closing_base": closing_base,
		# payable: value up = loss (expense), value down = gain
		"unrealized_loss": round(closing_base - booked_base, 2),
	}


def reval_rows(rows, closing_rate) -> list[dict]:
	"""Annotate open-payable rows; extra keys pass through. Largest loss first."""
	out = []
	for r in rows or []:
		row = dict(r or {})
		row.update(reval_row(row.get("outstanding_foreign"), row.get("booked_rate"), closing_rate))
		out.append(row)
	out.sort(key=lambda r: -abs(r["unrealized_loss"]))
	return out


def reval_summary(annotated_rows) -> dict:
	total_loss = sum(r["unrealized_loss"] for r in annotated_rows or [] if r["unrealized_loss"] > 0)
	total_gain = sum(-r["unrealized_loss"] for r in annotated_rows or [] if r["unrealized_loss"] < 0)
	return {
		"unrealized_loss": round(total_loss, 2),
		"unrealized_gain": round(total_gain, 2),
		"net_unrealized_loss": round(total_loss - total_gain, 2),
		"rows": len(annotated_rows or []),
	}
