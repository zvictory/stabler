"""G.17 — a document must show the upstream document it was CREATED FROM.

Three UAT screens reported the same symptom: the "Related documents" panel
(`RelatedDocuments.vue`, fed by `stabler.api.sales.get_linked_documents`) drew
an empty "—" even though the link plainly existed.

  * Purchase Receipt drawer — created from a Purchase Order; PO missing.
  * Purchase Invoice detail — created from a Purchase Receipt (+ its Purchase
    Order); both missing.
  * Sales Invoice detail — created from a Sales Order; SO missing.

Root cause, confirmed against the local site before writing this test:

    bench --site stabler execute stabler.api.sales.get_linked_documents \\
        --kwargs '{"doctype": "Purchase Receipt", "name": "MAT-PRE-2026-00005"}'
    -> {"Purchase Invoice": [{"name": "ACC-PINV-2026-00883", "docstatus": 1}]}

MAT-PRE-2026-00005's own item row carries `purchase_order = PUR-ORD-2026-00009`
(confirmed by SELECT), yet the endpoint never mentions it. `get_linked_documents`
delegates to Frappe's `frappe.desk.form.linked_with` walker, which only ever
answers "which documents point AT the subject" — the direction that finds the
Purchase Invoice raised against this receipt. It cannot walk the opposite way:
a document's OWN "created from" link lives on its own item rows (Purchase
Receipt Item.purchase_order, Purchase Invoice Item.purchase_order/
.purchase_receipt, Sales Invoice Item.sales_order), which the generic walker
never reads at all.

`_add_upstream_item_links` is the fix, tested here directly rather than through
`get_linked_documents` itself: that function does
`from frappe.desk.form.linked_with import get_linked_docs, get_linked_doctypes`
as a LOCAL import, which needs a real installed Frappe package tree (the fake
`frappe` module below has no `__path__`, so it cannot be a parent package for
`frappe.desk...`). `_add_upstream_item_links` is called AFTER that walk, on the
`out` dict the walk already built, and never touches the desk module itself —
so it is the one piece of `get_linked_documents` a frappe-free test can drive
directly. End-to-end proof that `get_linked_documents` actually calls it, on a
real site, belongs in `test_related_documents_integration.py` (bench-only).

    PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_related_documents_upstream_links -v
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


def _load_sales():
	"""Import `stabler.api.sales` against a minimal hand-built `frappe`.

	`stabler.api.sales` is a large module with a wide import surface; this fakes
	exactly the names it imports at module load time (verified against the file's
	own `from ... import ...` lines) and nothing more.
	"""
	_SANDBOX.evict(
		"stabler.api.sales",
		"stabler.api._common",
		"stabler.api._money",
		"stabler.api._pricing",
		"stabler.api._sales_margin",
		"stabler.api.approvals",
		"stabler.api.organization",
		"stabler.api.tender_dimension",
		"stabler.stabler.customer_hierarchy",
		"frappe",
		"frappe.utils",
	)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.whitelist = lambda *args, **_kwargs: (lambda fn: fn) if args == () else args[0]

	class _ValidationError(Exception):
		pass

	frappe.ValidationError = _ValidationError
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})

	def _throw(message, exc=None, *args, **kwargs):
		raise (exc or _ValidationError)(str(message))

	frappe.throw = _throw
	frappe.session = types.SimpleNamespace(user="tester@example.com")
	frappe.get_roles = lambda _user=None: []
	# Overridden per test via monkeypatching the returned module's `frappe`
	# attribute — these defaults must never be reached by a test that forgot to.
	frappe.get_all = lambda *a, **k: (_ for _ in ()).throw(AssertionError("frappe.get_all not stubbed"))
	frappe.has_permission = lambda *a, **k: (_ for _ in ()).throw(
		AssertionError("frappe.has_permission not stubbed")
	)
	frappe.db = types.SimpleNamespace(
		exists=lambda *a, **k: True,
		get_value=lambda *a, **k: (_ for _ in ()).throw(AssertionError("frappe.db.get_value not stubbed")),
		has_column=lambda *a, **k: True,
		sql=lambda *a, **k: [],
	)
	frappe.get_cached_value = lambda *a, **k: None

	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value=0: int(float(value or 0))
	utils.flt = lambda value=0, precision=None: float(value or 0)
	utils.getdate = lambda value=None: value
	utils.today = lambda: "2026-09-05"
	frappe.utils = utils

	_SANDBOX.install({"frappe": frappe, "frappe.utils": utils})

	common = types.ModuleType("stabler.api._common")
	common.BOX_FIELDS = ("custom_boxes", "custom_box_kg")
	common._assert_box_columns = lambda *a, **k: None
	common._assert_can_read = lambda *a, **k: None
	common._assert_can_write = lambda *a, **k: None
	common._require_company = lambda company: company
	common._validate_money_overrides = lambda *a, **k: None
	common.check_concurrency = lambda *a, **k: None

	money = types.ModuleType("stabler.api._money")
	money.money_epsilon = lambda *a, **k: 0.005

	pricing = types.ModuleType("stabler.api._pricing")
	pricing.gross_rate = lambda *a, **k: 0
	pricing.net_rate = lambda *a, **k: 0

	sales_margin = types.ModuleType("stabler.api._sales_margin")
	sales_margin.attach_margins = lambda *a, **k: None

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda _company: None

	organization = types.ModuleType("stabler.api.organization")
	organization.module_map_for = lambda _company: {}

	tender_dimension = types.ModuleType("stabler.api.tender_dimension")
	tender_dimension.dimension_fieldname = lambda: "tender"

	customer_hierarchy = types.ModuleType("stabler.stabler.customer_hierarchy")
	for _err in (
		"ERR_ALLOC_EMPTY",
		"ERR_ALLOC_EXCEEDS",
		"ERR_ALLOC_NONPOSITIVE",
		"ERR_ALLOC_UNKNOWN_INVOICE",
		"ERR_XFER_EMPTY",
		"ERR_XFER_EXCEEDS",
		"ERR_XFER_NONPOSITIVE",
		"ERR_XFER_UNKNOWN_CHILD",
	):
		setattr(customer_hierarchy, _err, _err)
	customer_hierarchy.children_balance_map = lambda *a, **k: {}
	customer_hierarchy.cumulative_balance = lambda *a, **k: 0
	customer_hierarchy.group_allocations_by_party = lambda *a, **k: {}
	customer_hierarchy.validate_bulk_allocations = lambda *a, **k: None
	customer_hierarchy.validate_transfers = lambda *a, **k: None

	_SANDBOX.install(
		{
			"stabler.api._common": common,
			"stabler.api._money": money,
			"stabler.api._pricing": pricing,
			"stabler.api._sales_margin": sales_margin,
			"stabler.api.approvals": approvals,
			"stabler.api.organization": organization,
			"stabler.api.tender_dimension": tender_dimension,
			"stabler.stabler.customer_hierarchy": customer_hierarchy,
		}
	)
	return importlib.import_module("stabler.api.sales")


class _Row(dict):
	"""Frappe rows answer both `row["x"]` and `row.get("x")`; a plain dict already
	does — this only exists so call sites reading `row.x` (attribute style, as
	`frappe.get_all`'s rows without `as_dict` quirks sometimes are) also work."""

	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError as exc:
			raise AttributeError(key) from exc


class UpstreamItemLinksTest(unittest.TestCase):
	"""`_add_upstream_item_links` — the "created from" half `get_linked_documents`
	was missing. Every fixture mirrors real rows read off the local site."""

	def test_purchase_receipt_shows_the_purchase_order_it_was_made_from(self):
		# Real shape, read-only probed 2026-09-05: MAT-PRE-2026-00005's own item
		# carries purchase_order = PUR-ORD-2026-00009, and the endpoint's answer
		# before this fix was {"Purchase Invoice": [...]} — the PO never appeared.
		sales = _load_sales()

		def get_all(doctype, filters=None, fields=None, **_kwargs):
			self.assertEqual(doctype, "Purchase Receipt Item")
			self.assertEqual(filters, {"parent": "MAT-PRE-2026-00005", "parenttype": "Purchase Receipt"})
			self.assertEqual(fields, ["purchase_order"])
			return [_Row(purchase_order="PUR-ORD-2026-00009")]

		sales.frappe.get_all = get_all
		sales.frappe.has_permission = lambda *a, **k: True
		sales.frappe.db.get_value = lambda dt, name, field: 1

		out = {"Purchase Invoice": [{"name": "ACC-PINV-2026-00883", "docstatus": 1}]}
		sales._add_upstream_item_links("Purchase Receipt", "MAT-PRE-2026-00005", out)

		self.assertEqual(out["Purchase Order"], [{"name": "PUR-ORD-2026-00009", "docstatus": 1}])
		# The walker's own result (the downstream Purchase Invoice) must survive
		# untouched — this function only ADDS the upstream side.
		self.assertEqual(out["Purchase Invoice"], [{"name": "ACC-PINV-2026-00883", "docstatus": 1}])

	def test_purchase_invoice_shows_both_the_order_and_the_receipt_it_came_from(self):
		# Real shape: ACC-PINV-2026-00883's item carries BOTH purchase_order and
		# purchase_receipt — a bill created straight through the PO-to-PR-to-PI
		# chain must show both upstream documents, not just one.
		sales = _load_sales()

		def get_all(doctype, filters=None, fields=None, **_kwargs):
			self.assertEqual(doctype, "Purchase Invoice Item")
			self.assertEqual(sorted(fields), ["purchase_order", "purchase_receipt"])
			return [_Row(purchase_order="PUR-ORD-2026-00009", purchase_receipt="MAT-PRE-2026-00005")]

		sales.frappe.get_all = get_all
		sales.frappe.has_permission = lambda *a, **k: True
		sales.frappe.db.get_value = lambda dt, name, field: 1

		out = {}
		sales._add_upstream_item_links("Purchase Invoice", "ACC-PINV-2026-00883", out)

		self.assertEqual(out["Purchase Order"], [{"name": "PUR-ORD-2026-00009", "docstatus": 1}])
		self.assertEqual(out["Purchase Receipt"], [{"name": "MAT-PRE-2026-00005", "docstatus": 1}])

	def test_sales_invoice_shows_the_sales_order_it_was_made_from(self):
		# Real shape: ACC-SINV-2026-07435's item carries sales_order =
		# SAL-ORD-2026-05895 (the UAT report's own example).
		sales = _load_sales()

		def get_all(doctype, filters=None, fields=None, **_kwargs):
			self.assertEqual(doctype, "Sales Invoice Item")
			return [_Row(sales_order="SAL-ORD-2026-05895")]

		sales.frappe.get_all = get_all
		sales.frappe.has_permission = lambda *a, **k: True
		sales.frappe.db.get_value = lambda dt, name, field: 1

		out = {}
		sales._add_upstream_item_links("Sales Invoice", "ACC-SINV-2026-07435", out)

		self.assertEqual(out["Sales Order"], [{"name": "SAL-ORD-2026-05895", "docstatus": 1}])

	def test_a_doctype_outside_the_map_is_a_pure_no_op(self):
		# Payment Entry has its own upstream mechanism (_add_payment_entry_references);
		# it must not gain a second, unrelated "Payment Entry Item" query.
		sales = _load_sales()
		sales.frappe.get_all = lambda *a, **k: (_ for _ in ()).throw(
			AssertionError("must not query anything for a doctype with no upstream links")
		)

		out = {"Sales Invoice": [{"name": "SINV-1", "docstatus": 1}]}
		sales._add_upstream_item_links("Payment Entry", "PE-1", out)

		self.assertEqual(out, {"Sales Invoice": [{"name": "SINV-1", "docstatus": 1}]})

	def test_an_unreadable_upstream_document_is_not_leaked(self):
		# Same discipline as _add_payment_entry_references's own leak test: proving
		# read access to the subject says nothing about the upstream document.
		sales = _load_sales()
		sales.frappe.get_all = lambda *a, **k: [_Row(purchase_order="PUR-ORD-SECRET")]
		sales.frappe.has_permission = lambda *a, **k: False
		sales.frappe.db.get_value = lambda dt, name, field: 1

		out = {}
		sales._add_upstream_item_links("Purchase Receipt", "MAT-PRE-2026-00005", out)

		self.assertNotIn("Purchase Order", out)

	def test_two_lines_naming_the_same_order_produce_one_entry_not_two(self):
		sales = _load_sales()
		sales.frappe.get_all = lambda *a, **k: [
			_Row(purchase_order="PUR-ORD-2026-00008"),
			_Row(purchase_order="PUR-ORD-2026-00008"),
		]
		sales.frappe.has_permission = lambda *a, **k: True
		sales.frappe.db.get_value = lambda dt, name, field: 0

		out = {}
		sales._add_upstream_item_links("Purchase Receipt", "MAT-PRE-2026-00004", out)

		self.assertEqual(out["Purchase Order"], [{"name": "PUR-ORD-2026-00008", "docstatus": 0}])

	def test_an_order_the_walker_already_found_is_not_duplicated(self):
		# Defensive: if the upstream doc is somehow already in `out` (e.g. a future
		# doctype where Frappe's own walker AND this function could both find the
		# same name), the existing entry wins rather than growing a duplicate row.
		sales = _load_sales()
		sales.frappe.get_all = lambda *a, **k: [_Row(purchase_order="PUR-ORD-2026-00009")]
		sales.frappe.has_permission = lambda *a, **k: (_ for _ in ()).throw(
			AssertionError("an already-listed reference must not be permission-checked again")
		)

		out = {"Purchase Order": [{"name": "PUR-ORD-2026-00009", "docstatus": 1}]}
		sales._add_upstream_item_links("Purchase Receipt", "MAT-PRE-2026-00005", out)

		self.assertEqual(out["Purchase Order"], [{"name": "PUR-ORD-2026-00009", "docstatus": 1}])

	def test_no_item_rows_issues_no_further_queries(self):
		sales = _load_sales()
		sales.frappe.get_all = lambda *a, **k: []
		sales.frappe.has_permission = lambda *a, **k: (_ for _ in ()).throw(
			AssertionError("nothing to check permission for when there are no item rows")
		)

		out = {}
		sales._add_upstream_item_links("Sales Invoice", "SINV-EMPTY", out)

		self.assertEqual(out, {})


class DealDisplayLabelTest(unittest.TestCase):
	"""G.18 (Sales Invoice side) — `_deal_display_label`'s fallback chain.

	Contract: "<organization or lead_name> · <deal name>". Deliberately NOT
	`tender_dimension.tender_label()` (organization only, no lead_name fallback,
	no deal name suffix) — that helper stays exactly as PurchaseInvoiceForm.vue
	already renders it; this is a separate, richer label for the two screens
	that had no tender display at all.
	"""

	def test_uses_the_organization_when_present(self):
		# Real shape, read-only probed 2026-09-05: CRM-DEAL-2026-00015's
		# organization is "O'zbekiston temir yo'llari AJ [DEMO]". `lead_name` is
		# set here too (a CRM Deal can carry both) so this proves organization is
		# tried FIRST, not merely that it works when lead_name is absent.
		sales = _load_sales()
		sales.frappe.db.get_value = lambda dt, name, fields, as_dict=False: {
			"organization": "O'zbekiston temir yo'llari AJ [DEMO]",
			"lead_name": "Someone Else",
		}

		label = sales._deal_display_label("CRM-DEAL-2026-00015")

		self.assertEqual(label, "O'zbekiston temir yo'llari AJ [DEMO] · CRM-DEAL-2026-00015")

	def test_falls_back_to_lead_name_when_organization_is_blank(self):
		# A lead-only CRM Deal (no company yet) must still name something instead
		# of rendering "· CRM-DEAL-...", which tender_label()'s own fallback
		# (organization or the bare deal id) would do.
		sales = _load_sales()
		sales.frappe.db.get_value = lambda dt, name, fields, as_dict=False: {
			"organization": None,
			"lead_name": "Aziz Karimov",
		}

		label = sales._deal_display_label("CRM-DEAL-2026-00099")

		self.assertEqual(label, "Aziz Karimov · CRM-DEAL-2026-00099")

	def test_falls_back_to_the_deal_id_when_neither_name_is_set(self):
		sales = _load_sales()
		sales.frappe.db.get_value = lambda dt, name, fields, as_dict=False: {}

		label = sales._deal_display_label("CRM-DEAL-2026-00100")

		self.assertEqual(label, "CRM-DEAL-2026-00100 · CRM-DEAL-2026-00100")

	def test_no_deal_is_the_empty_string_not_a_bare_separator(self):
		sales = _load_sales()
		sales.frappe.db.get_value = lambda *a, **k: (_ for _ in ()).throw(
			AssertionError("an empty deal must short-circuit before any lookup")
		)

		self.assertEqual(sales._deal_display_label(""), "")


class RegistrationTest(unittest.TestCase):
	def test_the_module_is_in_the_frappe_free_list(self):
		import pathlib

		root = pathlib.Path(__file__).resolve().parents[2]
		listed = (root / ".github" / "frappe-free-tests.txt").read_text().split()

		self.assertTrue(
			"stabler.tests.test_related_documents_upstream_links" in listed,
			"module missing from .github/frappe-free-tests.txt — `make check` would not run it",
		)


if __name__ == "__main__":
	unittest.main()
