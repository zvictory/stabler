"""
One-off: run backfill_so_delivery logic for specific SOs WITHOUT the has_reserved_stock
gate.  Used for SOs whose SREs are already consumed (update_stock=0 SI path) but
whose classic reserved_qty is still stuck because delivered_qty=0.

Usage
-----
Dry-run (default):
  bench --site anjan.erpstable.com execute stabler.maintenance.backfill_so_forced.run

Live:
  bench --site anjan.erpstable.com execute stabler.maintenance.backfill_so_forced.run \
    --kwargs "{'dry_run': False}"
"""

from __future__ import annotations

import frappe
from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
from frappe.utils import flt

from stabler.maintenance.backfill_so_delivery import (
    _coerce_dry_run,
    _invoiced_qty_by_so_detail,
)

# SOs whose SREs are consumed but classic reserved_qty is still stuck.
# All items on these SOs have been verified to have sufficient on-hand stock.
_TARGET_SO_NAMES = [
    "SAL-ORD-2026-07718",
]


def run(dry_run=True):
    dry_run = _coerce_dry_run(dry_run)
    print(f"[backfill_so_forced] dry_run={dry_run}")

    for so_name in _TARGET_SO_NAMES:
        try:
            _process(so_name, dry_run)
        except Exception:
            frappe.db.rollback()
            print(f"  ERROR {so_name}:\n{frappe.get_traceback()}")


def _process(so_name: str, dry_run: bool) -> None:
    so = frappe.get_doc("Sales Order", so_name)
    if flt(so.per_delivered) >= 100:
        print(f"  SKIP {so_name}: already fully delivered")
        return

    invoiced_by_detail, has_unmapped = _invoiced_qty_by_so_detail(so_name)
    if has_unmapped:
        print(f"  SKIP {so_name}: unmapped SI lines — deliver manually")
        return

    items_to_deliver = []
    deliverable: dict[str, float] = {}
    for item in so.items:
        delivered = flt(item.delivered_qty)
        remaining = flt(item.qty) - delivered
        invoiced_undelivered = invoiced_by_detail.get(item.name, 0.0) - delivered
        qty = min(remaining, invoiced_undelivered)
        if qty > 0:
            deliverable[item.name] = qty
            items_to_deliver.append({"item_code": item.item_code, "qty": qty})

    if not items_to_deliver:
        print(f"  SKIP {so_name}: nothing invoiced-but-undelivered")
        return

    print(
        f"  {'DRY-RUN' if dry_run else 'LIVE'} {so_name} | "
        f"deliver={[(i['item_code'], i['qty']) for i in items_to_deliver]}"
    )

    if dry_run:
        return

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
        print(f"  SKIP {so_name}: no rows after capping")
        return

    # Do NOT back-date to the SI's posting_date: back-dating triggers a full
    # SLE repost chain that may fail "reserved stock" validation for other items
    # that were reserved/consumed in the interim.  Today's date is correct —
    # we're recording a stock adjustment now, not reconstructing history.

    dn.flags.ignore_permissions = True
    dn.insert()
    dn.submit()
    frappe.db.commit()

    print(f"  DONE {so_name} → {dn.name} (posting_date={dn.posting_date})")
