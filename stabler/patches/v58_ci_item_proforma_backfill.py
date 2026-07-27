"""Stamp the header's Proforma onto CI item rows that carry none (WP-I2 follow-up).

``Commercial Invoice`` and ``Commercial Invoice Item`` both carry
``custom_proforma_invoice``. Historically only the header was filled, so ~2 127
item rows have an empty row-level link. Every PI↔CI reconciliation therefore had
to fall back to the header — meaning a single-PI invoice reconciled fine but a
multi-PI one (83 of msa's 353 CIs) could not attribute its lines at all.

This copies the header value down to the rows that are still empty. Rows that
already name a proforma are never touched: on a multi-PI invoice the row is the
authoritative link and the header is only the first/primary one.

``patches.txt`` has no ``[post_model_sync]`` marker, so this runs BEFORE the
doctype DDL sync — hence the ``has_column`` guards on both tables rather than a
bare UPDATE.

Idempotent: the WHERE clause is self-clearing, so a second run matches 0 rows.
Reversible: the stamped rows are exactly those whose ``custom_proforma_invoice``
equals their parent's, and can be re-emptied with a single UPDATE.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Commercial Invoice"):
		return
	if not frappe.db.has_column("Commercial Invoice", "custom_proforma_invoice"):
		return
	if not frappe.db.has_column("Commercial Invoice Item", "custom_proforma_invoice"):
		return

	# `NOT IN ('', NULL)` is never TRUE in SQL — the NULL poisons the whole
	# comparison. COALESCE first, compare after.
	where = """
        WHERE COALESCE(cii.custom_proforma_invoice, '') = ''
          AND COALESCE(ci.custom_proforma_invoice, '') != ''
    """
	stamped = frappe.db.sql(
		f"""
        SELECT COUNT(*)
        FROM `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        {where}
        """
	)[0][0]
	if not stamped:
		return

	frappe.db.sql(
		f"""
        UPDATE `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        SET cii.custom_proforma_invoice = ci.custom_proforma_invoice
        {where}
        """
	)
	frappe.db.commit()
	print(f"v58_ci_item_proforma_backfill: stamped {stamped} Commercial Invoice Item row(s)")
