"""Which Purchase Invoice is THE goods invoice of a Commercial Invoice (R0.1).

A CI is linked to a Purchase Invoice through the v46 ``custom_commercial_invoice``
ref. That ref is deliberately many-to-one: a transporter's freight bill and a
service provider's fee are attributed to the same CI so the landed cost picture
is complete — the truck-transport automation in ``imports_module/hooks.py``
already books such a bill against the trucking company.

So the ref alone answers "is this bill attributed to that CI?", NOT "is this the
invoice for the goods?". The disambiguator is the SUPPLIER: the goods invoice is
raised on ``ci.supplier``, a carrier is a different party. Three code paths mean
"THE goods invoice" and cost real money if they pick a carrier's bill instead —
one of them CANCELS the invoice it picks. This module pins the supplier scope on
those three, and pins the deliberately-broad aggregation sites as broad, so a
later refactor cannot quietly swap one meaning for the other.

Frappe-free: these assert structural properties of the API source.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_ci_goods_invoice_scope -v
"""

from __future__ import annotations

import os
import re
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
IMPORTS = os.path.join(_ROOT, "api", "imports.py")
PURCHASING = os.path.join(_ROOT, "api", "purchasing.py")


def read(p):
	with open(p, encoding="utf-8") as fh:
		return fh.read()


def body(src, name):
	m = re.search(rf"^def {name}\(", src, re.M)
	assert m, f"{name} not found"
	tail = src[m.start() :]
	nxt = re.search(r"\n(?:@frappe\.whitelist\(\)|def |# ---)", tail[1:])
	return tail[: nxt.start() + 1] if nxt else tail


class ConvertPicksTheGoodsInvoiceTest(unittest.TestCase):
	"""convert_ci_to_purchase_invoice's idempotency check must not match a carrier."""

	def setUp(self):
		self.body = body(read(IMPORTS), "convert_ci_to_purchase_invoice")

	def test_duplicate_check_is_scoped_to_the_ci_supplier(self):
		# Without the supplier filter, a freight bill already attributed to the
		# CI satisfies the "already linked" test, the endpoint returns that
		# carrier's invoice as if it were the goods invoice, and the goods
		# payable is never opened — the supplier's A/P silently never exists.
		#
		# Asserted on the lookup REGION, not the whole function: ci.supplier is
		# also stamped on the invoice this endpoint creates further down, so a
		# bare assertIn would pass even with the filter unscoped.
		lookup = self.body[
			self.body.index("existing = frappe.db.get_value(") : self.body.index("if existing:")
		]
		self.assertIn('"custom_commercial_invoice": commercial_invoice', lookup)
		self.assertIn('"supplier": ci.supplier', lookup)

	def test_the_column_guard_survives(self):
		# custom_commercial_invoice does not exist on every site; narrowing the
		# lookup must not have cost the has_column guard that keeps the endpoint
		# working for tenants that never got the v46 patch.
		self.assertIn('frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice")', self.body)


class DriftComparesOnlyTheGoodsInvoiceTest(unittest.TestCase):
	"""_ci_invoice_drift decides which invoice rebook_ci_invoice cancels."""

	def setUp(self):
		self.src = read(IMPORTS)
		self.body = body(self.src, "_ci_invoice_drift")

	def test_the_ci_supplier_is_fetched(self):
		# The scope key has to come from the CI side; it rides on the existing
		# Commercial Invoice query rather than costing a query per invoice.
		self.assertRegex(self.body, r'fields=\[[^\]]*"agreed_total"[^\]]*"supplier"[^\]]*\]')

	def test_the_scope_filter_costs_no_query_of_its_own(self):
		# The batching guarantee covers this loop too: a drift report over a
		# whole book would otherwise fire one CI read per invoice. Sliced to the
		# filter loop alone, since the sibling test in
		# test_ci_invoice_drift_source.py guards the drift loop below it.
		start = self.body.index("for inv in invoices:")
		loop = self.body[start : self.body.index("invoices = kept", start)]
		self.assertNotIn("frappe.", loop)

	def test_an_invoice_from_another_supplier_is_not_compared(self):
		# A carrier's bill has nothing to do with agreed_total; measured against
		# it, it reads as drifting by its entire value. Report it and every
		# freight invoice in the book becomes a false "drifting" row.
		self.assertIn("ci_supplier_of", self.body)
		self.assertIn('if ci_supplier and inv.get("supplier") != ci_supplier:', self.body)
		self.assertIn("continue", self.body)

	def test_a_ci_without_a_supplier_is_still_reported(self):
		# The skip is conditional on the CI actually naming a supplier. A CI
		# with none is a different defect; dropping its rows would hide drift
		# this report exists to surface.
		self.assertIn("if ci_supplier and", self.body)

	def test_the_scope_still_reports_only_and_never_repairs(self):
		# Unchanged invariant, re-pinned here because the narrowing touched this
		# function: opening a screen must never cancel or post anything.
		for token in (".save(", ".insert(", ".submit(", ".cancel(", "db_set(", "db.set_value("):
			self.assertNotIn(token, self.body)

	def test_rebook_cancels_exactly_what_this_report_selected(self):
		# This is WHY the narrowing above is a money fix and not cosmetics:
		# rebook does no lookup of its own, it cancels the invoice named in the
		# drift row. An unscoped report hands it a transporter's invoice.
		rebook = body(self.src, "rebook_ci_invoice")
		self.assertIn("_ci_invoice_drift(company, commercial_invoice)", rebook)
		self.assertIn('old_name = row["purchase_invoice"]', rebook)
		self.assertIn("old.cancel()", rebook)


class VirtualExposureRetiresOnTheGoodsInvoiceTest(unittest.TestCase):
	"""supplier_import_exposure drops a CI from exposure once it is booked."""

	def setUp(self):
		self.body = body(read(PURCHASING), "supplier_import_exposure")

	def test_only_the_ci_suppliers_invoice_retires_the_commitment(self):
		# has_purchase_invoice means "the agreed_total now lives on a PInv".
		# Matched on the CI ref alone, a transporter's freight bill would retire
		# the CI's whole agreed_total from virtual exposure while the goods A/P
		# was never booked — the commitment vanishes from the supplier's page.
		exists = self.body[
			self.body.index("EXISTS(SELECT 1 FROM `tabPurchase Invoice` pi") : self.body.index(
				"AS has_purchase_invoice"
			)
		]
		self.assertIn("pi.custom_commercial_invoice = ci.name", exists)
		self.assertIn("pi.supplier = ci.supplier", exists)

	def test_sites_without_the_v46_column_still_answer(self):
		self.assertIn('frappe.db.has_column("Purchase Invoice", "custom_commercial_invoice")', self.body)
		self.assertIn('"0 AS has_purchase_invoice"', self.body)


class AttributionSitesStayBroadTest(unittest.TestCase):
	"""The other direction: sites that mean "every bill on this CI" must not narrow.

	These do not fail before the R0.1 change — they are the guard against
	over-applying it. Adding a supplier filter here would erase the carrier and
	service bills from the CI's cost picture, which is the whole reason those
	bills carry the ref.
	"""

	def setUp(self):
		self.src = read(IMPORTS)

	def test_related_import_bills_collects_every_attributed_bill(self):
		fn = body(self.src, "_related_import_bills")
		self.assertIn('match.append("pi.custom_commercial_invoice = %(ci)s")', fn)
		self.assertNotIn("pi.supplier =", fn)

	def test_the_ci_delete_blocker_sees_every_referencing_invoice(self):
		# A carrier's bill is a real reference: it must keep blocking deletion of
		# the CI it points at, or deleting the CI orphans it.
		fn = body(self.src, "_ci_reference_rows")
		self.assertIn('where.append("pi.custom_commercial_invoice = %(ci)s")', fn)
		self.assertNotIn("pi.supplier =", fn)


if __name__ == "__main__":
	unittest.main()
