"""The tender intake's item lines — pure, Frappe-free.

The lines live inside the ``custom_tender_intake`` JSON overlay, and the RFQ
step copies them line by line. That makes them load-bearing for the whole
tender → RFQ → quotation chain, so their sanitizer gets its own module the
way ``_bid_pnl`` and ``_landed`` did: importable without Frappe, testable
without doubles, and impossible to entangle with a 3450-line API module.

Three rules live here, and each is a regression that already happened once:

  * ``sanitize_intake_items`` recomputes ``amount`` as qty x rate. A
    client-stale amount is a fact that was never true, and the pipeline
    totals read it as one.
  * ``clean_intake_items`` preserves the prior lines when the payload
    carries no ``items`` key. The PO-control intake editor saves the
    deadline/checklist fields without lines; treating an absent key as "no
    items" wiped the tender scope there on every save.
  * ``read_intake_items`` normalizes the stored JSON on the way OUT, so an
    RFQ raised months later sees the same lines the drawer captured.
"""

from __future__ import annotations

import json

#: Hard ceiling on one lot's line count. A tender spec with more lines than
#: this is data damage, not a tender; and the JSON overlay is read on every
#: board render, so it may not grow without bound.
INTAKE_ITEM_LIMIT = 200


def _num(v, default: float = 0.0) -> float:
	try:
		return float(v)
	except (TypeError, ValueError):
		return default


def sanitize_intake_items(raw, limit: int = INTAKE_ITEM_LIMIT) -> list[dict]:
	"""Clean one client-supplied list of intake item lines.

	Lines without an item or with a non-positive quantity are dropped rather
	than repaired: the drawer already filters its own rows, so a line that
	arrives broken was never shown to the user as part of the tender.
	"""
	lines: list[dict] = []
	for entry in raw or []:
		if not isinstance(entry, dict):
			continue
		item_code = str(entry.get("item_code") or "").strip()[:140]
		if not item_code:
			continue
		qty = _num(entry.get("qty"))
		if qty <= 0:
			continue
		rate = max(_num(entry.get("rate")), 0.0)
		lines.append(
			{
				"item_code": item_code,
				"item_name": str(entry.get("item_name") or "").strip()[:140],
				"qty": qty,
				"uom": str(entry.get("uom") or "").strip()[:40],
				"rate": rate,
				"amount": round(qty * rate, 2),
			}
		)
	return lines[:limit]


def clean_intake_items(data: dict, prior_items) -> list:
	"""Reconcile the tender's item lines across an intake edit.

	An absent key preserves the prior lines; a present list replaces them.
	The intake drawer owns the lines and sends the full set, while the
	PO-control editor sends only its own fields — one rule covers both.
	"""
	if "items" not in data or data["items"] is None:
		return sanitize_intake_items(prior_items)
	return sanitize_intake_items(data["items"])


def parse_intake(raw) -> dict:
	"""Parse the stored intake JSON; damaged storage reads as empty."""
	if not raw:
		return {}
	try:
		return raw if isinstance(raw, dict) else json.loads(raw)
	except (ValueError, TypeError):
		return {}


def read_intake_items(doc) -> list[dict]:
	"""The tender's item lines, read back from a CRM Deal."""
	return sanitize_intake_items(parse_intake(doc.get("custom_tender_intake")).get("items"))
