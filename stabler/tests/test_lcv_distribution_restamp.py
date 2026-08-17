"""The basis the operator picks has to reach the voucher Submit posts.

The choice is stored on the source document; the voucher stores its own copy,
written once when it was built. On the imports route those two are written at
different times by different actors: `grn_on_submit` enqueues the draft in a
background job before any human opens the review screen, so the draft already
exists — stamped with the default basis — by the time the operator chooses one.

Nothing reconciled them. `set_distribution_method` wrote the source document and
`submit_landed_cost_voucher` posted the draft as it stood, so the screen could
report "By weight (kg)" while ERPNext capitalized the freight by value. Freight
spread by amount instead of quantity is wrong for every item whose value-per-kg
differs from the average, and there is no error, no warning, and nothing on
either document afterwards that says the two disagreed.

So these tests encode the two halves of the repair:

  while the basis is still changeable, choosing one re-stamps the drafts and
  makes ERPNext redistribute — the save is the point, not the label;

  once a submitted voucher has frozen it, a draft that disagrees is refused
  rather than quietly corrected. Rewriting a voucher at submit time would post
  numbers the accountant never saw, which is the same defect facing the other way.

Bench-free. `lcv_math` is imported for real — the normalization these decisions
turn on is the shipping one, not a stand-in.
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.lcv"

_SANDBOX = ModuleSandbox()


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


class _Voucher:
	"""A Landed Cost Voucher whose save() is observable."""

	def __init__(self, db, name, method, docstatus=0, receipts=("PR-1",)):
		self.db = db
		self.name = name
		self.distribute_charges_based_on = method
		self.docstatus = docstatus
		self.purchase_receipts = [
			types.SimpleNamespace(receipt_document_type="Purchase Receipt", receipt_document=pr)
			for pr in receipts
		]

	def get(self, field, default=None):
		return getattr(self, field, default)

	def save(self):
		# ERPNext redistributes here: LandedCostVoucher.validate calls
		# set_applicable_charges_on_item, which reads distribute_charges_based_on.
		self.db.saves.append((self.name, self.distribute_charges_based_on))

	def submit(self):
		self.docstatus = 1
		self.db.submits.append((self.name, self.distribute_charges_based_on))


class _FakeDB:
	def __init__(self):
		self.vouchers: dict[str, _Voucher] = {}
		self.persisted: dict[tuple, str] = {}
		self.saves: list[tuple] = []
		self.submits: list[tuple] = []
		self.docstatus_queries: list[int] = []

	def add(self, name, method, docstatus=0, receipts=("PR-1",)):
		self.vouchers[name] = _Voucher(self, name, method, docstatus, receipts)
		return self.vouchers[name]

	# --- frappe.db surface -------------------------------------------------- #
	def sql(self, _query, params=(), as_dict=False):
		docstatus = params[-1]
		self.docstatus_queries.append(docstatus)
		wanted = set(params[:-1])
		return [
			{"lcv": v.name, "method": v.distribute_charges_based_on}
			for v in self.vouchers.values()
			if v.docstatus == docstatus and wanted & {row.receipt_document for row in v.purchase_receipts}
		]

	def has_column(self, _doctype, _field):
		return True

	def exists(self, doctype, name):
		if doctype == "Landed Cost Voucher":
			return name in self.vouchers
		return True

	def get_value(self, _doctype, name, _field=None, **_kwargs):
		return self.persisted.get((_doctype, name))

	def set_value(self, doctype, name, _field, value):
		self.persisted[(doctype, name)] = value


def _load(db: _FakeDB, review=None):
	_SANDBOX.evict(_MODULE, "frappe", "frappe.utils", "stabler.api._common", "stabler.api.imports")

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.db = db
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn
	frappe.get_doc = lambda doctype, name: db.vouchers[name]
	frappe.get_cached_value = lambda _dt, _name, _field: "Test Co"

	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value=0: int(value or 0)
	utils.flt = lambda value=0, precision=None: float(value or 0)
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_a, **_k: None
	common._assert_can_write = lambda *_a, **_k: None

	imports = types.ModuleType("stabler.api.imports")
	imports._assert_cost_visible = lambda *_a, **_k: None
	imports._latest_exchange_rate = lambda *_a, **_k: 1.0
	imports.get_landed_cost_review = lambda _name: review or {"purchase_receipts": [{"name": "PR-1"}]}

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.imports": imports,
		}
	)
	return importlib.import_module(_MODULE)


class RestampOnChoiceTest(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.api = _load(self.db)

	def test_choosing_a_basis_restamps_the_draft_the_operator_will_submit(self):
		"""The bead's exact path: the draft predates the choice and must follow it."""
		draft = self.db.add("LCV-0001", "Amount")

		state = self.api.set_distribution_method("Purchase Receipt", "PR-1", "Qty")

		self.assertEqual(draft.distribute_charges_based_on, "Qty")
		self.assertEqual(state["method"], "Qty")
		self.assertEqual(state["restamped"], ["LCV-0001"])

	def test_restamping_saves_so_erpnext_redistributes(self):
		"""Setting the field without saving would relabel the voucher, not re-spread it.

		ERPNext recomputes applicable charges in LandedCostVoucher.validate, which
		only runs on save. A re-stamp that skipped it would leave the old per-item
		amounts under a new basis label — worse than the defect it replaces,
		because now the voucher itself lies.
		"""
		self.db.add("LCV-0001", "Amount")

		self.api.set_distribution_method("Purchase Receipt", "PR-1", "Qty")

		self.assertEqual(self.db.saves, [("LCV-0001", "Qty")])

	def test_a_draft_already_on_the_chosen_basis_is_left_alone(self):
		"""A needless save reposts valuation for nothing."""
		self.db.add("LCV-0001", "Qty")

		self.api.set_distribution_method("Purchase Receipt", "PR-1", "Qty")

		self.assertEqual(self.db.saves, [])

	def test_only_drafts_are_restamped(self):
		"""A submitted voucher has capitalized already; re-stamping it is not a fix."""
		self.db.add("LCV-DRAFT", "Amount", docstatus=0)
		self.db.add("LCV-DONE", "Amount", docstatus=1)

		with self.assertRaises(_Thrown):
			# The submitted voucher freezes the basis, so the choice is refused
			# outright — the re-stamp never runs and never sees LCV-DONE.
			self.api.set_distribution_method("Purchase Receipt", "PR-1", "Qty")

		self.assertEqual(self.db.saves, [])

	def test_the_grn_route_restamps_the_background_built_draft(self):
		"""On the imports route the draft exists before any human opens the screen."""
		draft = self.db.add("LCV-0001", "Amount")

		self.api.set_distribution_method("GRN Checklist", "GRN-0001", "Qty")

		self.assertEqual(draft.distribute_charges_based_on, "Qty")
		self.assertEqual(self.db.saves, [("LCV-0001", "Qty")])

	def test_a_voucher_on_other_receipts_is_not_touched(self):
		self.db.add("LCV-MINE", "Amount", receipts=("PR-1",))
		other = self.db.add("LCV-OTHER", "Amount", receipts=("PR-9",))

		self.api.set_distribution_method("Purchase Receipt", "PR-1", "Qty")

		self.assertEqual(other.distribute_charges_based_on, "Amount")
		self.assertEqual(self.db.saves, [("LCV-MINE", "Qty")])


class SubmitGuardTest(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.api = _load(self.db)

	def test_submit_refuses_a_draft_that_disagrees_with_a_frozen_basis(self):
		"""set_distribution_method cannot reach a draft that predates the freeze.

		Once a voucher is submitted the choice is refused, so the re-stamp never
		runs. A draft built before that on a different basis is the case only this
		guard catches, and posting it would net later customs charges against
		amounts capitalized on a distribution they do not match.
		"""
		self.db.add("LCV-DONE", "Amount", docstatus=1)
		self.db.add("LCV-DRAFT", "Qty", docstatus=0)

		with self.assertRaises(_Thrown) as caught:
			self.api.submit_landed_cost_voucher("LCV-DRAFT")

		message = str(caught.exception)
		self.assertIn("LCV-DONE", message)
		self.assertEqual(self.db.submits, [])

	def test_submit_proceeds_when_the_frozen_basis_agrees(self):
		self.db.add("LCV-DONE", "Amount", docstatus=1)
		self.db.add("LCV-DRAFT", "Amount", docstatus=0)

		result = self.api.submit_landed_cost_voucher("LCV-DRAFT")

		self.assertEqual(result["docstatus"], 1)
		self.assertEqual(result["distribute_charges_based_on"], "Amount")
		self.assertEqual(self.db.submits, [("LCV-DRAFT", "Amount")])

	def test_submit_proceeds_when_nothing_is_frozen(self):
		self.db.add("LCV-DRAFT", "Qty", docstatus=0)

		self.api.submit_landed_cost_voucher("LCV-DRAFT")

		self.assertEqual(self.db.submits, [("LCV-DRAFT", "Qty")])

	def test_an_already_submitted_voucher_is_still_refused(self):
		self.db.add("LCV-DONE", "Qty", docstatus=1)

		with self.assertRaises(_Thrown):
			self.api.submit_landed_cost_voucher("LCV-DONE")


if __name__ == "__main__":
	unittest.main()
