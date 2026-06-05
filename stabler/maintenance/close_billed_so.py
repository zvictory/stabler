"""
Auto-close fully-billed Sales Orders on Sales Invoice submit.

Background
----------
ERPNext tracks two independent reservation buckets on tabBin:

  reserved_stock  — the new SRE engine; released when an SI/DN increments the SRE's
                    delivered_qty (update_stock=1 SI does this correctly).
  reserved_qty    — the classic SO soft-reservation; released ONLY when
                    Sales Order Item.delivered_qty increases (via a Delivery Note)
                    OR when the SO status becomes Closed/On Hold.

A Sales Invoice — even with update_stock=1 — never advances SO.Item.delivered_qty, so
the classic reservation lingers even after goods have left and the SRE is consumed.

Fix (forward path only — update_stock=1 SIs)
--------------------------------------------
When a submitted SI carries update_stock=1, every linked Sales Order that is now fully
billed at qty level is Closed automatically.  SalesOrder.update_status("Closed") calls
update_reserved_qty() → update_bin_qty(..., get_reserved_qty(...)), and because
get_reserved_qty() filters status NOT IN ('Closed','On Hold'), the classic reservation
drops to 0 with NO new stock ledger entry.

The backlog of historic update_stock=0 SIs is handled separately by
stabler/maintenance/backfill_so_delivery.py (creates the missing Delivery Note).

Registered in hooks.py doc_events["Sales Invoice"]["on_submit"].
"""

from __future__ import annotations

import frappe

_logger = frappe.logger("stabler.close_billed_so")


def on_si_submit(doc, method=None):
    """Close any Sales Order that became fully billed as a result of this SI.

    Runs only when the SI moves stock (update_stock=1) — those SIs already
    wrote the stock-out SLE and consumed the SRE, so a Delivery Note would
    double-count the stock movement.  Closing the SO releases the classic
    reserved_qty without a second SLE.

    Failures are logged and swallowed — an SO close failure must never abort
    the SI submit or block EHF/Factura/1C processing that follows.
    """
    if not doc.update_stock:
        return

    # Collect distinct sales orders referenced by this invoice.
    so_names = {item.sales_order for item in doc.items if item.sales_order}
    if not so_names:
        return

    for so_name in so_names:
        try:
            _maybe_close(so_name)
        except Exception:
            frappe.log_error(
                title=f"close_billed_so: failed to close {so_name}",
                message=frappe.get_traceback(),
            )


def _maybe_close(so_name: str) -> None:
    """Close *so_name* if it is submitted, open, and fully billed."""
    so = frappe.get_doc("Sales Order", so_name)

    # Already closed/on-hold — nothing to do.
    if so.docstatus != 1 or so.status in ("Closed", "On Hold"):
        return

    # billing_status is maintained by ERPNext's update_billing_status() on each SI
    # submit/cancel.  "Fully Billed" means every SO line's amount is covered.
    # Note: billed_qty is NOT a physical DB column in this ERPNext version, so we
    # rely on the SO-level billing_status rather than per-item billed_qty checks.
    if so.billing_status != "Fully Billed":
        return

    # Every line fully billed: close the SO.
    # update_status("Closed") → set_status() → update_reserved_qty() →
    # update_bin_qty(..., get_reserved_qty(...))  [excludes Closed SOs]
    # → classic reserved_qty drops to 0 with no new SLE.
    so.update_status("Closed")
    _logger.info("auto-closed %s (billing_status=Fully Billed)", so_name)
