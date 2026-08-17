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
* **No zero-valued stock.** A resolved rate of 0 is not a price, it is a missing
  price. ``effective_rate`` lets a manually entered rate on the Truck Receipt
  line override the PO rate (the escape hatch — PO linkage is often missing by
  design of the current flow), and ``unpriced_lines`` names the receivable lines
  that still have no price at all. The caller blocks the whole receipt on those
  instead of booking stock into the warehouse at zero value.
* **Batch naming.** ``{container_number or CI}-{item_code}-{arrival_date}``.
* **Currency.** Rate/qty are USD/Kg; the PR is tagged ``currency = "USD"`` and
  the USD->company conversion_rate is deliberately left to ERPNext's own
  Currency Exchange defaults (documented assumption — stock items are held in
  Kg, so uom == stock_uom == "Kg", conversion_factor 1). How that currency gets
  resolved is unchanged; ``mismatched_currency_pos`` names the Purchase Orders whose
  currency is not the receipt's and ``hooks.py`` refuses the receipt over them,
  rather than mislabelling the rate.
"""

from __future__ import annotations

import math

STOCK_UOM = "Kg"

# Where the rate on a receipt line came from (see ``effective_rate``).
RATE_SOURCE_MANUAL = "manual"
RATE_SOURCE_PO = "purchase_order"
RATE_SOURCE_NONE = "none"


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


def _as_float(value) -> float:
	"""``value`` as a finite float, or 0.0 when it cannot be read as one.

	Blank (``None`` / ``""``), non-numeric text, NaN and infinity all collapse to
	0.0 instead of raising. Rates arrive from a web form and from PO rows, so
	"unreadable" is a real input; treating it as *no number* keeps the decision
	with the price rules below (which refuse to post a 0) rather than letting a
	``float()`` blow up mid-receipt or letting a NaN sail through ``> 0``.
	"""
	try:
		out = float(value)
	except (TypeError, ValueError):
		return 0.0
	if not math.isfinite(out):
		return 0.0
	return out


def effective_rate(manual_rate, po_rate) -> tuple[float, str]:
	"""``(rate, source)``. A manually entered rate wins over the resolved PO rate.

	A manual rate counts only when it reads as a positive number. Blank, zero,
	negative and unreadable manual input falls through to ``po_rate``; when that
	is not positive either the line has no price at all and the source is
	``RATE_SOURCE_NONE`` with a rate of 0.0 — which ``unpriced_lines`` reports and
	the caller refuses to post. Nothing here raises.
	"""
	manual = _as_float(manual_rate)
	if manual > 0:
		return round(manual, 4), RATE_SOURCE_MANUAL
	po = _as_float(po_rate)
	if po > 0:
		return round(po, 4), RATE_SOURCE_PO
	return 0.0, RATE_SOURCE_NONE


def unpriced_lines(rows) -> list[dict]:
	"""Rows that would enter the Purchase Receipt with no price.

	``rows`` is a list of dicts with at least: idx, item_code, qty, manual_rate,
	po_rate. Only rows with qty > 0 can reach the receipt (``build_pr_payload``
	drops the rest), so only those can be unpriced — a zero-qty line with no rate
	is not stock and not a problem.

	Returns the offending row dicts themselves (idx + item_code preserved) so the
	caller can name them. An empty list means every receivable line has a price.
	"""
	offenders: list[dict] = []
	for row in rows or []:
		if _as_float(row.get("qty")) <= 0:
			continue
		_rate, source = effective_rate(row.get("manual_rate"), row.get("po_rate"))
		if source == RATE_SOURCE_NONE:
			offenders.append(row)
	return offenders


def mismatched_currency_pos(resolved, po_item_rows, pr_currency) -> list[dict]:
	"""Purchase Orders in another currency that priced a line of this receipt.

	``resolved`` is the build path's per-line result: dicts with at least
	``item_code``, ``qty`` and ``source`` (see ``effective_rate``). ``po_item_rows``
	is the ``resolve_po_rate`` input with a ``currency`` on each row (its parent
	PO's). ``pr_currency`` is the currency the Purchase Receipt is tagged with.

	Only a PO-sourced rate can be mislabelled: a manually typed rate is a number in
	the receipt's currency by definition, and a zero-qty line never reaches the
	receipt, so neither is compared. A row whose PO carries no currency is skipped
	too — it cannot be compared, and it is not the mislabel this reports.

	Returns ``[{"purchase_order", "currency"}, ...]``, one entry per offending PO
	(deduped) ordered by PO name so the caller's message reads the same every run.
	An empty list means no rate on this receipt was read off a foreign-currency PO.
	"""
	priced_from_po = {
		row.get("item_code")
		for row in resolved or []
		if row.get("source") == RATE_SOURCE_PO and _as_float(row.get("qty")) > 0
	}
	if not priced_from_po:
		return []
	mismatched: dict[str, str] = {}
	for row in po_item_rows or []:
		if row.get("item_code") not in priced_from_po:
			continue
		currency = row.get("currency")
		if not currency or currency == pr_currency:
			continue
		mismatched[row.get("purchase_order")] = currency
	return [
		{"purchase_order": po, "currency": currency}
		for po, currency in sorted(mismatched.items(), key=lambda pair: str(pair[0]))
	]


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
