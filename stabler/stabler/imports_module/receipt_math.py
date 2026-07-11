"""Pure, frappe-free helpers for the PR-per-TruckReceipt build (critique M7).

Each submitted Truck Receipt becomes one *partial* ERPNext Purchase Receipt
against the linked Purchase Order(s), so perishable meat enters stock truck by
truck without waiting for the whole GRN to close. The frappe-facing wiring lives
in ``imports_module/hooks.py``; every decision and payload shape lives here so it
can be unit-tested without a bench.

Key rules encoded here:

* **Good-only qty.** Only ``condition == "Good"`` weight enters the Purchase
  Receipt (``good_qty``). Damaged/rejected boxes stay recorded on the Truck
  Receipt for the claim trail (the GRN Checklist still counts them as physically
  received — see ``grn_math``).
* **PO-rate resolution.** ``resolve_po_rate`` matches an item across the POs
  linked to the Commercial Invoice. Exactly one line -> use its rate + linkage;
  none, or several with differing rates -> rate 0 and a warning; several with an
  identical rate -> that rate but no (ambiguous) row linkage.
* **Batch naming.** ``{container_number or CI}-{item_code}-{arrival_date}``.
* **Currency.** Rate/qty are USD/Kg; the PR is tagged ``currency = "USD"`` and
  the USD->company conversion_rate is deliberately left to ERPNext's own
  Currency Exchange defaults (documented assumption — stock items are held in
  Kg, so uom == stock_uom == "Kg", conversion_factor 1).
"""

from __future__ import annotations

STOCK_UOM = "Kg"


def good_qty(received_kg, condition) -> float:
	"""Weight that enters the Purchase Receipt: Good condition only, else 0."""
	if str(condition or "").strip().lower() != "good":
		return 0.0
	return round(float(received_kg or 0), 3)


def temperature_ok(temp, target_min, target_max) -> bool:
	"""True when ``temp`` is within [min, max]. No reading / no range -> True."""
	if temp in (None, ""):
		return True
	if target_min in (None, "") or target_max in (None, ""):
		return True
	return float(target_min) <= float(temp) <= float(target_max)


def batch_name(container_number, commercial_invoice, item_code, arrival_date) -> str:
	"""Deterministic ERPNext Batch id for a received line."""
	prefix = container_number or commercial_invoice or "IMP"
	return f"{prefix}-{item_code}-{arrival_date}"


def resolve_po_rate(item_code, po_item_rows) -> dict:
	"""Resolve the PO rate + row linkage for ``item_code``.

	``po_item_rows`` is a list of
	``{"purchase_order", "purchase_order_item", "item_code", "rate"}``.
	Returns ``{"rate", "purchase_order", "purchase_order_item", "warning"}``.
	"""
	matches = [r for r in po_item_rows if r.get("item_code") == item_code]
	if not matches:
		return {
			"rate": 0.0,
			"purchase_order": None,
			"purchase_order_item": None,
			"warning": f"No linked Purchase Order line for item {item_code}; rate set to 0.",
		}
	if len(matches) == 1:
		m = matches[0]
		return {
			"rate": round(float(m.get("rate") or 0), 4),
			"purchase_order": m.get("purchase_order"),
			"purchase_order_item": m.get("purchase_order_item"),
			"warning": None,
		}
	rates = {round(float(r.get("rate") or 0), 4) for r in matches}
	if len(rates) == 1:
		return {
			"rate": next(iter(rates)),
			"purchase_order": None,
			"purchase_order_item": None,
			"warning": (
				f"Item {item_code} is on several Purchase Order lines with the same rate; "
				"rate applied but row linkage omitted (ambiguous)."
			),
		}
	return {
		"rate": 0.0,
		"purchase_order": None,
		"purchase_order_item": None,
		"warning": (
			f"Item {item_code} is on several Purchase Order lines with differing rates; "
			"rate set to 0 — verify manually."
		),
	}


def build_pr_line(*, item_code, qty, rate, warehouse, purchase_order, purchase_order_item, batch_no) -> dict:
	"""One Purchase Receipt Item dict (Kg stock uom, optional PO/batch linkage)."""
	line = {
		"item_code": item_code,
		"qty": round(float(qty or 0), 3),
		"uom": STOCK_UOM,
		"stock_uom": STOCK_UOM,
		"conversion_factor": 1,
		"rate": round(float(rate or 0), 4),
		"warehouse": warehouse,
	}
	if purchase_order:
		line["purchase_order"] = purchase_order
	if purchase_order_item:
		line["purchase_order_item"] = purchase_order_item
	if batch_no:
		line["use_serial_batch_fields"] = 1
		line["batch_no"] = batch_no
	return line


def build_pr_payload(*, company, supplier, posting_date, currency, warehouse, lines, truck_receipt_name):
	"""Assemble the (submittable) Purchase Receipt dict from resolved lines.

	``lines`` is a list of ``build_pr_line`` dicts. Only lines with qty > 0 are
	kept (Good-condition weight). Returns ``None`` when nothing is receivable so
	the caller can skip. ``docstatus`` is never set here — the caller submits it.
	"""
	items = [ln for ln in lines if float(ln.get("qty") or 0) > 0]
	if not items:
		return None
	return {
		"doctype": "Purchase Receipt",
		"company": company,
		"supplier": supplier,
		"posting_date": posting_date,
		"set_posting_time": 1,
		"currency": currency,
		"remarks": f"Auto Purchase Receipt for Truck Receipt {truck_receipt_name}",
		"items": items,
	}
