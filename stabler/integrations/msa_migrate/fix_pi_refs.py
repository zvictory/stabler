"""Fix missing or auto-generated supplier_pi_ref on Proforma Invoices to match Google Sheet master reference."""

import frappe

from .pi_ref_backfill import PI_ROWS


def run(dry_run=1):
	dry_run = int(dry_run)
	pis = frappe.get_all("Proforma Invoice", fields=["name", "supplier", "supplier_pi_ref", "agreed_total"])

	ref_by_tot = {round(float(r["agreed_total"]), 2): r["ref"] for r in PI_ROWS}

	fixes = []
	for pi in pis:
		orig = pi.supplier_pi_ref or ""
		tot = round(float(pi.agreed_total or 0), 2)
		expected_ref = ref_by_tot.get(tot)

		if expected_ref and (not orig or orig.startswith("PI-2026-") or orig != expected_ref):
			fixes.append(
				{
					"name": pi.name,
					"supplier": pi.supplier,
					"old_ref": orig,
					"new_ref": expected_ref,
					"agreed_total": tot,
				}
			)
			if not dry_run:
				frappe.db.set_value(
					"Proforma Invoice", pi.name, "supplier_pi_ref", expected_ref, update_modified=False
				)

	if not dry_run:
		frappe.db.commit()

	mode = "DRY-RUN" if dry_run else "APPLIED"
	print(f"\n=== FIX PROFORMA INVOICE REFS ({mode}) ===")
	for f in fixes:
		print(
			f"PI: {f['name']:15} | Supplier: {f['supplier']:35} | Old Ref: {f['old_ref']:20} -> New Ref: {f['new_ref']:25} | Agreed: ${f['agreed_total']:12,.2f}"
		)

	return fixes
