"""Pure, frappe-free GRN Checklist variance math.

Ports the progressive-acceptance variance engine from the Django
``GoodsReceiptNote.update_totals`` / ``GRNLineItem.update_totals`` (msaerp
models.py:3826, 4022) so it can be unit-tested without a bench. The GRN
controller (``grn_checklist.py``) is a thin layer that reads/writes document
fields and delegates every calculation here.

Variance thresholds (Django, verbatim):
  * |variance%| <= 2   -> NORMAL   (no claim)
  * |variance%| <= 5   -> MINOR
  * |variance%| <= 10  -> MAJOR
  * |variance%|  > 10  -> CRITICAL
  * claim required whenever |variance%| > 2

The GRN records the *physical* received quantity (all conditions, including
damaged) — it is the receiving checklist / claim trail. Saleable stock (Good
condition only) is what the Purchase Receipt books; see ``receipt_math``.
"""

from __future__ import annotations


def variance_pct(numerator, denominator) -> float:
	"""``numerator / denominator * 100`` guarded for a zero/blank base."""
	d = float(denominator or 0)
	if d <= 0:
		return 0.0
	return round(float(numerator or 0) / d * 100.0, 2)


def variance_category(pct) -> str:
	"""NORMAL / MINOR / MAJOR / CRITICAL from a signed variance percentage."""
	v = abs(float(pct or 0))
	if v <= 2.0:
		return "NORMAL"
	if v <= 5.0:
		return "MINOR"
	if v <= 10.0:
		return "MAJOR"
	return "CRITICAL"


def claim_required(pct) -> bool:
	"""A supplier claim is required whenever the shortfall/overage exceeds 2%."""
	return abs(float(pct or 0)) > 2.0


def line_status(expected_boxes, received_boxes, pct) -> str:
	"""Per-item status Pending / Partial / Complete / Discrepancy.

	Mirrors Django ``GRNLineItem.update_totals``: Complete/Partial/Pending is
	decided on box counts first, then a >5% variance overrides to Discrepancy.
	"""
	eb = float(expected_boxes or 0)
	rb = float(received_boxes or 0)
	if rb >= eb:
		status = "Complete"
	elif rb > 0:
		status = "Partial"
	else:
		status = "Pending"
	if abs(float(pct or 0)) > 5.0:
		status = "Discrepancy"
	return status


def receipt_status(pending_boxes, received_boxes, pct) -> str:
	"""Header progress status Pending / Receiving / Complete / Discrepancy."""
	if float(pending_boxes or 0) == 0 and float(received_boxes or 0) > 0:
		status = "Complete"
	elif float(received_boxes or 0) > 0:
		status = "Receiving"
	else:
		status = "Pending"
	if abs(float(pct or 0)) > 5.0:
		status = "Discrepancy"
	return status


def compute_line(expected_boxes, expected_kg, received_boxes, received_kg) -> dict:
	"""Derived per-item fields for one GRN Checklist Item row."""
	pending_boxes = round(float(expected_boxes or 0) - float(received_boxes or 0))
	pending_kg = round(float(expected_kg or 0) - float(received_kg or 0), 2)
	var_kg = round(float(received_kg or 0) - float(expected_kg or 0), 2)
	pct = variance_pct(var_kg, expected_kg)
	return {
		"pending_boxes": pending_boxes,
		"pending_kg": pending_kg,
		"variance_kg": var_kg,
		"variance_pct": pct,
		"status": line_status(expected_boxes, received_boxes, pct),
	}


def compute_header(expected_boxes, expected_kg, received_boxes, received_kg) -> dict:
	"""Derived header fields for the GRN Checklist."""
	pending_boxes = round(float(expected_boxes or 0) - float(received_boxes or 0))
	pending_kg = round(float(expected_kg or 0) - float(received_kg or 0), 2)
	var_boxes = round(float(received_boxes or 0) - float(expected_boxes or 0))
	var_kg = round(float(received_kg or 0) - float(expected_kg or 0), 2)
	pct = variance_pct(var_kg, expected_kg)
	completion = variance_pct(received_kg, expected_kg)
	return {
		"pending_boxes": pending_boxes,
		"pending_kg": pending_kg,
		"variance_boxes": var_boxes,
		"variance_kg": var_kg,
		"variance_pct": pct,
		"category": variance_category(pct),
		"completion_pct": completion,
		"claim_required": claim_required(pct),
		"receipt_status": receipt_status(pending_boxes, received_boxes, pct),
	}
