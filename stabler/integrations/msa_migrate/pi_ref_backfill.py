"""Backfill the ORIGINAL MSA supplier PI reference onto Stabler Proforma Invoices.

The old MSA system's 36 PIs carry the real supplier refs (e.g.
"FIR/25-26/29639-29647"); in Stabler those records may be auto-named
PI-2026-000xx. This attaches the original ref to the `supplier_pi_ref` field so
the SPA shows it (see ProformaInvoices.vue "Orig. ref"). The auto name is left
untouched — Frappe autoname only fires on insert, so set_value here does NOT
rename; it just stores the real ref alongside.

Idempotent + DRY-RUN by default. Because the PI doctype has no PO link, matches
are made on supplier + agreed_total (docs_total as fallback) and printed for
review before anything is written.

Run on the msa site:
    bench --site msa.erpstable.com execute \
        stabler.integrations.msa_migrate.pi_ref_backfill.run --kwargs "{'dry_run': 1}"
After reviewing the report, apply with dry_run=0. Pass create_missing=1 to also
create header-only PI records for refs not found in Stabler.
"""

from __future__ import annotations

from collections import Counter

import frappe
from frappe.utils import flt, getdate

# ref · vendor · date · currency · incoterm · agreed_total · docs_total · advance_pct · po · status
PI_ROWS = [
    {"ref": "FIR/25-26/29639-29647", "vendor": "FAIR EXPORTS (INDIA) PVT. LTD.", "date": "2026-01-07", "currency": "USD", "incoterm": "CIF", "agreed_total": 1119040.92, "docs_total": 1119040.92, "advance_pct": 30.0, "po": "PUR-ORD-2026-00035", "status": "Draft"},
    {"ref": "PRO/ALS/100/25-26", "vendor": "Al Super Frozen Food Private Limited", "date": "2026-01-07", "currency": "USD", "incoterm": "CIF", "agreed_total": 1832040.0, "docs_total": 1806000.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00033", "status": "Confirmed"},
    {"ref": "PRO/MEPL/0538/25-26", "vendor": "Mirha Exports Private limited", "date": "2026-01-07", "currency": "USD", "incoterm": "CIF", "agreed_total": 1536416.0, "docs_total": 1358280.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00034", "status": "Confirmed"},
    {"ref": "HMA/PI/2229/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2026-01-03", "currency": "USD", "incoterm": "CIF", "agreed_total": 5265513.6, "docs_total": 4872069.6, "advance_pct": 30.0, "po": "PUR-ORD-2026-00032", "status": "Confirmed"},
    {"ref": "HMA/PI/2230/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2026-01-03", "currency": "USD", "incoterm": "CIF", "agreed_total": 2094400.0, "docs_total": 2094400.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00036", "status": "Confirmed"},
    {"ref": "HMA/PI/1948/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-12-08", "currency": "USD", "incoterm": "CIF", "agreed_total": 280000.0, "docs_total": 243600.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00031", "status": "Draft"},
    {"ref": "HMA/PI/1913/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-12-05", "currency": "USD", "incoterm": "CIF", "agreed_total": 75600.0, "docs_total": 75600.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00030", "status": "Draft"},
    {"ref": "FIR/25-26/28917-28925", "vendor": "FAIR EXPORTS (INDIA) PVT. LTD.", "date": "2025-12-03", "currency": "USD", "incoterm": "CIF", "agreed_total": 1229696.56, "docs_total": 1229696.56, "advance_pct": 30.0, "po": "PUR-ORD-2026-00024", "status": "Draft"},
    {"ref": "HMA/PI/1843/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-12-02", "currency": "USD", "incoterm": "CIF", "agreed_total": 4848872.0, "docs_total": 4506669.6, "advance_pct": 30.0, "po": "PUR-ORD-2026-00028", "status": "Draft"},
    {"ref": "HMA/PI/1844/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-12-02", "currency": "USD", "incoterm": "CIF", "agreed_total": 1502200.0, "docs_total": 1502200.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00029", "status": "Draft"},
    {"ref": "PRO/ALS/080/25-26", "vendor": "Al Super Frozen Food Private Limited", "date": "2025-12-01", "currency": "USD", "incoterm": "CIF", "agreed_total": 1827000.0, "docs_total": 1827000.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00026", "status": "Draft"},
    {"ref": "PRO/MEPL/0421/25-26", "vendor": "Mirha Exports Private limited", "date": "2025-12-01", "currency": "USD", "incoterm": "CIF", "agreed_total": 778428.2, "docs_total": 778428.2, "advance_pct": 30.0, "po": "PUR-ORD-2026-00025", "status": "Draft"},
    {"ref": "HMA/PI/1796/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-11-28", "currency": "USD", "incoterm": "CIF", "agreed_total": 1054200.0, "docs_total": 1031800.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00027", "status": "Draft"},
    {"ref": "FIR/25-26/28611-28616", "vendor": "FAIR EXPORTS (INDIA) PVT. LTD.", "date": "2025-11-20", "currency": "USD", "incoterm": "CIF", "agreed_total": 658000.0, "docs_total": 658000.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00023", "status": "Draft"},
    {"ref": "FIR/25-26/27482-27493", "vendor": "FAIR EXPORTS (INDIA) PVT. LTD.", "date": "2025-10-04", "currency": "USD", "incoterm": "CIF", "agreed_total": 1514744.56, "docs_total": 1514744.56, "advance_pct": 30.0, "po": "PUR-ORD-2026-00020", "status": "Draft"},
    {"ref": "HMA/PI/1351/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-10-03", "currency": "USD", "incoterm": "CIF", "agreed_total": 8072076.48, "docs_total": 7484464.8, "advance_pct": 30.0, "po": "PUR-ORD-2026-00021", "status": "Draft"},
    {"ref": "HMA/PI/1352/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-10-03", "currency": "USD", "incoterm": "CIF", "agreed_total": 2297431.2, "docs_total": 2297431.2, "advance_pct": 30.0, "po": "PUR-ORD-2026-00022", "status": "Draft"},
    {"ref": "HMA/PI/1240/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-09-24", "currency": "USD", "incoterm": "CIF", "agreed_total": 1162000.0, "docs_total": 1092000.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00017", "status": "Draft"},
    {"ref": "HMA/PI/1241/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-09-24", "currency": "USD", "incoterm": "CIF", "agreed_total": 342300.0, "docs_total": 327600.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00016", "status": "Draft"},
    {"ref": "HMA/PI/1209/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-09-19", "currency": "USD", "incoterm": "CIF", "agreed_total": 142800.0, "docs_total": 142800.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00018", "status": "Draft"},
    {"ref": "PRO/MEPL/0291/2526", "vendor": "Mirha Exports Private limited", "date": "2025-09-19", "currency": "USD", "incoterm": "CIF", "agreed_total": 3049300.0, "docs_total": 3049300.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00019", "status": "Draft"},
    {"ref": "HMA/PI/1167/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-09-12", "currency": "USD", "incoterm": "CIF", "agreed_total": 6887248.8, "docs_total": 6224462.4, "advance_pct": 30.0, "po": "PUR-ORD-2026-00014", "status": "Draft"},
    {"ref": "HMA/PI/1168/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-09-12", "currency": "USD", "incoterm": "CIF", "agreed_total": 912800.0, "docs_total": 912800.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00015", "status": "Draft"},
    {"ref": "PRO/MEPL/0187/25-26", "vendor": "Mirha Exports Private limited", "date": "2025-08-05", "currency": "USD", "incoterm": "CIF", "agreed_total": 1416100.0, "docs_total": 1223040.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00012", "status": "Draft"},
    {"ref": "PRO/MEPL/0188/25-26", "vendor": "Mirha Exports Private limited", "date": "2025-08-05", "currency": "USD", "incoterm": "CIF", "agreed_total": 61600.0, "docs_total": 56000.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00013", "status": "Draft"},
    {"ref": "HMA/PI/693/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-07-23", "currency": "USD", "incoterm": "CIF", "agreed_total": 6835584.0, "docs_total": 6029858.4, "advance_pct": 30.0, "po": "PUR-ORD-2026-00010", "status": "Draft"},
    {"ref": "HMA/PI/694/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-07-23", "currency": "USD", "incoterm": "CIF", "agreed_total": 700000.0, "docs_total": 700000.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00011", "status": "Draft"},
    {"ref": "IFF/EXP/25/247", "vendor": "IFF India Frozen Foods Private Limited", "date": "2025-06-20", "currency": "USD", "incoterm": "CIF", "agreed_total": 2430400.0, "docs_total": 1944320.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00009", "status": "Draft"},
    {"ref": "HMA/PI/405/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-06-19", "currency": "USD", "incoterm": "CIF", "agreed_total": 5878642.4, "docs_total": 5283629.6, "advance_pct": 30.0, "po": "PUR-ORD-2026-00006", "status": "Draft"},
    {"ref": "PRO/MEPL/0100/25-26", "vendor": "Mirha Exports Private limited", "date": "2025-06-16", "currency": "USD", "incoterm": "CIF", "agreed_total": 1360800.0, "docs_total": 1088640.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00007", "status": "Confirmed"},
    {"ref": "FIR/25-26/24534-24545", "vendor": "FAIR EXPORTS (INDIA) PVT. LTD.", "date": "2025-06-14", "currency": "USD", "incoterm": "CIF", "agreed_total": 1797633.25, "docs_total": 1797633.25, "advance_pct": 30.0, "po": "PUR-ORD-2026-00008", "status": "Draft"},
    {"ref": "FIR/25-26/24126-24137", "vendor": "FAIR EXPORTS (INDIA) PVT. LTD.", "date": "2025-05-17", "currency": "USD", "incoterm": "CIF", "agreed_total": 1390345.8, "docs_total": 1390345.8, "advance_pct": 30.0, "po": "PUR-ORD-2026-00005", "status": "Draft"},
    {"ref": "PRO/MEPL/0034/2526", "vendor": "Mirha Exports Private limited", "date": "2025-05-02", "currency": "USD", "incoterm": "CIF", "agreed_total": 2363239.2, "docs_total": 1901791.36, "advance_pct": 30.0, "po": "PUR-ORD-2026-00004", "status": "Confirmed"},
    {"ref": "HMA/PI/143/2025-26", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-05-01", "currency": "USD", "incoterm": "CIF", "agreed_total": 7645622.8, "docs_total": 6665455.2, "advance_pct": 30.0, "po": "PUR-ORD-2026-00003", "status": "Draft"},
    {"ref": "PRO/MEPL/0012/2526", "vendor": "Mirha Exports Private limited", "date": "2025-04-07", "currency": "USD", "incoterm": "CIF", "agreed_total": 1268400.0, "docs_total": 1268400.0, "advance_pct": 30.0, "po": "PUR-ORD-2026-00002", "status": "Confirmed"},
    {"ref": "HMA/PI/2677/202425", "vendor": "HMA AGRO INDUSTRIES LIMITED", "date": "2025-03-29", "currency": "USD", "incoterm": "CIF", "agreed_total": 5381616.4, "docs_total": 5381616.4, "advance_pct": 30.0, "po": "PUR-ORD-2026-00001", "status": "Confirmed"},
]

_EPS = 1.0  # currency tolerance when matching a total


def _resolve_supplier(vendor: str):
    """Exact supplier_name, then case-insensitive, then a first-word LIKE (only
    when it resolves to a single supplier)."""
    name = frappe.db.get_value("Supplier", {"supplier_name": vendor}, "name")
    if name:
        return name
    rows = frappe.db.sql(
        "SELECT name FROM `tabSupplier` WHERE LOWER(supplier_name) = LOWER(%s) LIMIT 1", vendor
    )
    if rows:
        return rows[0][0]
    key = (vendor or "").split()[0]
    rows = frappe.db.sql("SELECT name FROM `tabSupplier` WHERE supplier_name LIKE %s LIMIT 2", f"{key}%")
    return rows[0][0] if len(rows) == 1 else None


def _default_company():
    return (
        frappe.defaults.get_global_default("company")
        or frappe.db.get_value("Company", {}, "name")
    )


def run(dry_run=1, company=None, create_missing=0):
    dry_run, create_missing = int(dry_run), int(create_missing)
    company = company or _default_company()
    report = []

    for r in PI_ROWS:
        ref = r["ref"]
        if frappe.db.exists("Proforma Invoice", ref) or frappe.db.get_value(
            "Proforma Invoice", {"supplier_pi_ref": ref}, "name"
        ):
            report.append((ref, "OK (has ref)", ""))
            continue

        supplier = _resolve_supplier(r["vendor"])
        if not supplier:
            report.append((ref, "NO_SUPPLIER", r["vendor"]))
            continue

        cands = frappe.db.sql(
            """SELECT name, agreed_total, docs_total FROM `tabProforma Invoice`
               WHERE supplier = %s AND company = %s""",
            (supplier, company),
            as_dict=True,
        )
        match = [
            c for c in cands
            if abs(flt(c.agreed_total) - r["agreed_total"]) < _EPS
            or abs(flt(c.docs_total) - r["docs_total"]) < _EPS
        ]
        if len(match) == 1:
            report.append((ref, f"SET_REF -> {match[0].name}", ""))
            if not dry_run:
                frappe.db.set_value("Proforma Invoice", match[0].name, "supplier_pi_ref", ref)
        elif len(match) > 1:
            report.append((ref, f"AMBIGUOUS ({len(match)})", ", ".join(c.name for c in match)))
        elif create_missing and not dry_run:
            doc = frappe.new_doc("Proforma Invoice")
            doc.update({
                "supplier": supplier, "company": company, "supplier_pi_ref": ref,
                "pi_date": getdate(r["date"]), "currency": r["currency"],
                "incoterm": r.get("incoterm"), "agreed_total": r["agreed_total"],
                "docs_total": r["docs_total"], "advance_pct": r["advance_pct"],
                "status": "CONFIRMED" if r["status"] == "Confirmed" else "DRAFT",
                "remarks": f"Imported from MSA. PO: {r['po']}",
            })
            doc.insert(ignore_permissions=True)
            report.append((ref, f"CREATED -> {doc.name}", supplier))
        else:
            report.append((ref, "MISSING (would create)", supplier))

    if not dry_run:
        frappe.db.commit()

    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(f"\n=== MSA PI ref backfill ({mode}) · company={company} ===")
    for ref, status, note in report:
        print(f"  {ref:24} {status:26} {note}")
    print("summary:", dict(Counter(s.split(" ")[0].split("_")[0] for _, s, _ in report)))
    return report
