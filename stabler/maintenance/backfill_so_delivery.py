"""
Backfill Delivery Notes for Sales Orders that are fully invoiced but never delivered.

Background
----------
Stabler Sales Invoices were historically submitted with update_stock=0, so ERPNext
never released the Sales Order stock reservations nor wrote stock-ledger entries on
SI submit.  Goods physically left the warehouse but the system still shows them
reserved-on-hand.

This script fixes the BACKLOG by creating + submitting one Delivery Note per stuck
Sales Order, which natively:
  (a) writes the stock-out SLE, and
  (b) consumes the Stock Reservation Entry (delivered_qty++ → reservation released,
      per_delivered → 100).

We do NOT touch the Sales Invoices (cancel/resubmit would re-fire EHF/Factura/1C
tax pushes and duplicate the tax invoice).

Usage
-----
Dry-run (default):
  bench --site anjan.erpstable.com execute stabler.maintenance.backfill_so_delivery.run

Live run (5 SOs at a time):
  bench --site anjan.erpstable.com execute stabler.maintenance.backfill_so_delivery.run \
    --kwargs "{'dry_run': False, 'limit': 5}"

Full live run for one company:
  bench --site anjan.erpstable.com execute stabler.maintenance.backfill_so_delivery.run \
    --kwargs "{'dry_run': False, 'company': 'My Company LLC'}"
"""

from __future__ import annotations

import frappe
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import has_reserved_stock
from frappe.utils import flt

_logger = frappe.logger("stabler.backfill_so_delivery")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_dry_run(value) -> bool:
	"""bench execute passes all kwargs as strings; normalise to bool."""
	if isinstance(value, bool):
		return value
	return str(value).strip().lower() not in ("0", "false", "no", "")


def _coerce_limit(value) -> int | None:
	if value is None or value == "":
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		return None


def _earliest_si_posting_date(so_name: str) -> str | None:
	"""Return the posting_date of the earliest submitted Sales Invoice linked to *so_name*."""
	rows = frappe.db.sql(
		"""
		SELECT MIN(si.posting_date)
		FROM `tabSales Invoice` si
		INNER JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE sii.sales_order = %(so)s
		  AND si.docstatus = 1
		""",
		{"so": so_name},
	)
	if rows and rows[0][0]:
		return str(rows[0][0])
	return None


def _invoiced_qty_by_so_detail(so_name: str) -> tuple[dict[str, float], bool]:
	"""Map SO-item (so_detail) → total invoiced qty across submitted SIs.

	Returns (qty_by_detail, has_unmapped). `has_unmapped` is True if any submitted
	Sales Invoice line for this SO carries no so_detail — meaning we cannot
	precisely attribute its qty to an SO row, so the SO needs manual handling
	rather than an automatic full-remaining delivery.
	"""
	rows = frappe.db.sql(
		"""
		SELECT sii.so_detail, COALESCE(SUM(sii.qty), 0) AS qty
		FROM `tabSales Invoice Item` sii
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.sales_order = %(so)s
		  AND si.docstatus = 1
		GROUP BY sii.so_detail
		""",
		{"so": so_name},
		as_dict=True,
	)
	qty_by_detail: dict[str, float] = {}
	has_unmapped = False
	for r in rows:
		if r.so_detail:
			qty_by_detail[r.so_detail] = flt(r.qty)
		elif flt(r.qty) > 0:
			has_unmapped = True
	return qty_by_detail, has_unmapped


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _find_candidates(company: str | None, limit: int | None) -> list[str]:
	"""Return a deterministic list of SO names that need a backfill Delivery Note.

	Criteria (all must be true):
	  1. SO is submitted (docstatus=1).
	  2. SO appears as `sales_order` on at least one submitted Sales Invoice Item.
	  3. SO.per_delivered < 100  (not yet fully delivered in ERPNext).
	  4. has_reserved_stock("Sales Order", so_name) is True.
	  5. Optional company filter.

	We evaluate criteria 1-3 (and 5) in SQL for efficiency, then filter by
	has_reserved_stock() in Python (it runs its own DB query internally).
	"""
	company_cond = "AND so.company = %(company)s" if company else ""
	limit_clause = f"LIMIT {int(limit)}" if limit else ""

	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT so.name
		FROM `tabSales Order` so
		INNER JOIN `tabSales Invoice Item` sii ON sii.sales_order = so.name
		INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE so.docstatus = 1
		  AND si.docstatus = 1
		  AND so.per_delivered < 100
		  {company_cond}
		ORDER BY so.name ASC
		{limit_clause}
		""",
		{"company": company} if company else {},
	)

	candidates = [r[0] for r in rows]

	# Filter by active stock reservation (Python-side — has_reserved_stock runs its own SQL).
	return [so for so in candidates if has_reserved_stock("Sales Order", so)]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(dry_run=True, limit=None, company=None):
	"""
	Idempotent backfill: one Delivery Note per stuck Sales Order.

	Parameters
	----------
	dry_run : bool | str
	    Default True.  Pass False / "false" / "0" to actually create DNs.
	limit : int | str | None
	    Max number of SOs to process in this run.
	company : str | None
	    Restrict to a single company.  None = all companies.
	"""
	dry_run = _coerce_dry_run(dry_run)
	limit = _coerce_limit(limit)
	company = company or None  # normalise empty string → None

	print(f"[backfill_so_delivery] Starting — dry_run={dry_run}, limit={limit}, company={company or 'ALL'}")

	candidates = _find_candidates(company, limit)
	print(f"[backfill_so_delivery] Found {len(candidates)} candidate SO(s) with active reservations.")

	summary: dict = {
		"dry_run": dry_run,
		"candidates": len(candidates),
		"delivered": [],
		"skipped": [],
		"needs_manual": [],
		"errors": [],
		"created_delivery_notes": [],
	}

	for so_name in candidates:
		# ------------------------------------------------------------------
		# Idempotency guard: re-fetch current state inside the loop.
		# A previous iteration (or a concurrent process) may have already
		# delivered this SO.
		# ------------------------------------------------------------------
		so = frappe.get_doc("Sales Order", so_name)
		if flt(so.per_delivered) >= 100:
			reason = "already fully delivered (per_delivered >= 100)"
			print(f"  SKIP {so_name}: {reason}")
			summary["skipped"].append({"so": so_name, "reason": reason})
			continue

		if not has_reserved_stock("Sales Order", so_name):
			reason = "no active stock reservation"
			print(f"  SKIP {so_name}: {reason}")
			summary["skipped"].append({"so": so_name, "reason": reason})
			continue

		# ------------------------------------------------------------------
		# SAFETY: deliver only the INVOICED-but-undelivered qty per row, never the
		# full SO balance. make_delivery_note maps qty = ordered - delivered, which
		# would over-ship the un-invoiced portion of a partially-invoiced SO. We cap
		# each row to min(ordered - delivered, invoiced - delivered) using qty-level
		# invoiced totals (immune to per_billed amount noise from discounts/freight).
		#   - Full invoice  → cap = full remaining → reservation fully released.
		#   - Partial qty   → cap = invoiced portion → balance stays reserved.
		# ------------------------------------------------------------------
		invoiced_by_detail, has_unmapped = _invoiced_qty_by_so_detail(so_name)
		if has_unmapped:
			reason = "submitted SI line(s) have no so_detail — cannot map invoiced qty; deliver manually"
			print(f"  NEEDS-MANUAL {so_name}: {reason}")
			summary["needs_manual"].append({"so": so_name, "reason": reason})
			continue

		# deliverable[so_detail] = capped qty to ship for that SO row.
		deliverable: dict[str, float] = {}
		items_to_deliver = []
		for item in so.items:
			delivered = flt(item.delivered_qty)
			remaining = flt(item.qty) - delivered
			invoiced_undelivered = invoiced_by_detail.get(item.name, 0.0) - delivered
			qty = min(remaining, invoiced_undelivered)
			if qty > 0:
				deliverable[item.name] = qty
				items_to_deliver.append({"item_code": item.item_code, "qty_to_deliver": qty})

		if not items_to_deliver:
			reason = "nothing invoiced-but-undelivered to ship"
			print(f"  SKIP {so_name}: {reason}")
			summary["skipped"].append({"so": so_name, "reason": reason})
			continue

		if dry_run:
			entry = {
				"so": so_name,
				"customer": so.customer,
				"per_delivered": flt(so.per_delivered),
				"items": items_to_deliver,
			}
			print(
				f"  DRY-RUN {so_name} | customer={so.customer} | "
				f"per_delivered={flt(so.per_delivered):.1f}% | "
				f"deliver={[(i['item_code'], i['qty_to_deliver']) for i in items_to_deliver]}"
			)
			summary["delivered"].append(entry)
			continue

		# ------------------------------------------------------------------
		# Live run: create + submit the Delivery Note, capping each row qty to the
		# invoiced-but-undelivered amount computed above.
		# ------------------------------------------------------------------
		try:
			dn = make_delivery_note(so_name)

			kept = []
			for row in dn.items:
				cap = deliverable.get(row.so_detail, 0.0)
				if cap <= 0:
					continue
				if flt(row.qty) > cap:
					row.qty = cap
				kept.append(row)
			dn.items = kept
			if not dn.items:
				reason = "no DN rows left after capping to invoiced qty"
				print(f"  SKIP {so_name}: {reason}")
				summary["skipped"].append({"so": so_name, "reason": reason})
				continue

			# Set posting_date to the earliest SI posting_date for this SO,
			# so the stock-out lands in the period the goods were actually sold.
			posting_date = _earliest_si_posting_date(so_name)
			if posting_date:
				dn.set_posting_time = 1
				dn.posting_date = posting_date

			dn.flags.ignore_permissions = True
			dn.insert()
			dn.submit()

			# Commit after each successful SO so a later failure doesn't roll
			# back earlier fixes.
			frappe.db.commit()

			print(f"  DONE {so_name} → Delivery Note {dn.name} (posting_date={dn.posting_date})")
			summary["delivered"].append(so_name)
			summary["created_delivery_notes"].append(dn.name)

		except Exception as exc:
			frappe.db.rollback()
			err_msg = str(exc)
			print(f"  ERROR {so_name}: {err_msg}")
			summary["errors"].append({"so": so_name, "error": err_msg})

	# ------------------------------------------------------------------
	# Final summary
	# ------------------------------------------------------------------
	print("\n[backfill_so_delivery] === Summary ===")
	print(f"  dry_run              : {summary['dry_run']}")
	print(f"  candidates           : {summary['candidates']}")
	if dry_run:
		print(f"  would deliver        : {len(summary['delivered'])} SO(s)")
	else:
		print(f"  delivered            : {len(summary['delivered'])} SO(s)")
		print(f"  created DNs          : {summary['created_delivery_notes']}")
	print(f"  skipped              : {len(summary['skipped'])} SO(s)")
	print(f"  needs manual review  : {len(summary['needs_manual'])} SO(s)")
	print(f"  errors               : {len(summary['errors'])} SO(s)")
	if summary["needs_manual"]:
		for m in summary["needs_manual"]:
			print(f"    MANUAL {m['so']}: {m['reason']}")
	if summary["errors"]:
		for e in summary["errors"]:
			print(f"    {e['so']}: {e['error']}")

	_logger.info("backfill_so_delivery summary: %s", summary)

	return summary
