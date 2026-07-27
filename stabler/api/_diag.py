"""Lightweight transaction diagnostics for Stabler.

Goal: when ANY form/transaction misbehaves (especially multi-currency GL cases
like "UZS typed, USD base off by a cent"), there is a structured log of the
document's exact state to investigate — without enabling heavy Frappe debug.

`on_txn_validate` is registered in hooks.py as a `before_validate` doc-event for
the financial doctypes, so every save AND submit of those docs writes a snapshot
of its money fields (transaction-currency amounts next to the company-currency
base + the difference) to `logs/stabler.diag.log` right before validation runs.
So whatever validation/submit then rejects, the failing state is already logged.

Tail it:  tail -f sites/<site>/logs/stabler.diag.log
Never raises — diagnostics must not break a save.
"""

from __future__ import annotations

import json

import frappe

# Money / GL fields worth capturing when present on a doc. We only log the ones
# the doctype actually has, so one snapshot fn works for every transaction.
_FIELDS = (
	"company",
	"posting_date",
	"currency",
	"conversion_rate",
	"multi_currency",
	"grand_total",
	"base_grand_total",
	"rounded_total",
	"base_rounded_total",
	"rounding_adjustment",
	"base_rounding_adjustment",
	"outstanding_amount",
	"paid_amount",
	"received_amount",
	"base_paid_amount",
	"base_received_amount",
	"source_exchange_rate",
	"target_exchange_rate",
	"total_allocated_amount",
	"base_total_allocated_amount",
	"unallocated_amount",
	"difference_amount",
	"total_debit",
	"total_credit",
	"total_amount",
	"update_stock",
	"party_type",
	"party",
	"paid_from",
	"paid_to",
	"paid_from_account_currency",
	"paid_to_account_currency",
)


def diag_log(channel: str, stage: str, data: dict) -> None:
	"""Write one structured diagnostic line. Never raises."""
	try:
		payload = {"channel": channel, "stage": stage, "user": frappe.session.user}
		payload.update(data)
		frappe.logger("stabler.diag", allow_site=True, file_count=10).info(json.dumps(payload, default=str))
	except Exception:
		pass


def snapshot_doc(doc) -> dict:
	"""Compact money/GL snapshot of any document — only fields it actually has."""
	out = {
		"doctype": getattr(doc, "doctype", None),
		"name": getattr(doc, "name", None),
		"docstatus": getattr(doc, "docstatus", 0),
	}
	for f in _FIELDS:
		if hasattr(doc, f):
			v = doc.get(f)
			if v not in (None, ""):
				out[f] = v
	# Child amount rows that carry currency dimensions (JE accounts, PE deductions/refs).
	rows = []
	for table in ("accounts", "deductions", "references"):
		for r in doc.get(table) or []:
			rows.append(
				{
					"_t": table,
					"account": r.get("account") if hasattr(r, "get") else None,
					"debit": r.get("debit") if hasattr(r, "get") else None,
					"credit": r.get("credit") if hasattr(r, "get") else None,
					"amount": r.get("amount") if hasattr(r, "get") else None,
					"allocated_amount": r.get("allocated_amount") if hasattr(r, "get") else None,
					"user_remark": r.get("user_remark") if hasattr(r, "get") else None,
				}
			)
	if rows:
		out["rows"] = rows
	return out


def on_txn_validate(doc, method=None) -> None:
	"""before_validate doc-event: snapshot the doc's money state on every save."""
	try:
		diag_log("txn", method or "validate", snapshot_doc(doc))
	except Exception:
		pass
