"""
Auto-close fully-billed Sales Orders and release Stock Reservation Entries on SI submit.

Background
----------
ERPNext tracks two independent reservation buckets on tabBin:

  reserved_stock  — the SRE engine; released when an SI/DN increments the SRE's
                    delivered_qty (update_stock=1 SI does this correctly) OR when the
                    SRE is explicitly cancelled.
  reserved_qty    — the classic SO soft-reservation; released ONLY when
                    Sales Order Item.delivered_qty increases (via a Delivery Note)
                    OR when the SO status becomes Closed/On Hold.

A Sales Invoice — even with update_stock=1 — never advances SO.Item.delivered_qty, so
the classic reservation lingers even after goods have left and the SRE is consumed.

Fix
---
On any SI submit, every linked Sales Order has its still-open SREs cancelled immediately
(_release_reservations).  This prevents orphaned SREs regardless of update_stock.

For update_stock=1 SIs, the existing auto-close also runs: if the SO is now fully billed,
update_status("Closed") drops the classic reserved_qty without a new SLE (_maybe_close).

The backlog of historic update_stock=0 SIs is handled separately by
stabler/maintenance/backfill_so_delivery.py (creates the missing Delivery Note).

Registered in hooks.py doc_events["Sales Invoice"]["on_submit"].
"""

from __future__ import annotations

import frappe

_logger = frappe.logger("stabler.close_billed_so")


def on_si_submit(doc, method=None):
    """Release stock reservations and optionally close Sales Orders on SI submit.

    Two independent actions run for every linked Sales Order:

    1. **SRE release (always):** cancel any still-open Stock Reservation Entries
       (status not in Delivered/Cancelled).  Runs regardless of update_stock so
       that update_stock=0 invoices do not leave orphaned SREs behind.

    2. **Auto-close (update_stock=1 only):** if the SI moves stock, and the SO is
       now fully billed, call update_status("Closed") to drop the classic
       reserved_qty.  Skipped for update_stock=0 SIs because those SOs may still
       need a Delivery Note.

    Failures are logged and swallowed — nothing here must abort the SI submit or
    block EHF/Factura/1C processing that follows.
    """
    # Collect distinct sales orders referenced by this invoice.
    so_names = {item.sales_order for item in doc.items if item.sales_order}
    if not so_names:
        return

    for so_name in so_names:
        try:
            _release_reservations(so_name)
            if doc.update_stock:
                _maybe_close(so_name)
        except Exception as exc:
            frappe.log_error(
                title=f"close_billed_so: failed for {so_name}",
                message=frappe.get_traceback(),
            )
            # Also record on the SO itself so failures are queryable without
            # trawling the Error Log (silent failures are the whole bug class).
            billing_status = frappe.db.get_value("Sales Order", so_name, "billing_status") or "unknown"
            _record_close_failure(so_name, billing_status, str(exc))


def _record_close_failure(so_name: str, billing_status: str, reason: str) -> None:
    """Leave a visible trace on the SO when auto-close fails silently."""
    try:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Sales Order",
            "reference_name": so_name,
            "content": (
                f"[stabler] auto-close failed (billing_status={billing_status}): "
                f"{reason or 'see Error Log'}. Close manually via Stabler or investigate."
            ),
        }).insert(ignore_permissions=True)
    except Exception:
        pass  # Never let the recorder abort anything


def _release_reservations(so_name: str) -> None:
    """Cancel the still-open Stock Reservation Entries for *so_name*.

    Uses an explicit sre_list (pre-filtered to non-Delivered/Cancelled) rather
    than the voucher_no= overload, which would also cancel already-Delivered SREs
    and reverse real delivery bookkeeping.
    """
    open_sres = frappe.get_all(
        "Stock Reservation Entry",
        filters={
            "voucher_type": "Sales Order",
            "voucher_no": so_name,
            "docstatus": 1,
            "status": ["not in", ["Delivered", "Cancelled"]],
        },
        pluck="name",
    )
    if not open_sres:
        return
    from erpnext.stock.doctype.stock_reservation_entry.stock_reservation_entry import (
        cancel_stock_reservation_entries,
    )
    cancel_stock_reservation_entries(sre_list=open_sres, notify=False)
    _logger.info("released %d SRE(s) for %s", len(open_sres), so_name)


def _maybe_close(so_name: str) -> None:
    """Close *so_name* if it is submitted, open, and fully billed.

    ERPNext's update_billing_status() runs inside SI.submit() before doc_events
    fire, so billing_status in the DB is already current by the time we arrive.
    We load fresh with get_doc (not a cached copy) and then re-read billing_status
    directly from the DB as a belt-and-suspenders check.
    """
    so = frappe.get_doc("Sales Order", so_name)

    # Already closed/on-hold — nothing to do.
    if so.docstatus != 1 or so.status in ("Closed", "On Hold"):
        return

    # Re-read billing_status directly from DB to be explicit about intent and
    # guard against any future Frappe get_doc caching changes.
    # ERPNext's update_billing_status() runs earlier in the submit pipeline so
    # the value here already reflects this SI's contribution.
    billing_status = frappe.db.get_value("Sales Order", so_name, "billing_status")
    if billing_status != "Fully Billed":
        return

    # Every line fully billed: close the SO.
    # update_status("Closed") → set_status() → update_reserved_qty() →
    # update_bin_qty(..., get_reserved_qty(...))  [excludes Closed SOs]
    # → classic reserved_qty drops to 0 with no new SLE.
    so.update_status("Closed")
    _logger.info("auto-closed %s (billing_status=Fully Billed)", so_name)
