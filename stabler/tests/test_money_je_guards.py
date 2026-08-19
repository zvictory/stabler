"""Journal Entry write guards: who may overwrite what, and when.

The JE editor replaces the whole account table on every save
(``doc.set("accounts", [])`` then re-append). That makes the update endpoint the
most destructive write in the money module: it does not merge, it substitutes.
Three guards decide whether that substitution is safe, and each is tested here
for the reason it exists, not merely for the branch it takes.

1. **Concurrency.** Submit, cancel and delete all take a ``modified`` token and
   call ``check_concurrency``; update did not. Two tabs on the same draft meant
   the second save silently discarded the first save's rows — and because the
   rows are replaced wholesale, not merged, nothing about the document showed
   that anything had been lost until somebody submitted it.

2. **Frozen periods.** A posting date inside a frozen accounting period used to
   save happily as a draft and only fail at submit, with ERPNext's untranslated
   message. The entry then existed in the list but never in the ledger — the
   source of "I entered it, why is it not in the trial balance". The refusal
   belongs where the date is accepted, in the user's own language.

3. **Save-and-post as one call.** ``create_journal_entry`` could only ever make a
   draft, so posting meant a second round trip through a different button. The
   ``submit`` flag must go through the *same* permission and validation path —
   a shortcut that skipped ``submit`` permission would turn a convenience into a
   privilege escalation.

Plus the list endpoint's search/paging contract (B1), which decides whether an
entry from three weeks ago can be reached at all.

Bench-free by construction: ``make check`` does not run the bench set, so a test
that needed a live site would not gate a push.

  PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_money_je_guards -v
"""

from __future__ import annotations

import importlib
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


class FakeDoc:
	"""Minimal stand-in for a Frappe document.

	Records every lifecycle call into the shared ``trace`` list so a test can
	assert the ORDER of guards, not just that they ran: a concurrency check that
	fires after ``save`` has already replaced the rows guards nothing.
	"""

	def __init__(self, trace, **fields):
		self._trace = trace
		self.accounts = []
		self.docstatus = 0
		self.name = None
		self.voucher_type = "Journal Entry"
		self.__dict__.update(fields)

	def append(self, table, row):
		getattr(self, table).append(dict(row))

	def set(self, table, value):
		setattr(self, table, list(value))

	def get(self, key, default=None):
		return getattr(self, key, default)

	def save(self, **kwargs):
		self._trace.append("save")

	def insert(self, **kwargs):
		self._trace.append("insert")
		self.name = self.name or "JV-NEW-0001"

	def submit(self):
		self._trace.append("submit")
		self.docstatus = 1


#: The fake ``frappe._`` stamps this prefix on everything it is handed, so a test
#: can tell a translated message from a raw f-string. Half the point of moving the
#: frozen-period refusal into our own code is that ERPNext's version of it reaches
#: a Russian- or Uzbek-speaking accountant in English.
I18N = "[i18n]"


def _load_money(
	*,
	db_modified="2026-08-19 10:00:00",
	acc_frozen_upto=None,
	frozen_accounts_modifier=None,
	roles=(),
	existing_doc=None,
	exchange_rates=None,
	accounts=None,
	temporary_accounts=None,
):
	"""Import ``stabler.api.money`` against a hand-built ``frappe``.

	Returns ``(module, ctx)`` where ``ctx`` carries the trace of guard calls, the
	documents the module created, and the SQL it issued.
	"""
	_SANDBOX.evict(
		"stabler.api.money",
		"stabler.api._common",
		"stabler.api.approvals",
		"stabler.api.supplier_payment_guard",
		"frappe",
		"frappe.utils",
		"frappe.rate_limiter",
		"erpnext",
		"erpnext.setup",
		"erpnext.setup.utils",
	)

	trace: list[str] = []
	ctx = types.SimpleNamespace(trace=trace, docs=[], queries=[], existing=existing_doc)

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: I18N + value
	frappe.message_log = []

	class _ValidationError(Exception):
		pass

	frappe.ValidationError = _ValidationError
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.DoesNotExistError = type("DoesNotExistError", (Exception,), {})
	frappe.TimestampMismatchError = type("TimestampMismatchError", (_ValidationError,), {})

	def _throw(message, exc=None, *args, **kwargs):
		raise (exc or _ValidationError)(str(message))

	frappe.throw = _throw
	frappe.whitelist = lambda *a, **k: lambda fn: fn
	frappe.session = types.SimpleNamespace(user="accountant@example.com")
	frappe.get_roles = lambda _user=None: list(roles)
	frappe.local = types.SimpleNamespace(response={})

	account_rows = dict(accounts or {})

	def _get_value(doctype, filters=None, fieldname=None, *args, **kwargs):
		as_dict = kwargs.get("as_dict")
		if doctype == "Company":
			return "UZS"
		if doctype == "Account":
			row = account_rows.get(filters)
			if row is None:
				return None
			if as_dict:
				return types.SimpleNamespace(**row)
			if isinstance(fieldname, list):
				return [row.get(f) for f in fieldname]
			return row.get(fieldname)
		if doctype == "Journal Entry" and fieldname == "modified":
			return db_modified
		return None

	frappe.db = types.SimpleNamespace(
		get_value=_get_value,
		exists=lambda *a, **k: True,
		sql=lambda query, params=None, **kw: ctx.queries.append((query, params)) or [],
	)

	def _get_all(doctype, filters=None, fields=None, **kwargs):
		if doctype == "Account" and (filters or {}).get("account_type") == "Temporary":
			return list(
				temporary_accounts if temporary_accounts is not None else [{"name": "Temporary Opening - X"}]
			)
		return []

	frappe.get_all = _get_all

	def _get_doc(doctype, name=None):
		trace.append("get_doc")
		if ctx.existing is None:
			ctx.existing = FakeDoc(trace, name=name, company="Test Co", docstatus=0)
		return ctx.existing

	frappe.get_doc = _get_doc

	def _new_doc(doctype):
		doc = FakeDoc(trace, doctype=doctype)
		ctx.docs.append(doc)
		return doc

	frappe.new_doc = _new_doc

	def _get_single(doctype):
		if doctype == "Accounts Settings":
			return types.SimpleNamespace(
				get=lambda key, default=None: {
					"acc_frozen_upto": acc_frozen_upto,
					"frozen_accounts_modifier": frozen_accounts_modifier,
				}.get(key, default)
			)
		return types.SimpleNamespace(get=lambda key, default=None: default)

	frappe.get_single = _get_single
	frappe.log_error = lambda *a, **k: None

	import datetime

	def _getdate(value=None):
		if value in (None, ""):
			return datetime.date(2026, 8, 19)
		if isinstance(value, datetime.date):
			return value
		return datetime.date(*(int(p) for p in str(value)[:10].split("-")))

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value, precision=None: 0.0 if value in (None, "") else float(value)

	def _cint(value):
		# frappe.utils.cint's contract, which matters here: everything arriving
		# over HTTP is a string, and a non-numeric one is 0, not a truthy object.
		try:
			return int(float(value))
		except (TypeError, ValueError):
			return 0

	utils.cint = _cint
	utils.getdate = _getdate
	utils.today = lambda: "2026-08-19"
	utils.formatdate = lambda value, fmt=None: str(value)
	utils.get_datetime_str = lambda value: str(value)
	utils.add_days = lambda value, days: _getdate(value) + datetime.timedelta(days=days)
	utils.nowdate = lambda: "2026-08-19"
	frappe.utils = utils

	rate_limiter = types.ModuleType("frappe.rate_limiter")
	rate_limiter.rate_limit = lambda *a, **k: lambda fn: fn
	frappe.rate_limiter = rate_limiter

	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: company
	common._assert_can_read = lambda *a, **k: None

	def _assert_can_write(doctype, name, ptype="write"):
		trace.append(f"can_write:{ptype}")

	common._assert_can_write = _assert_can_write

	def _check_concurrency(doctype, name, modified=None):
		trace.append("check_concurrency")
		if db_modified and not modified:
			_throw("Stale request: reload the document.")
		if db_modified and modified and str(db_modified) != str(modified):
			_throw("This document was changed by someone else.", frappe.TimestampMismatchError)

	common.check_concurrency = _check_concurrency

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: None

	guard = types.ModuleType("stabler.api.supplier_payment_guard")
	guard.assert_supplier_payment_currency = lambda *a, **k: None

	erpnext = types.ModuleType("erpnext")
	erpnext_setup = types.ModuleType("erpnext.setup")
	erpnext_utils = types.ModuleType("erpnext.setup.utils")
	rates = dict(exchange_rates or {})
	erpnext_utils.get_exchange_rate = lambda frm, to, date=None: rates.get((frm, to), 0.0)
	erpnext.setup = erpnext_setup
	erpnext_setup.utils = erpnext_utils

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"frappe.rate_limiter": rate_limiter,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.api.supplier_payment_guard": guard,
			"erpnext": erpnext,
			"erpnext.setup": erpnext_setup,
			"erpnext.setup.utils": erpnext_utils,
		}
	)
	module = importlib.import_module("stabler.api.money")
	ctx.frappe = frappe
	return module, ctx


#: Two balanced base-currency lines — the smallest payload the endpoint accepts.
CASH = "Cash - X"
SALES = "Sales - X"
BASE_ACCOUNTS = {
	CASH: {"company": "Test Co", "is_group": 0, "account_currency": "UZS"},
	SALES: {"company": "Test Co", "is_group": 0, "account_currency": "UZS"},
}
BALANCED_ROWS = [
	{"account": CASH, "debit": 1000, "credit": 0},
	{"account": SALES, "debit": 0, "credit": 1000},
]


class UpdateJournalEntryConcurrencyTest(unittest.TestCase):
	"""A6 — the draft editor replaces rows wholesale; a stale save is silent loss."""

	def test_a_stale_token_is_refused_before_the_rows_are_replaced(self):
		"""Two tabs, one draft. The second save must not overwrite the first.

		The rows are substituted, not merged, so a conflict leaves no trace in the
		document — the only chance to catch it is before ``save`` runs."""
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		with self.assertRaises(ctx.frappe.TimestampMismatchError):
			money.update_journal_entry(
				"JV-00001",
				"2026-08-19",
				BALANCED_ROWS,
				modified="2026-08-19 09:00:00",
			)

		self.assertIn("check_concurrency", ctx.trace)
		self.assertNotIn("save", ctx.trace)

	def test_the_concurrency_check_runs_after_the_write_permission_check(self):
		"""Order matters in both directions.

		Before ``save``, or it guards nothing. After ``_assert_can_write``, or the
		endpoint tells a caller without write permission whether the document
		exists and when it last changed."""
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		money.update_journal_entry(
			"JV-00001",
			"2026-08-19",
			BALANCED_ROWS,
			modified="2026-08-19 10:00:00",
		)

		self.assertLess(ctx.trace.index("can_write:write"), ctx.trace.index("check_concurrency"))
		self.assertLess(ctx.trace.index("check_concurrency"), ctx.trace.index("save"))

	def test_a_caller_that_sends_no_token_still_saves(self):
		"""``modified`` is deliberately optional.

		``check_concurrency`` rejects a MISSING token on an existing document
		(``_common.check_concurrency``: "Stale request: reload the document"), so
		calling it unconditionally would 500 every save the current form makes —
		it sends the token to submit/cancel/delete but not to update. The guard is
		therefore armed by the caller; this test pins the compatibility promise so
		that removing it is a deliberate act, not an accident."""
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		money.update_journal_entry("JV-00001", "2026-08-19", BALANCED_ROWS)

		self.assertIn("save", ctx.trace)


class FrozenPeriodTest(unittest.TestCase):
	"""A7 — a frozen period must stop the entry where the date is typed.

	ERPNext applies `acc_frozen_upto` when the GL is written, i.e. at submit. So a
	draft dated inside a closed period saved, listed and looked real, then failed
	at submit with an untranslated ERPNext message. What is left behind is the
	worst artefact this module can produce: a document that exists in the entry
	list and nowhere in the trial balance.
	"""

	FROZEN_UPTO = "2026-07-31"

	def test_a_new_entry_inside_the_frozen_period_is_refused_before_it_is_created(self):
		money, ctx = _load_money(accounts=BASE_ACCOUNTS, acc_frozen_upto=self.FROZEN_UPTO)

		with self.assertRaises(Exception) as caught:
			money.create_journal_entry("Test Co", "2026-07-15", BALANCED_ROWS)

		self.assertIn("2026-07-31", str(caught.exception))
		self.assertNotIn("insert", ctx.trace)

	def test_the_refusal_is_translated(self):
		"""The whole reason for owning this check is that ERPNext's is English-only.
		A refusal the accountant cannot read is indistinguishable from a bug."""
		money, _ctx = _load_money(accounts=BASE_ACCOUNTS, acc_frozen_upto=self.FROZEN_UPTO)

		with self.assertRaises(Exception) as caught:
			money.create_journal_entry("Test Co", "2026-07-15", BALANCED_ROWS)

		self.assertIn(I18N, str(caught.exception))

	def test_editing_a_draft_into_the_frozen_period_is_refused_before_the_save(self):
		money, ctx = _load_money(accounts=BASE_ACCOUNTS, acc_frozen_upto=self.FROZEN_UPTO)

		with self.assertRaises(Exception):
			money.update_journal_entry("JV-00001", "2026-07-15", BALANCED_ROWS)

		self.assertNotIn("save", ctx.trace)

	def test_the_freeze_date_itself_is_closed_and_the_next_day_is_open(self):
		"""`acc_frozen_upto` is inclusive in ERPNext. An off-by-one here either
		blocks a legal posting or lets an illegal one through — and the second
		only surfaces at submit, which is exactly the failure being fixed."""
		money, _ctx = _load_money(accounts=BASE_ACCOUNTS, acc_frozen_upto=self.FROZEN_UPTO)
		with self.assertRaises(Exception):
			money.create_journal_entry("Test Co", self.FROZEN_UPTO, BALANCED_ROWS)

		money, ctx = _load_money(accounts=BASE_ACCOUNTS, acc_frozen_upto=self.FROZEN_UPTO)
		money.create_journal_entry("Test Co", "2026-08-01", BALANCED_ROWS)
		self.assertIn("insert", ctx.trace)

	def test_the_role_that_may_post_to_a_closed_period_still_may(self):
		"""ERPNext grants `frozen_accounts_modifier` the right to post into the
		frozen range; that is the person whose job is fixing a closed period. A
		check stricter than the ledger's would take away the only tool they have."""
		money, ctx = _load_money(
			accounts=BASE_ACCOUNTS,
			acc_frozen_upto=self.FROZEN_UPTO,
			frozen_accounts_modifier="Accounts Manager",
			roles=("Accounts Manager",),
		)

		money.create_journal_entry("Test Co", "2026-07-15", BALANCED_ROWS)

		self.assertIn("insert", ctx.trace)

	def test_no_freeze_configured_blocks_nothing(self):
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		money.create_journal_entry("Test Co", "2020-01-01", BALANCED_ROWS)

		self.assertIn("insert", ctx.trace)


class CreateAndPostTest(unittest.TestCase):
	"""B4 — "save and post" as one call, without becoming a way around anything."""

	def test_the_default_is_still_a_draft(self):
		"""Every existing caller omits the flag and must keep getting a draft."""
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		result = money.create_journal_entry("Test Co", "2026-08-19", BALANCED_ROWS)

		self.assertNotIn("submit", ctx.trace)
		self.assertEqual(result["docstatus"], 0)

	def test_submitting_posts_the_entry_in_the_same_call(self):
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		result = money.create_journal_entry("Test Co", "2026-08-19", BALANCED_ROWS, submit=True)

		self.assertLess(ctx.trace.index("insert"), ctx.trace.index("submit"))
		self.assertEqual(result["docstatus"], 1)

	def test_submit_permission_is_checked_on_the_document_before_it_posts(self):
		"""Insert permission is not submit permission. A user allowed to prepare
		entries but not to post them must not gain the ledger through a flag."""
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		money.create_journal_entry("Test Co", "2026-08-19", BALANCED_ROWS, submit=True)

		self.assertLess(ctx.trace.index("can_write:submit"), ctx.trace.index("submit"))

	def test_a_string_zero_does_not_post(self):
		"""Whitelisted endpoints are reached over HTTP, where every argument is a
		string: `submit="0"` is exactly what a form sends for an unticked box, and
		a bare `if submit:` would post a journal the user asked to keep as a draft.
		Posting is not reversible — it takes a cancellation, in the ledger, forever."""
		money, ctx = _load_money(accounts=BASE_ACCOUNTS)

		money.create_journal_entry("Test Co", "2026-08-19", BALANCED_ROWS, submit="0")

		self.assertNotIn("submit", ctx.trace)

	def test_posting_does_not_skip_the_validation_the_draft_path_runs(self):
		"""The flag is a shortcut through the UI, never through the rules."""
		money, ctx = _load_money(accounts=BASE_ACCOUNTS, acc_frozen_upto="2026-07-31")

		with self.assertRaises(Exception):
			money.create_journal_entry("Test Co", "2026-07-15", BALANCED_ROWS, submit=True)
		self.assertNotIn("insert", ctx.trace)

		money, ctx = _load_money(accounts=BASE_ACCOUNTS)
		unbalanced = [
			{"account": CASH, "debit": 1000, "credit": 0},
			{"account": SALES, "debit": 0, "credit": 900},
		]
		with self.assertRaises(Exception):
			money.create_journal_entry("Test Co", "2026-08-19", unbalanced, submit=True)
		self.assertNotIn("insert", ctx.trace)


if __name__ == "__main__":
	unittest.main()
