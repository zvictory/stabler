"""Server-side cap on how much a Commercial Invoice may allocate against a PI.

The SPA offers a remaining-quantity picker, but a picker is not a control: the
REST API is open and a client can post whatever it likes. This module is the
actual guarantee, and it runs from the Commercial Invoice's own ``validate`` —
`hooks.py` registers only an ``on_update`` doc_event for the doctype, which is
too late to refuse a write.

Three things make it safe to run on a live book:

1. **The same gate as the status pipeline** (``status_pipeline.assert_transition``):
   no-op during the msaerp ETL, and no-op for any company without the imports
   module. The six non-msa tenants never execute a line of this.
2. **Only the keys this save creates or increases are checked.** The msa book
   carries 21 keys / 25 959 boxes of REAL over-shipment. Checking every row would
   make those documents permanently unsaveable — and since "Cancelled" is an
   ordinary value of ``status`` written through a normal ``save()``, it would also
   freeze them in status forever. ``set_ci_status`` and
   ``compute_customs_fee(apply=1)`` write a header field and touch no item row;
   they must sail through, and they do.
3. **The invoice being saved is excluded from its own shipped balance**, so
   editing a CI never makes it cannibalise its own allocation.

The balance is keyed by ``(PI, category)`` — never by item. A PI line is usually
a compensated bundle that the CI ships broken into sub-cuts, so item-keying
matched 19.5% of CI lines against 98.3% for category-keying, and every bundle
read as 100% unshipped. See the invariants at the bottom of ``_imports_rules``.
"""

import frappe

from stabler.api import _imports_rules as rules
from stabler.stabler.imports_module.status_pipeline import _imports_active


def _ci_rows(doc) -> list[dict]:
	"""Commercial Invoice item rows as plain dicts for the frappe-free rules layer.

	``custom_proforma_invoice`` on the *header* is a site-level Custom Field, so it
	is read with ``getattr`` — a site that never carried the imports work has no
	such field. It is projected as ``header_proforma_invoice`` because that is the
	fallback name ``rules._shipped_pi`` looks for: the row link wins, the header is
	the fallback, and ~2 127 msa rows carry the link ONLY on the header.
	"""
	if doc is None:
		return []
	header_pi = getattr(doc, "custom_proforma_invoice", None) or ""
	return [
		{
			"custom_proforma_invoice": row.get("custom_proforma_invoice") or "",
			"header_proforma_invoice": header_pi,
			"category": row.get("category"),
			"item": row.get("item"),
			"boxes": row.get("boxes"),
			"qty": row.get("qty"),
		}
		for row in (doc.get("items") or [])
	]


def _fmt(value) -> str:
	"""Whole numbers read as whole numbers — 41 boxes, not 41.0."""
	number = float(value or 0)
	return str(int(number)) if number.is_integer() else str(round(number, 3))


def assert_within_remaining(doc) -> None:
	"""Refuse a save whose item rows claim more than the contract has left.

	Must be called BEFORE any ``is_new()`` early return in the controller: the SPA
	creates invoices with ``doc.insert()`` (``stabler/api/imports.py``
	``create_commercial_invoice``), and a brand-new CI over-allocating a contract
	is precisely the case this exists for.
	"""
	if frappe.flags.in_msaerp_migration:
		return
	if not _imports_active(getattr(doc, "company", None)):
		return

	after = _ci_rows(doc)
	if not after:
		return
	keys = rules.changed_allocation_keys(_ci_rows(doc.get_doc_before_save()), after)
	if not keys:
		return

	# Raw docnames for the query — a match key holds the *normalised* PI name.
	pi_names = sorted({pi for pi in (rules._shipped_pi(row) for row in after) if pi})
	if not pi_names:
		return

	# One query per side for every touched key, never one per row.
	pi_items = frappe.db.sql(
		"""
        SELECT parent AS pi_name, item, category, boxes, qty
        FROM `tabProforma Invoice Item`
        WHERE parent IN %(pi_names)s
        """,
		{"pi_names": tuple(pi_names)},
		as_dict=True,
	)
	if not pi_items:
		return

	from stabler.api.imports import _ci_item_effective_pi_expr

	eff_pi = _ci_item_effective_pi_expr()
	conds = [
		"ci.company = %(company)s",
		"ci.status != 'Cancelled'",
		f"{eff_pi} IN %(pi_names)s",
	]
	params = {"company": doc.company, "pi_names": tuple(pi_names)}
	if doc.name:
		# Never let an invoice consume its own allocation.
		conds.append("ci.name != %(self_name)s")
		params["self_name"] = doc.name

	shipped_rows = frappe.db.sql(
		f"""
        SELECT {eff_pi} AS pi_name, cii.category, cii.item, cii.parent AS ci_name,
               SUM(cii.boxes) AS boxes, SUM(cii.qty) AS qty
        FROM `tabCommercial Invoice Item` cii
        JOIN `tabCommercial Invoice` ci ON ci.name = cii.parent
        WHERE {" AND ".join(conds)}
        GROUP BY {eff_pi}, cii.category, cii.item, cii.parent
        """,
		params,
		as_dict=True,
	)

	breaches = rules.over_allocations(
		rules.contract_index(pi_items),
		rules.shipped_index(shipped_rows),
		after,
		keys,
	)
	if not breaches:
		return

	details = "; ".join(
		frappe._("{0} · {1}: {2} boxes / {3} kg allocated, {4} boxes / {5} kg remaining").format(
			breach["pi_name"],
			breach["label"],
			_fmt(breach["allocated_boxes"]),
			_fmt(breach["allocated_qty"]),
			_fmt(breach["remaining_boxes"]),
			_fmt(breach["remaining_qty"]),
		)
		for breach in breaches
	)
	frappe.throw(
		frappe._("These lines allocate more than the Proforma Invoice has left: {0}").format(details),
		title=frappe._("Over-allocated"),
	)
