"""The LCV reservation must be released when the voucher stops existing.

A Container Cost Line is stamped with ``lcv_ref`` the moment a Landed Cost
Voucher consumes it, and every later build skips it. That stamp is the only
thing standing between "this cost was already vouchered" and a double
capitalization — so the day a draft voucher is deleted or cancelled without the
stamp coming off, the money is stranded: no voucher carries it and no future
voucher will ever pick it up again. These tests are about that money coming
back, which is why they compare the rebuilt voucher's amounts against the first
one's instead of merely asserting a new name was returned.

The exchange rate is seeded deterministically. Without a stored Currency
Exchange row the resolver falls through to ERPNext's live fetch, which would
make this module depend on an outbound HTTP call — and, worse, would let the
test pass for the wrong reason on a machine that happens to have network.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.stabler.imports_module import lcv_math
from stabler.stabler.imports_module.hooks import _build_and_save_lcv, _collect_cost_lines

RELEASE_HANDLER = "stabler.stabler.imports_module.hooks.release_cost_lines_for_lcv"
CANCEL_HANDLER = "stabler.stabler.imports_module.hooks.allow_cancel_with_grn_link"
CANCEL_ENDPOINT = "stabler.api.lcv.cancel_landed_cost_voucher"

LINE_AMOUNT = 100.0
LINE_RATE = 12500.0


class TestLCVIntegration(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_value("Company", {}, "name")
		self.supplier = frappe.db.get_value("Supplier", {}, "name")
		if not all((self.company, self.supplier)):
			self.skipTest("Company and Supplier fixtures are required")

		self.company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		self.line_currency = "EUR" if self.company_currency == "USD" else "USD"
		if not frappe.db.exists("Currency", self.line_currency):
			self.skipTest(f"Currency {self.line_currency} is required")
		self._seed_exchange_rate()

		expense_account = frappe.db.get_value(
			"Account",
			{"company": self.company, "account_type": "Expenses Included In Valuation", "is_group": 0},
			"name",
		) or frappe.db.get_value(
			"Account",
			{"company": self.company, "root_type": "Expense", "is_group": 0},
			"name",
		)
		frappe.db.set_value("Stabler Settings", None, "imports_lcv_expense_account", expense_account)

		self.ci = frappe.new_doc("Commercial Invoice")
		self.ci.update(
			{
				"company": self.company,
				"supplier": self.supplier,
				"ci_number": frappe.generate_hash(length=10),
				"ci_date": frappe.utils.today(),
			}
		)
		self.ci.insert(ignore_permissions=True)

		self.container = frappe.new_doc("Import Container")
		self.container.update(
			{
				"company": self.company,
				"commercial_invoice": self.ci.name,
				"container_number": f"TEST-{frappe.generate_hash(length=6)}",
			}
		)
		self.container.append(
			"cost_lines",
			{
				"cost_component": "Freight",
				"currency": self.line_currency,
				"amount": LINE_AMOUNT,
				"include_in_landed_cost": 1,
			},
		)
		self.container.insert(ignore_permissions=True)

		self.grn = frappe.new_doc("GRN Checklist")
		self.grn.company = self.company
		self.grn.commercial_invoice = self.ci.name
		self.grn.insert(ignore_permissions=True)

		# The item has to be a STOCK item and the warehouse a leaf: ERPNext's
		# ``get_pr_items`` selects receipt rows on ``is_stock_item OR is_fixed_asset``,
		# so a service item yields a voucher with zero rows and the distribution then
		# dies on ``IndexError`` inside ERPNext — a fixture failure that reads like a
		# product bug. Measured on genesis-test.local: the first non-disabled Item is
		# "Import Service" (is_stock_item = 0), which is exactly what a plain
		# ``{"disabled": 0}`` lookup used to pick.
		item = frappe.db.get_value("Item", {"disabled": 0, "is_stock_item": 1}, "name")
		warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not (item and warehouse):
			self.skipTest("A stock Item and a leaf Warehouse are required")

		self.pr = frappe.new_doc("Purchase Receipt")
		self.pr.company = self.company
		self.pr.supplier = self.supplier
		self.pr.append("items", {"item_code": item, "qty": 1, "rate": 100, "warehouse": warehouse})
		self.pr.insert(ignore_permissions=True)

		self.truck = frappe.new_doc("Import Truck")
		self.truck.company = self.company
		self.truck.commercial_invoice = self.ci.name
		self.truck.insert(ignore_permissions=True)

		self.tr = frappe.new_doc("Truck Receipt")
		self.tr.company = self.company
		self.tr.truck = self.truck.name
		self.tr.grn_checklist = self.grn.name
		self.tr.purchase_receipt = self.pr.name
		self.tr.arrival_date = frappe.utils.today()
		self.tr.db_insert()
		self.tr.db_set("docstatus", 1)

		self.pr.db_set("docstatus", 1)

	def tearDown(self):
		frappe.db.rollback()

	# -- helpers ------------------------------------------------------------

	def _seed_exchange_rate(self):
		"""A stored rate for the build date, so nothing here touches the network."""
		on_date = frappe.utils.today()
		existing = frappe.db.get_value(
			"Currency Exchange",
			{"from_currency": self.line_currency, "to_currency": self.company_currency, "date": on_date},
			"name",
		)
		if existing:
			frappe.db.set_value("Currency Exchange", existing, "exchange_rate", LINE_RATE)
			return
		frappe.get_doc(
			{
				"doctype": "Currency Exchange",
				"date": on_date,
				"from_currency": self.line_currency,
				"to_currency": self.company_currency,
				"exchange_rate": LINE_RATE,
			}
		).insert(ignore_permissions=True)

	def _drop_exchange_rate(self):
		"""Make the rate genuinely unresolvable for the rest of this test.

		Deleting the stored row is only half of it: ``resolve_line_rates`` then falls
		through to ERPNext's ``get_exchange_rate``, which on a machine with network
		would answer — and the test would pass for the wrong reason, or fail on the
		day the provider is down. The fallback is stubbed to "no rate" so the
		condition under test is the one that actually holds.
		"""
		for name in frappe.get_all(
			"Currency Exchange",
			filters={"from_currency": self.line_currency, "to_currency": self.company_currency},
			pluck="name",
		):
			frappe.delete_doc("Currency Exchange", name, force=True, ignore_permissions=True)

		patcher = patch("erpnext.setup.utils.get_exchange_rate", return_value=0.0)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _stamps(self):
		"""Raw ``lcv_ref`` values straight off the child table.

		Deliberately NOT via ``_collect_cost_lines`` — that helper filters stamped
		rows out, so looping over its result to assert the stamp would iterate zero
		times and pass no matter which voucher name was written.
		"""
		return [
			row or ""
			for row in frappe.get_all(
				"Container Cost Line",
				filters={"parent": self.container.name},
				order_by="idx",
				pluck="lcv_ref",
			)
		]

	def _charges(self, lcv_name):
		"""``[(component, amount)]`` of a voucher — the money it actually carries."""
		doc = frappe.get_doc("Landed Cost Voucher", lcv_name)
		return sorted((row.description, round(row.amount, 2)) for row in doc.taxes)

	# -- tests --------------------------------------------------------------

	def test_deleted_lcv_releases_cost_lines_and_the_money_comes_back(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")
		self.assertTrue(lcv_name)

		# The seeded rate must be the one that landed: LINE_AMOUNT at LINE_RATE, not
		# the 1.0 that a missing-rate fallback would have produced.
		charges = self._charges(lcv_name)
		self.assertEqual(charges, [("Freight", round(LINE_AMOUNT * LINE_RATE, 2))])

		# 1. the consumed row carries THIS voucher's name
		self.assertEqual(self._stamps(), [lcv_name])

		# 2. and is therefore invisible to the next build
		self.assertEqual(_collect_cost_lines(self.ci.name), [])

		# 3. delete the draft voucher. No ``force``: the handler has to unlink the
		#    GRN row itself, otherwise frappe's link check refuses the delete — which
		#    is exactly the failure this test exists to catch.
		frappe.delete_doc("Landed Cost Voucher", lcv_name)
		self.assertFalse(frappe.db.exists("Landed Cost Voucher", lcv_name))

		self.assertEqual(self._stamps(), [""])
		self.grn.reload()
		self.assertEqual(len(self.grn.landed_cost_vouchers), 0)

		released = _collect_cost_lines(self.ci.name)
		self.assertEqual(len(lcv_math.unconsumed(released)), 1)
		self.assertEqual(released[0]["amount"], LINE_AMOUNT)

		# 4. the rebuild carries the same money — a name alone would prove nothing.
		#    Nor would a *different* name: deleting the last document of a series makes
		#    frappe roll the counter back (``revert_series_if_last``), so the rebuild
		#    legitimately reuses ``MAT-LCV-…-00001``. What proves the release is that
		#    the voucher exists again, carries the identical charges, and the released
		#    cost line is stamped with it.
		lcv_name_2 = _build_and_save_lcv(self.grn, note="second")
		self.assertTrue(lcv_name_2)
		self.assertTrue(frappe.db.exists("Landed Cost Voucher", lcv_name_2))
		self.assertEqual(self._charges(lcv_name_2), charges)
		self.assertEqual(self._stamps(), [lcv_name_2])

	def test_a_line_no_rate_could_value_is_never_stamped_as_vouchered(self):
		"""The stamp is permanent, so it may only mark money a voucher really carries.

		Without a rate ``aggregate_components`` drops the line and the voucher is
		built from whatever is left. If the build stamped it anyway, ``unconsumed``
		would skip it for the rest of time: the cost would vanish from valuation with
		nothing but a log line to say so. It has to stay pending until a rate exists.
		"""
		self._drop_exchange_rate()

		# A second, company-currency line so a voucher still gets created — the bug
		# is invisible when there is nothing to voucher and the build returns None.
		self.container.append(
			"cost_lines",
			{
				"cost_component": "Customs Clearance Fee",
				"currency": self.company_currency,
				"amount": 500_000,
				"include_in_landed_cost": 1,
			},
		)
		self.container.save(ignore_permissions=True)

		lcv_name = _build_and_save_lcv(self.grn, note="no rate")
		self.assertTrue(lcv_name)

		# Only the line it could value is on the voucher...
		self.assertEqual(self._charges(lcv_name), [("Customs Clearance Fee", 500_000.0)])
		# ...and only that line is stamped.
		self.assertEqual(self._stamps(), ["", lcv_name])

		# The unvalued cost is still pending, at its full amount, for the next build.
		pending = _collect_cost_lines(self.ci.name)
		self.assertEqual([(ln["cost_component"], ln["amount"]) for ln in pending], [("Freight", LINE_AMOUNT)])

		# And it lands the moment a rate exists — proving nothing was lost.
		self._seed_exchange_rate()
		lcv_name_2 = _build_and_save_lcv(self.grn, note="rate arrived")
		self.assertEqual(self._charges(lcv_name_2), [("Freight", round(LINE_AMOUNT * LINE_RATE, 2))])

	def test_cancelled_lcv_releases_cost_lines_but_keeps_grn_row(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")
		self.assertTrue(lcv_name)
		self.assertEqual(self._stamps(), [lcv_name])

		# The wiring is half the contract: a handler that works but is not registered
		# releases nothing in production.
		registered = frappe.get_hooks("doc_events").get("Landed Cost Voucher", {}).get("on_cancel", [])
		self.assertIn(RELEASE_HANDLER, registered)

		lcv = frappe.get_doc("Landed Cost Voucher", lcv_name)
		lcv.db_set("docstatus", 1)
		lcv.reload()

		# Dispatched through the registered path, so a typo in stabler/hooks.py fails
		# here. A full ``lcv.cancel()`` cannot run in this fixture: the Purchase
		# Receipt is submitted by ``db_set`` and has no stock ledger for ERPNext's own
		# ``on_cancel`` to repost.
		frappe.get_attr(RELEASE_HANDLER)(lcv, "on_cancel")

		self.assertEqual(self._stamps(), [""])

		# Cancel keeps the audit trail: the GRN still shows which voucher was tried.
		self.grn.reload()
		self.assertEqual(len(self.grn.landed_cost_vouchers), 1)

	def test_a_submitted_grn_lcv_ref_blocks_cancel_until_the_handler_runs(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")
		self.assertTrue(lcv_name)

		# Make GRN submitted so Frappe link checking finds it
		self.grn.db_set("docstatus", 1)
		# `db_set` writes only the parent row. In production `Document.set_docstatus`
		# (document.py:547) copies the docstatus onto every child row, and
		# `delete_doc.py:356` tests the CHILD row's docstatus — so without this the link
		# check finds nothing and the "prove it can fail" step would pass vacuously.
		frappe.db.set_value("GRN LCV Ref", {"parent": self.grn.name}, "docstatus", 1)

		# Assert CANCEL_HANDLER is registered under before_cancel
		registered_before = (
			frappe.get_hooks("doc_events").get("Landed Cost Voucher", {}).get("before_cancel", [])
		)
		self.assertIn(CANCEL_HANDLER, registered_before)

		lcv = frappe.get_doc("Landed Cost Voucher", lcv_name)
		lcv.db_set("docstatus", 1)
		lcv.reload()

		# Prove the link IS detected first without the fix, otherwise the test is a false green.
		# The reloaded lcv has no ignore_linked_doctypes yet, so this is the un-fixed state.
		from frappe.exceptions import LinkExistsError
		from frappe.model.delete_doc import check_if_doc_is_linked

		with self.assertRaises(LinkExistsError):
			check_if_doc_is_linked(lcv, method="Cancel")

		# With the hook enabled, the check should pass
		frappe.get_attr(CANCEL_HANDLER)(lcv, "before_cancel")
		check_if_doc_is_linked(lcv, method="Cancel")

	def test_the_handler_is_a_no_op_when_no_grn_lcv_ref_points_at_the_lcv(self):
		doc = frappe._dict({"name": "LCV-no-such-voucher"})
		frappe.get_attr(CANCEL_HANDLER)(doc, "before_cancel")
		self.assertIsNone(doc.get("ignore_linked_doctypes"))

	def test_the_handler_appends_to_ignore_linked_doctypes_instead_of_clobbering_it(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")
		doc = frappe._dict({"name": lcv_name, "ignore_linked_doctypes": ("Purchase Receipt",)})
		frappe.get_attr(CANCEL_HANDLER)(doc, "before_cancel")

		# Assert all three:
		# - "Purchase Receipt" is still present
		self.assertIn("Purchase Receipt", doc.ignore_linked_doctypes)
		# - "GRN Checklist" is present
		self.assertIn("GRN Checklist", doc.ignore_linked_doctypes)
		# - idempotent: calling a second time leaves exactly one "GRN Checklist"
		frappe.get_attr(CANCEL_HANDLER)(doc, "before_cancel")
		self.assertEqual(doc.ignore_linked_doctypes.count("GRN Checklist"), 1)

	def test_a_draft_voucher_cannot_be_cancelled_and_its_money_stays_reserved(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")

		with self.assertRaises(frappe.ValidationError):
			frappe.get_attr(CANCEL_ENDPOINT)(lcv_name)

		self.assertEqual(self._stamps(), [lcv_name])

	def test_an_already_cancelled_voucher_cannot_be_cancelled_twice(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")
		# Legitimate use of set_value here: setting up fixture state for a guard test
		# without needing a full production cancel lifecycle
		frappe.db.set_value("Landed Cost Voucher", lcv_name, "docstatus", 2)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_attr(CANCEL_ENDPOINT)(lcv_name)

	def test_an_unknown_voucher_name_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_attr(CANCEL_ENDPOINT)("LCV-does-not-exist")

	def test_a_user_without_cancel_permission_cannot_cancel_a_voucher(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")

		with self.assertRaises(frappe.PermissionError):
			frappe.get_attr(CANCEL_ENDPOINT)(lcv_name)

	def test_cancelling_through_the_endpoint_reverses_the_voucher_and_releases_the_money(self):
		lcv_name = _build_and_save_lcv(self.grn, note="initial")
		self.assertEqual(self._stamps(), [lcv_name])

		frappe.get_doc("Landed Cost Voucher", lcv_name).submit()

		res = frappe.get_attr(CANCEL_ENDPOINT)(lcv_name)
		self.assertEqual(res["docstatus"], 2)
		self.assertEqual(res["name"], lcv_name)

		lcv = frappe.get_doc("Landed Cost Voucher", lcv_name)
		self.assertEqual(lcv.docstatus, 2)

		self.assertEqual(self._stamps(), [""])
		self.assertTrue(frappe.db.exists("GRN LCV Ref", {"lcv": lcv_name}))

	def test_the_release_handler_is_wired_to_the_cancel_lifecycle(self):
		registered = frappe.get_hooks("doc_events").get("Landed Cost Voucher", {}).get("on_cancel", [])
		self.assertIn(RELEASE_HANDLER, registered)
