"""Import the 243 legacy MSA Commercial Invoices as Stabler CI header records.

PHASE 1 — headers only: ci_number (original), supplier, date, status, totals
(boxes/kg/agreed/docs/diff), incoterm, and the link to the SOURCE PI via
custom_proforma_invoice. This is what powers the smart PI list's "Invoiced %"
and CI count. Line items, containers, expenses and advance allocations are a
later phase (they need item-code -> Item mapping and extra doctypes).

Idempotent + DRY-RUN by default. Depends on the PI ref backfill having run first
(pi_ref_backfill.run) so each source PI ref resolves to a Stabler PI.

Data: the 243 rows ship with the module (data/msa_ci_rows.json), so no manual
upload is needed — a site private-files copy still takes precedence if present.

Run on the msa site:
    bench --site msa.erpstable.com execute \
        stabler.integrations.msa_migrate.ci_backfill.run --kwargs "{'dry_run': 1}"
Review the report, then dry_run=0 to create.

Notes / known limits (audited):
- Stabler CI is 1:1 with a PI (custom_proforma_invoice single Link); 3 of the 243
  CIs source from multiple PIs — those link to the FIRST source PI and are flagged
  MULTI_PI in the report (invoiced% attributes the whole CI to that one PI).
- The CI controller does NOT recompute totals on insert, so agreed/docs/boxes/kg
  are written as-is (no line items needed).
"""

from __future__ import annotations

import json
import os
from collections import Counter

import frappe
from frappe.utils import getdate

from .pi_ref_backfill import _default_company, _resolve_supplier

_DATA_FILE = "msa_ci_rows.json"
_CI_STATUSES = {
    "BOOKED", "STUFFED", "GATE_IN", "ON_BOARD", "IN_TRANSIT", "DISCHARGED",
    "AVAILABLE", "ARRIVED_AT_IRAN", "DELIVERED_TO_UZBEKISTAN", "Cancelled",
}


def _resolve_pi(ref: str):
    """Stabler PI name for an original ref (name == ref, or supplier_pi_ref == ref)."""
    if not ref:
        return None
    if frappe.db.exists("Proforma Invoice", ref):
        return ref
    return frappe.db.get_value("Proforma Invoice", {"supplier_pi_ref": ref}, "name")


def _load_rows():
    # Prefer a site private-files override; otherwise the copy shipped with the module.
    site_path = frappe.get_site_path("private", "files", _DATA_FILE)
    module_path = os.path.join(os.path.dirname(__file__), "data", _DATA_FILE)
    path = site_path if os.path.exists(site_path) else module_path
    if not os.path.exists(path):
        frappe.throw(f"CI data file not found ({module_path}).")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(dry_run=1, company=None):
    dry_run = int(dry_run)
    company = company or _default_company()
    rows = _load_rows()
    has_link = frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice")
    report = []

    for r in rows:
        cin = r.get("ci_number")
        if not cin:
            continue
        if frappe.db.get_value("Commercial Invoice", {"ci_number": cin}, "name"):
            report.append((cin, "OK (exists)", ""))
            continue
        supplier = _resolve_supplier(r.get("vendor"))
        if not supplier:
            report.append((cin, "NO_SUPPLIER", r.get("vendor")))
            continue
        pis = r.get("source_pis") or []
        pi = _resolve_pi(pis[0]) if pis else None
        multi = " MULTI_PI" if len(pis) > 1 else ""
        status = r.get("status") if r.get("status") in _CI_STATUSES else "BOOKED"

        if dry_run:
            tag = "CREATE" if pi or not pis else "CREATE (PI unresolved)"
            report.append((cin, tag + multi, f"pi={pi or '—'}"))
            continue

        doc = frappe.new_doc("Commercial Invoice")
        doc.update({
            "company": company, "supplier": supplier, "ci_number": cin,
            "ci_date": getdate(r.get("ci_date")) if r.get("ci_date") else frappe.utils.today(),
            "status": status, "currency": "USD", "incoterm": r.get("incoterm"),
            "total_boxes": int(r.get("total_boxes") or 0), "total_kg": r.get("total_kg") or 0,
            "agreed_total": r.get("agreed_total") or 0, "docs_total": r.get("docs_total") or 0,
            "cash_difference": r.get("cash_difference") or 0,
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
        if has_link and pi:
            frappe.db.set_value("Commercial Invoice", doc.name, "custom_proforma_invoice", pi)
        report.append((cin, f"CREATED -> {doc.name}" + multi, f"pi={pi or '—'}"))

    if not dry_run:
        frappe.db.commit()

    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(f"\n=== MSA CI backfill ({mode}) · company={company} · rows={len(rows)} ===")
    for cin, status, note in report:
        print(f"  {cin:22} {status:30} {note}")
    print("summary:", dict(Counter(s.split(" ")[0] for _, s, _ in report)))
    return report
