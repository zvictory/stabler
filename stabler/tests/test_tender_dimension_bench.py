"""ADR-609's tender dimension against a live ledger.

`test_tender_dimension` proves every RULE without a bench: which deals may be
selected, what `stamp_tender` copies, what `default_gl_tender` fills in. What a
stubbed frappe cannot show is the only thing the feature is actually for —
whether the value reaches the GENERAL LEDGER, and whether the amounts on either
side of it stayed identical:

  * a `Custom Field` is not a column until `create_custom_fields` has run, and
    `get_gl_dict` copies `self.get(fieldname)` onto a GL row only when the field
    EXISTS on GL Entry. The frappe-free suite asserts the patch asks for the
    fields; only a live database can say they landed;
  * `Accounting Dimension Detail.mandatory_for_pl` is enforced by ERPNext's
    `validate_dimensions_for_pl_and_bs`, not by any stabler code. Turning it on
    is a promise that no P&L posting can be made without a tender — a promise
    that is either true of this site's ledger or it is not, and the stub cannot
    tell us which;
  * `default_gl_tender` runs as a `before_validate` doc event on GL Entry. That
    GL rows are inserted one document at a time (`general_ledger.make_entry`) is
    what makes the hook fire at all; a rewrite that batches them would silently
    stop calling it and every frappe-free test would stay green;
  * the money invariant. `TestPlainCompany` posts the SAME expense on a company
    with the module off and compares its ledger rows against the tender
    company's, account role by account role and figure by figure. If P5a ever
    moves an amount, a currency or an account, that comparison is where it shows.

    cd /path/to/frappe-bench && bench --site <site> run-tests \\
        --module stabler.tests.test_tender_dimension_bench

NOT in `.github/frappe-free-tests.txt` on purpose: it needs a live bench, so it
runs under `make test-bench`, never under `make check`.

Every fixture is registered for cleanup the moment it is created, GL rows
included: this site has `Accounts Settings.delete_linked_ledger_entries = 0`, so
deleting a voucher leaves its ledger rows behind, and a company cannot be removed
while any GL row still names it (`Company.on_trash` keeps the accounts of a
company that has ledger history).
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, today

try:
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # newer frappe
	from frappe.tests import IntegrationTestCase as FrappeTestCase

from stabler.api.crm import list_deals
from stabler.api.money import amend_expense_entry, submit_expense_entry
from stabler.api.purchasing import (
	create_purchase_invoice,
	create_purchase_invoice_from_po,
	purchase_invoice_detail,
)
from stabler.api.tender_dimension import (
	DIMENSION_DOCTYPE,
	OVERHEAD_ORGANIZATION,
	clear_dimension_cache,
	dimension_fieldname,
	ensure_company_setup,
	is_active_tender,
	overhead_deal,
	tender_enabled,
)
from stabler.stabler.doctype.stabler_settings.stabler_settings import module_map_for

#: The six doctypes the patch asserts the field landed on (contract B2/acceptance 1).
_REQUIRED_ON = (
	"GL Entry",
	"Journal Entry Account",
	"Sales Invoice",
	"Purchase Invoice",
	"Sales Order",
	"Purchase Order",
)


#: The throwaway company `TestPlainCompany` builds and removes. Named, not
#: inlined, so the leftover-cleanup and the insert can never drift apart.
_PLAIN_COMPANY = "_ADR609 Plain Co"


def _tender_company() -> str | None:
	"""A company with the tender module on — found by FLAG, never by name."""
	for row in frappe.get_all("Stabler Company Modules", fields=["name", "company"], limit=50):
		if frappe.db.get_value("Stabler Company Modules", row["name"], "enable_tender"):
			return row["company"]
	return None


def _an_account(company: str, **filters) -> str | None:
	filters.update({"company": company, "is_group": 0, "disabled": 0})
	return frappe.db.get_value("Account", filters, "name")


def _plain_expense_account(company: str) -> str | None:
	"""An expense account with no special ERPNext role, in the company's currency.

	`account_type` is deliberately empty: "Cost of Goods Sold", "Stock Adjustment"
	and friends are wired into other controllers, and a JE line on one of them
	measures those controllers rather than this hook.

	The currency filter is not decoration: this site's chart carries a USD expense
	account, and `submit_expense_entry` refuses a line whose account currency
	differs from the payment account's ("Cross-currency expense lines are not yet
	supported") — the fixture would have measured that refusal instead of the tender.
	"""
	return _an_account(
		company,
		root_type="Expense",
		account_type="",
		account_currency=frappe.db.get_value("Company", company, "default_currency"),
	)


def _gl_rows(voucher_type: str, voucher_no: str, fieldname: str) -> list[dict]:
	fields = ["account", "debit", "credit", "account_currency", "cost_center", "is_cancelled", fieldname]
	return frappe.get_all(
		"GL Entry",
		filters={"voucher_type": voucher_type, "voucher_no": voucher_no, "is_cancelled": 0},
		fields=fields,
		order_by="account asc",
		limit_page_length=0,
	)


def _dimension_name() -> str | None:
	return frappe.db.get_value("Accounting Dimension", {"document_type": DIMENSION_DOCTYPE}, "name")


def _report_type(account: str) -> str:
	return frappe.get_cached_value("Account", account, "report_type") or ""


class _Fixture(FrappeTestCase):
	"""The tender company, its overhead deal, and two deals to select between."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# The ONE commit this suite makes, and the last thing it does. Registered
		# before any fixture, so LIFO runs it after every per-test cleanup and
		# after every class-level erasure — and before frappe's own `_rollback_db`,
		# which `super().setUpClass()` registered first and LIFO therefore runs
		# last. It is needed because creating a Company commits from inside
		# ERPNext's chart of accounts: the row is durable, so the rollback would
		# undo the DELETE and leave the company standing. Measured: the second run
		# of this module died on "Duplicate entry '_ADR609 Plain Co'".
		#
		# Nothing else here may commit. A commit inside a per-test cleanup would
		# persist whatever that test still had pending — see `_erase_voucher`.
		cls.addClassCleanup(frappe.db.commit)
		frappe.set_user("Administrator")
		clear_dimension_cache()
		cls.company = _tender_company()
		cls.fieldname = dimension_fieldname()
		cls.overhead = overhead_deal(cls.company) if cls.company else None
		cls.currency = (
			frappe.db.get_value("Company", cls.company, "default_currency") if cls.company else None
		)
		cls.cash = (
			_an_account(cls.company, account_type="Cash", account_currency=cls.currency)
			if cls.company
			else None
		)
		cls.expense = _plain_expense_account(cls.company) if cls.company else None
		cls.ready = bool(cls.company and cls.fieldname and cls.overhead and cls.cash and cls.expense)
		if not cls.ready:
			return
		cls.master = cls._make_master()
		cls.tender = cls._make_deal("Tender")
		cls.lost = cls._make_deal("Tender", stage="lost")

	@classmethod
	def _track(cls, doctype: str, name: str) -> str:
		cls.addClassCleanup(frappe.delete_doc, doctype, name, force=True, ignore_permissions=True)
		return name

	@classmethod
	def _make_master(cls) -> str:
		"""The parent every tender lot must have.

		`tender_master.validate_deal_parent_tender` refuses a NEW `deal_type
		Tender` deal with no `custom_parent_tender` on a tender company — measured:
		without this every class here died in `setUpClass` with "A tender lot must
		belong to a Parent Tender." So a tender fixture is a two-document fixture,
		and a test that skipped the master would be testing a shape the app forbids.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "Tender Master",
				"company": cls.company,
				"title": "ADR-609 bench",
				"buyer_name": "ADR-609 bench",
			}
		).insert(ignore_permissions=True)
		return cls._track("Tender Master", doc.name)

	@classmethod
	def _make_deal(cls, deal_type: str, *, stage: str = "", company: str | None = None) -> str:
		"""A CRM Deal with no organization: `organization` is a LINK, not a label."""
		payload = {"doctype": DIMENSION_DOCTYPE, "company": company or cls.company, "deal_type": deal_type}
		if deal_type == "Tender":
			payload["custom_parent_tender"] = cls.master
		if stage and frappe.db.has_column(DIMENSION_DOCTYPE, "custom_tender_stage"):
			payload["custom_tender_stage"] = stage
		doc = frappe.get_doc(payload).insert(ignore_permissions=True)
		return cls._track(DIMENSION_DOCTYPE, doc.name)

	def setUp(self):
		if not self.ready:
			self.skipTest("no tender-enabled company with the dimension installed on this site")
		frappe.set_user("Administrator")
		clear_dimension_cache()

	def _expense_entry(self, *, deal: str | None, company: str | None = None, amount: float = 1234.0) -> str:
		"""One submitted expense JE, cancelled and erased when the test ends."""
		company = company or self.company
		result = submit_expense_entry(
			company=company,
			posting_date=today(),
			payment_from=_an_account(
				company,
				account_type="Cash",
				account_currency=frappe.db.get_value("Company", company, "default_currency"),
			),
			lines=[{"account": _plain_expense_account(company), "amount": amount, "memo": "ADR-609 bench"}],
			deal=deal,
			submit=1,
		)
		name = result["name"]
		self.addCleanup(self._erase_voucher, "Journal Entry", name)
		return name

	def _erase_voucher(self, doctype: str, name: str) -> None:
		"""Cancel, delete, and take the ledger rows with it.

		`delete_linked_ledger_entries` is off on this site, so `delete_doc` alone
		leaves the GL rows standing and the next run measures them.

		It does NOT commit, and must not. Nothing on the expense path commits —
		`money.py` has no `db.commit` on any write path, and a submitted voucher
		disappears on `frappe.db.rollback()` — so there is nothing here that the
		framework's rollback cannot undo. What a commit here WOULD do is persist
		everything else then pending: the cleanup stack is LIFO, so in
		`TestModuleFlagOff` this runs before `_set_flag(1)` and would commit
		`enable_tender = 0` onto the real `_Test Company` row, leaving a live
		company with the tender module silently off if the run were interrupted
		before the class-level commit put it back. Pinned by
		`TestSuiteHygiene.test_a_per_test_cleanup_never_commits`.
		"""
		if not frappe.db.exists(doctype, name):
			return
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		frappe.db.delete("GL Entry", {"voucher_type": doctype, "voucher_no": name})


class TestSuiteHygiene(_Fixture):
	"""R20 — what the cleanups may and may not do to a live site."""

	def test_a_per_test_cleanup_never_commits(self):
		"""A commit inside a per-test cleanup commits EVERYTHING then pending.

		The cleanup stack is LIFO, so in `TestModuleFlagOff` `_erase_voucher`
		runs BEFORE `_set_flag(1)`: a commit there persists `enable_tender = 0`
		on the real `_Test Company` row, and only the class-level commit puts it
		back. A run interrupted in between leaves a live company with the tender
		module silently off — this suite would have changed the site it measures.
		"""
		seen = []
		original = frappe.db.commit
		frappe.db.commit = lambda: seen.append("commit")
		try:
			name = self._expense_entry(deal=None, amount=17.0)
			self._erase_voucher("Journal Entry", name)
		finally:
			frappe.db.commit = original
		self.assertEqual(seen, [], "a per-test cleanup committed the transaction")


class TestPatchLanded(_Fixture):
	"""Acceptance 1 — what `v103` left on this site."""

	def test_the_dimension_exists_over_crm_deal(self):
		row = frappe.db.get_value(
			"Accounting Dimension",
			{"document_type": DIMENSION_DOCTYPE},
			["name", "fieldname", "disabled"],
			as_dict=True,
		)
		self.assertTrue(row, "no Accounting Dimension over CRM Deal — v103 has not run here")
		self.assertFalse(row.disabled, "the dimension is disabled; nothing would be stamped")
		self.assertEqual(row.fieldname, self.fieldname)

	def test_every_doctype_the_ledger_needs_carries_the_column(self):
		# A Custom Field row is not a column. `has_column` is the only thing that
		# distinguishes "the patch asked" from "the field is there to be written".
		missing = [dt for dt in _REQUIRED_ON if not frappe.db.has_column(dt, self.fieldname)]
		self.assertEqual(missing, [], f"the dimension field never landed on {missing}")

	def test_the_company_row_makes_the_dimension_mandatory_for_pl(self):
		row = frappe.db.get_value(
			"Accounting Dimension Detail",
			{
				"parent": frappe.db.get_value(
					"Accounting Dimension", {"document_type": DIMENSION_DOCTYPE}, "name"
				),
				"company": self.company,
			},
			["mandatory_for_pl", "mandatory_for_bs", "default_dimension", "reference_document"],
			as_dict=True,
		)
		self.assertTrue(row, f"{self.company} has the module on but no dimension detail row")
		self.assertEqual(row.mandatory_for_pl, 1, "a P&L row could be posted with no tender")
		# Balance-sheet rows stay optional on purpose (decision 2): the cash leg of
		# an expense is not a tender cost, and requiring it would double every
		# tender's figure once P5b sums the dimension.
		self.assertEqual(row.mandatory_for_bs, 0)
		self.assertEqual(row.reference_document, DIMENSION_DOCTYPE)
		self.assertEqual(row.default_dimension, self.overhead)

	def test_running_the_setup_again_changes_nothing(self):
		self.assertEqual(
			ensure_company_setup(self.company),
			{"overhead_deal": False, "detail_row": False, "default_dimension": False},
		)

	def test_the_overhead_deal_is_the_one_genel_gider_bucket(self):
		row = frappe.db.get_value(
			DIMENSION_DOCTYPE, self.overhead, ["organization", "deal_type", "company"], as_dict=True
		)
		self.assertEqual(row.deal_type, "Overhead")
		self.assertEqual(row.company, self.company)
		self.assertEqual(row.organization, OVERHEAD_ORGANIZATION)
		self.assertEqual(
			frappe.db.count(DIMENSION_DOCTYPE, {"company": self.company, "deal_type": "Overhead"}),
			1,
			"a second overhead deal would split the company's untagged cost in two",
		)


class TestExpenseEntry(_Fixture):
	"""Acceptance 2 — the Journal Entry writer, end to end."""

	def test_a_chosen_tender_reaches_every_account_row_and_every_gl_row(self):
		name = self._expense_entry(deal=self.tender)
		rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": name},
			fields=["account", self.fieldname],
			limit_page_length=0,
		)
		self.assertTrue(rows)
		self.assertEqual(
			[r[self.fieldname] for r in rows],
			[self.tender] * len(rows),
			"a Journal Entry Account row lost the tender, so its GL row cannot carry it",
		)
		gl = _gl_rows("Journal Entry", name, self.fieldname)
		self.assertTrue(gl, "the entry posted no ledger rows")
		self.assertEqual({r[self.fieldname] for r in gl}, {self.tender})

	def test_an_untagged_expense_lands_on_genel_gider_and_leaves_the_cash_leg_alone(self):
		name = self._expense_entry(deal=None)
		gl = _gl_rows("Journal Entry", name, self.fieldname)
		pl = [r for r in gl if _report_type(r["account"]) == "Profit and Loss"]
		bs = [r for r in gl if _report_type(r["account"]) == "Balance Sheet"]
		self.assertTrue(pl and bs, "the fixture no longer posts one P&L and one balance-sheet row")
		self.assertEqual(
			{r[self.fieldname] for r in pl},
			{self.overhead},
			"an untagged P&L row stayed unattributed — `mandatory_for_pl` would have thrown on a real site",
		)
		self.assertEqual(
			[r[self.fieldname] for r in bs],
			[None] * len(bs),
			"the cash leg was tagged; every tender's cost would be counted twice",
		)

	def _amend(self, source: str, deal: str, amount: float = 1234.0) -> dict:
		return amend_expense_entry(
			source_name=source,
			modified=frappe.db.get_value("Journal Entry", source, "modified"),
			company=self.company,
			posting_date=today(),
			payment_from=self.cash,
			lines=[{"account": self.expense, "amount": amount, "memo": "ADR-609 bench amend"}],
			deal=deal,
			submit=1,
		)

	def test_an_expense_on_a_tender_that_has_since_been_lost_can_still_be_corrected(self):
		"""R15. An amendment re-sends the value the voucher already carries.

		`Expenses.vue` puts the STORED deal into every edit payload, so the
		correction arrives naming the same tender the original was posted
		against. Treating that as a fresh choice makes the ONE operation that
		fixes a posted voucher impossible the moment the tender is finished — and
		the throw lands AFTER `source.cancel()`, so the user is left with a
		cancelled expense and no replacement, saved only by the HTTP rollback.
		`tender_dimension` already promises the opposite: a document that carries
		a tender which has since been lost stays readable and SAVABLE.
		"""
		live = self._make_deal("Tender")
		name = self._expense_entry(deal=live)
		frappe.db.set_value(DIMENSION_DOCTYPE, live, "custom_tender_stage", "lost")
		clear_dimension_cache()
		self.assertFalse(is_active_tender(live, self.company), "the fixture did not finish the tender")

		result = self._amend(name, live)
		self.addCleanup(self._erase_voucher, "Journal Entry", result["name"])

		self.assertEqual(result["amended_from"], name)
		pl = [
			r
			for r in _gl_rows("Journal Entry", result["name"], self.fieldname)
			if _report_type(r["account"]) == "Profit and Loss"
		]
		self.assertTrue(pl, "the replacement booked no expense row")
		self.assertEqual(
			{r[self.fieldname] for r in pl},
			{live},
			"the correction lost the attribution the original voucher had",
		)

	def test_naming_a_cancelled_voucher_does_not_buy_a_new_expense_on_a_dead_tender(self):
		"""R21. The relaxation may not key off `amended_from` alone.

		`amended_from` is a DECLARED kwarg of the whitelisted
		`submit_expense_entry`, and frappe passes a client any parameter the
		signature declares. So "this is an amendment" cannot be something the
		caller asserts: naming any cancelled, not-yet-amended voucher of one's own
		company that carries a finished tender would post a BRAND NEW expense
		against it. The relaxation belongs to `amend_expense_entry`'s request, and
		`frappe.local` is the only thing a client cannot set.
		"""
		dead = self._make_deal("Tender")
		source = self._expense_entry(deal=dead)
		frappe.db.set_value(DIMENSION_DOCTYPE, dead, "custom_tender_stage", "lost")
		clear_dimension_cache()
		doc = frappe.get_doc("Journal Entry", source)
		doc.flags.ignore_permissions = True
		doc.cancel()

		created = {}
		try:
			with self.assertRaises(frappe.ValidationError) as caught:
				created["name"] = submit_expense_entry(
					company=self.company,
					posting_date=today(),
					payment_from=self.cash,
					lines=[{"account": self.expense, "amount": 55.0, "memo": "ADR-609 bench forged"}],
					deal=dead,
					amended_from=source,
					submit=1,
				)["name"]
		finally:
			if created.get("name"):
				self._erase_voucher("Journal Entry", created["name"])
		self.assertIn("active tender", str(caught.exception))

	def test_amending_onto_a_DIFFERENT_dead_tender_is_still_refused(self):
		"""The other half: a value that CHANGES is a new choice and is asserted.

		Without this the R15 fix would read as "amendments skip the check", and a
		user could move a posted cost onto a lost tender by editing the voucher.
		"""
		name = self._expense_entry(deal=self.tender)
		with self.assertRaises(frappe.ValidationError) as caught:
			self._amend(name, self.lost)
		self.assertIn("active tender", str(caught.exception))

	def test_a_lost_tender_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self._expense_entry(deal=self.lost)
		self.assertIn("active tender", str(caught.exception))

	def test_a_standard_deal_is_refused(self):
		standard = self._make_deal("Standard")
		with self.assertRaises(frappe.ValidationError):
			self._expense_entry(deal=standard)


class TestModuleFlagOff(_Fixture):
	"""R2 — turning `enable_tender` off must not brick a company already set up."""

	def _set_flag(self, value: int) -> None:
		settings = frappe.get_single("Stabler Settings")
		for row in settings.company_modules:
			if row.company == self.company:
				row.enable_tender = value
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
		clear_dimension_cache()

	def test_the_ledger_still_posts_and_still_attributes_when_the_flag_goes_off(self):
		"""erpnext reads the detail row, not our flag.

		`ensure_company_setup` never deletes the row — history would be left
		carrying a dimension nothing declares — so `mandatory_for_pl` stays on and
		`validate_dimensions_for_pl_and_bs` goes on refusing an empty P&L row.
		Measured before the fix: flag off, untagged expense -> "Accounting
		Dimension Tender is required for 'Profit and Loss' account Tax Expense -
		_TC", i.e. the company could no longer post at all.
		"""
		self.addCleanup(self._set_flag, 1)
		self._set_flag(0)
		self.assertFalse(tender_enabled(self.company), "the fixture did not actually turn the module off")
		name = self._expense_entry(deal=None, amount=931.0)
		gl = _gl_rows("Journal Entry", name, self.fieldname)
		pl = [r for r in gl if _report_type(r["account"]) == "Profit and Loss"]
		bs = [r for r in gl if _report_type(r["account"]) == "Balance Sheet"]
		self.assertTrue(pl and bs)
		self.assertEqual({r[self.fieldname] for r in pl}, {self.overhead})
		self.assertEqual([r[self.fieldname] for r in bs], [None] * len(bs))


class TestPurchaseInvoice(_Fixture):
	"""Acceptance 3 — the purchase writer and what the form is told about it."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not cls.ready:
			return
		cls.supplier = frappe.db.get_value("Supplier", {"disabled": 0}, "name")
		cls.service_item = frappe.db.get_value("Item", {"is_stock_item": 0, "disabled": 0}, "name")
		cls.ready = bool(cls.supplier and cls.service_item)

	def _submit(self, doctype: str, name: str) -> str:
		doc = frappe.get_doc(doctype, name)
		doc.flags.ignore_permissions = True
		doc.submit()
		return name

	def _invoice(self, tender: str | None) -> str:
		result = create_purchase_invoice(
			company=self.company,
			supplier=self.supplier,
			items=[{"item_code": self.service_item, "qty": 1, "rate": 500}],
			posting_date=today(),
			tender=tender,
		)
		self.addCleanup(self._erase_voucher, "Purchase Invoice", result["name"])
		return result["name"]

	def test_an_untagged_bill_puts_its_expense_on_genel_gider(self):
		name = self._invoice(None)
		self.assertFalse(
			frappe.db.get_value("Purchase Invoice", name, self.fieldname),
			"the overhead deal was written at DOCUMENT level; an untagged bill would read as a deliberate overhead decision",
		)
		self._submit("Purchase Invoice", name)
		pl = [
			r
			for r in _gl_rows("Purchase Invoice", name, self.fieldname)
			if _report_type(r["account"]) == "Profit and Loss"
		]
		self.assertTrue(pl, "the bill booked no expense row")
		self.assertEqual({r[self.fieldname] for r in pl}, {self.overhead})

	def test_a_chosen_tender_reaches_the_parent_the_rows_and_the_ledger(self):
		name = self._invoice(self.tender)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", name, self.fieldname), self.tender)
		rows = frappe.get_all(
			"Purchase Invoice Item", filters={"parent": name}, pluck=self.fieldname, limit_page_length=0
		)
		self.assertEqual(rows, [self.tender] * len(rows))
		self._submit("Purchase Invoice", name)
		pl = [
			r
			for r in _gl_rows("Purchase Invoice", name, self.fieldname)
			if _report_type(r["account"]) == "Profit and Loss"
		]
		self.assertEqual({r[self.fieldname] for r in pl}, {self.tender})

	def test_a_tagged_bill_carries_its_tender_on_the_supplier_leg_as_well(self):
		"""R12. The hook never fills a balance-sheet row; erpnext tags both legs anyway.

		`default_gl_tender` returns early on a Balance Sheet account, so nothing
		P5a does puts a tender on the payable. erpnext does: a document-level
		dimension is copied onto EVERY GL row the voucher posts, both legs. This
		is measured rather than asserted in a docstring because P5b depends on
		it — a report that summed the dimension across all accounts would count
		this bill twice, once as expense and once as payable, and every tender's
		figure would come out doubled.
		"""
		name = self._invoice(self.tender)
		self._submit("Purchase Invoice", name)
		bs = [
			r
			for r in _gl_rows("Purchase Invoice", name, self.fieldname)
			if _report_type(r["account"]) == "Balance Sheet"
		]
		self.assertTrue(bs, "the bill booked no balance-sheet row")
		self.assertEqual({r[self.fieldname] for r in bs}, {self.tender})

	def test_a_lost_tender_cannot_be_sent_to_the_writer(self):
		with self.assertRaises(frappe.ValidationError):
			self._invoice(self.lost)

	def test_a_bill_made_from_an_order_inherits_the_orders_deal_and_says_so(self):
		if not frappe.db.has_column("Purchase Order", "custom_crm_deal"):
			self.skipTest("this site has no `Purchase Order.custom_crm_deal` (patch v30)")
		po = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"company": self.company,
				"supplier": self.supplier,
				"transaction_date": today(),
				"schedule_date": today(),
				"custom_crm_deal": self.tender,
				"items": [{"item_code": self.service_item, "qty": 1, "rate": 500, "schedule_date": today()}],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Purchase Order", po.name)
		self.assertEqual(
			po.get(self.fieldname),
			self.tender,
			"`stamp_tender` did not copy the order's own deal onto the dimension field",
		)
		self._submit("Purchase Order", po.name)
		pi = create_purchase_invoice_from_po(po.name)
		self.addCleanup(self._erase_voucher, "Purchase Invoice", pi["name"])
		self.assertEqual(
			frappe.db.get_value("Purchase Invoice", pi["name"], self.fieldname),
			self.tender,
			"the bill lost the tender the order was placed under, and the SPA never sent one",
		)
		detail = purchase_invoice_detail(pi["name"])
		self.assertEqual(detail["tender"], self.tender)
		self.assertEqual(
			detail["tender_locked"], 1, "the form would offer to change a value the order decided"
		)


class TestSalesSide(_Fixture):
	"""Acceptance 4 — the tender follows a sales order into revenue and cost."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not cls.ready:
			return
		cls.customer = frappe.db.get_value("Customer", {"disabled": 0}, "name")
		# `valuation_rate >= 1`, biggest first: erpnext books NO ledger row for a
		# stock value difference that rounds to zero, and this site holds the same
		# item at 0.1 UZS in another warehouse — measured, the delivery submitted
		# happily and posted nothing, so the test failed on the fixture's rounding
		# rather than on the tender.
		cls.stock = frappe.db.get_value(
			"Bin",
			{"actual_qty": [">", 1], "valuation_rate": [">=", 1]},
			["item_code", "warehouse", "valuation_rate"],
			as_dict=True,
			order_by="valuation_rate desc",
		)
		cls.has_so_deal = frappe.db.has_column("Sales Order", "custom_crm_deal")
		cls.ready = bool(cls.customer and cls.stock and cls.has_so_deal)

	def setUp(self):
		super().setUp()
		if not self.ready:
			self.skipTest("no customer with stock on hand, or no `Sales Order.custom_crm_deal`, on this site")

	def _order(self) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"company": self.company,
				"customer": self.customer,
				"transaction_date": today(),
				"delivery_date": today(),
				"custom_crm_deal": self.tender,
				"items": [
					{
						"item_code": self.stock.item_code,
						"warehouse": self.stock.warehouse,
						"qty": 1,
						"rate": 1000,
						"delivery_date": today(),
					}
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Sales Order", doc.name)
		doc.flags.ignore_permissions = True
		doc.submit()
		return doc.name

	def test_an_invoice_made_from_the_order_carries_the_tender_into_revenue(self):
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		order = self._order()
		si = make_sales_invoice(order)
		si.flags.ignore_permissions = True
		si.insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Sales Invoice", si.name)
		self.assertEqual(si.get(self.fieldname), self.tender, "the invoice lost the order's tender")
		self.assertEqual(
			[row.get(self.fieldname) for row in si.items],
			[self.tender] * len(si.items),
			"an invoice row lost the tender, so its revenue GL row cannot carry it",
		)
		si.submit()
		income = [
			r
			for r in _gl_rows("Sales Invoice", si.name, self.fieldname)
			if _report_type(r["account"]) == "Profit and Loss"
		]
		self.assertTrue(income, "the invoice booked no revenue row")
		self.assertEqual({r[self.fieldname] for r in income}, {self.tender})

	def test_a_delivery_with_no_tender_of_its_own_takes_it_from_the_order(self):
		"""The row-level source lookup, with the parent's own routes taken away.

		Written because a mutation SURVIVED the test above: dropping
		`against_sales_order` from `_ITEM_SOURCES` changed nothing there, because
		erpnext's mapper copies `custom_crm_deal` onto the delivery note and
		`stamp_tender` then spreads the parent value over the rows. So that test
		measures the mapper, not the source lookup. Here the delivery arrives with
		neither field set — the shape a delivery combining orders has, and the shape
		a delivery gets the moment a tender is chosen only through the dimension —
		and `against_sales_order` is its only way back to the tender.
		"""
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		order = self._order()
		dn = make_delivery_note(order)
		for row in dn.items:
			row.warehouse = self.stock.warehouse
			row.set(self.fieldname, None)
			self.assertTrue(row.against_sales_order, "the mapper stopped linking the row to its order")
		dn.set(self.fieldname, None)
		dn.set("custom_crm_deal", None)
		dn.flags.ignore_permissions = True
		dn.insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Delivery Note", dn.name)
		self.assertEqual(
			[row.get(self.fieldname) for row in dn.items],
			[self.tender] * len(dn.items),
			"a delivery with no tender of its own left its cost unattributed",
		)

	def test_a_delivery_made_from_the_order_carries_the_tender_into_cost_of_goods(self):
		from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

		order = self._order()
		dn = make_delivery_note(order)
		# `make_delivery_note` re-resolves each row's warehouse from the item's
		# defaults, which on this site points at a warehouse holding the item at a
		# tenth of a som. Pin it back to the warehouse the fixture measured.
		for row in dn.items:
			row.warehouse = self.stock.warehouse
		dn.flags.ignore_permissions = True
		dn.insert(ignore_permissions=True)
		self.addCleanup(self._erase_voucher, "Delivery Note", dn.name)
		self.assertEqual(
			[row.get(self.fieldname) for row in dn.items],
			[self.tender] * len(dn.items),
			"`against_sales_order` is the delivery note's only link back to the tender",
		)
		dn.submit()
		self.assertTrue(
			frappe.db.get_value("Stock Ledger Entry", {"voucher_no": dn.name}, "stock_value_difference"),
			"the delivery moved no stock VALUE, so no cost row could exist to carry a tender",
		)
		booked = _gl_rows("Delivery Note", dn.name, self.fieldname)
		cogs = [r for r in booked if _report_type(r["account"]) == "Profit and Loss"]
		self.assertTrue(cogs, f"the delivery booked no cost of goods row; it booked {booked}")
		self.assertEqual({r[self.fieldname] for r in cogs}, {self.tender})


class TestPlainCompany(_Fixture):
	"""Acceptance 1 (negative) and 5 — the money invariant, measured.

	A second company is created for this and removed again. It is the only way to
	ask the question the invariant is about: does the SAME expense post the SAME
	ledger on a company that never heard of tenders?
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not cls.ready:
			return
		source = frappe.get_doc("Company", cls.company)
		if frappe.db.exists("Company", _PLAIN_COMPANY):
			# A previous run that died between the insert and its cleanup. The name
			# is this module's own, so removing it is finishing that run's rollback.
			frappe.delete_doc("Company", _PLAIN_COMPANY, force=True, ignore_permissions=True)
		cls.plain = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": _PLAIN_COMPANY,
				"abbr": "_A609",
				"default_currency": source.default_currency,
				"country": source.country,
			}
		).insert(ignore_permissions=True)
		# Registered LAST so it runs FIRST: the company cannot go while any GL row
		# still names it, and `Company.on_trash` keeps the accounts of a company
		# with ledger history.
		cls.addClassCleanup(frappe.delete_doc, "Company", cls.plain.name, force=True, ignore_permissions=True)
		cls.addClassCleanup(frappe.db.delete, "GL Entry", {"company": cls.plain.name})
		# `Stabler Company Modules` is a CHILD table of the `Stabler Settings`
		# single, not a standalone doctype — inserting one directly dies on
		# "Value missing for None: parent, parenttype". `get_company_module_row`
		# appends the row itself, with `tender` off by DEFAULT_MODULE_ENABLED,
		# which is precisely the company this class needs.
		module_map_for(cls.plain.name)
		cls.addClassCleanup(cls._drop_module_row, cls.plain.name)

	@classmethod
	def _drop_module_row(cls, company: str) -> None:
		settings = frappe.get_single("Stabler Settings")
		settings.company_modules = [r for r in settings.company_modules if r.company != company]
		settings.save(ignore_permissions=True)

	def test_a_company_with_the_module_off_gets_no_bucket_and_no_detail_row(self):
		self.assertEqual(
			ensure_company_setup(self.plain.name),
			{"overhead_deal": False, "detail_row": False, "default_dimension": False},
		)
		self.assertIsNone(
			overhead_deal(self.plain.name), "a GENEL GİDER deal was created for a non-tender company"
		)
		self.assertFalse(
			frappe.db.exists(
				"Accounting Dimension Detail",
				{
					"parent": frappe.db.get_value(
						"Accounting Dimension", {"document_type": DIMENSION_DOCTYPE}, "name"
					),
					"company": self.plain.name,
				},
			),
			"a non-tender company was made mandatory for P&L; every posting on it would throw",
		)

	def test_turning_the_flag_on_through_the_settings_single_sets_the_company_up(self):
		"""R1 end to end: the PARENT save is what runs the setup.

		Registered on `Stabler Company Modules` the handler fired zero times — that
		doctype is a child table and frappe never runs a child row's document
		methods — so a company switched on from the organization screen got no
		GENEL GIDER deal and no detail row, and its first P&L posting then died on
		a mandatory dimension nobody had given it a value for.
		"""
		self.addCleanup(self._teardown_toggle)
		settings = frappe.get_single("Stabler Settings")
		for row in settings.company_modules:
			if row.company == self.plain.name:
				row.enable_tender = 1
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)

		clear_dimension_cache()
		deal = overhead_deal(self.plain.name)
		self.assertTrue(deal, "saving Stabler Settings did not create the company's GENEL GIDER deal")
		row = frappe.db.get_value(
			"Accounting Dimension Detail",
			{"parent": _dimension_name(), "company": self.plain.name},
			["mandatory_for_pl", "default_dimension"],
			as_dict=True,
		)
		self.assertTrue(row, "saving Stabler Settings did not create the company's detail row")
		self.assertEqual(row.mandatory_for_pl, 1)
		self.assertEqual(row.default_dimension, deal)

	def _teardown_toggle(self) -> None:
		"""Undo the toggle and everything the hook created for it."""
		settings = frappe.get_single("Stabler Settings")
		for row in settings.company_modules:
			if row.company == self.plain.name:
				row.enable_tender = 0
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
		frappe.db.delete(
			"Accounting Dimension Detail", {"parent": _dimension_name(), "company": self.plain.name}
		)
		clear_dimension_cache()
		deal = overhead_deal(self.plain.name)
		if deal:
			frappe.delete_doc(DIMENSION_DOCTYPE, deal, force=True, ignore_permissions=True)
		clear_dimension_cache()

	def test_the_same_expense_posts_the_same_ledger_without_the_dimension(self):
		"""The money invariant: the field is the ONLY difference between the two."""
		tagged = self._expense_entry(deal=None, amount=777.0)
		plain = self._expense_entry(deal=None, company=self.plain.name, amount=777.0)

		def shape(voucher: str) -> list[tuple]:
			# Accounts are named per company (`Cash - _TC` vs `Cash - _A609`), so the
			# comparable identity is the account's ROLE, not its name.
			return sorted(
				(
					_report_type(r["account"]),
					frappe.get_cached_value("Account", r["account"], "root_type"),
					flt(r["debit"]),
					flt(r["credit"]),
					r["account_currency"],
				)
				for r in _gl_rows("Journal Entry", voucher, self.fieldname)
			)

		self.assertEqual(
			shape(plain),
			shape(tagged),
			"the tender dimension moved an amount, a currency or an account role",
		)
		self.assertEqual(
			[r[self.fieldname] for r in _gl_rows("Journal Entry", plain, self.fieldname)],
			[None] * len(_gl_rows("Journal Entry", plain, self.fieldname)),
			"a company with the module off had its ledger stamped",
		)


class TestPickers(_Fixture):
	"""Acceptance 6 and 7 — what a picker may offer, and what a board must not show."""

	def test_the_picker_leads_with_genel_gider_and_offers_live_tenders(self):
		rows = list_deals(company=self.company, active_tenders=1)["deals"]
		names = [r["name"] for r in rows]
		self.assertEqual(names[0], self.overhead, "GENEL GİDER is not the first thing offered")
		self.assertEqual(rows[0]["organization"], OVERHEAD_ORGANIZATION)
		self.assertIn(self.tender, names)
		self.assertNotIn(self.lost, names, "a lost tender was offered as a place to put new cost")

	def test_the_picker_excludes_a_standard_deal(self):
		standard = self._make_deal("Standard")
		offered = [r["name"] for r in list_deals(company=self.company, active_tenders=1)["deals"]]
		self.assertNotIn(standard, offered)

	def test_the_crm_board_never_shows_the_overhead_bucket(self):
		# `list_deals` without `active_tenders` is the board's own call, and the
		# exclusion lives in `_crm_list` underneath it — asserted through the
		# endpoint rather than the private helper so a change of route still fails.
		names = [r["name"] for r in list_deals(company=self.company, page_length=500)["deals"]]
		self.assertNotIn(self.overhead, names, "GENEL GİDER appeared on the deal board as if it were a deal")
		self.assertIn(self.tender, names, "the board stopped showing tenders altogether")
