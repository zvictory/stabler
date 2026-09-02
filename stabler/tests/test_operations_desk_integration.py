"""Against a real bench: `operations_desk` refuses different things for
different reasons, and says which one it did.

Three of its four permission gates are asserted here by calling the endpoint and
reading the sentence back, plus the company-module half of one of them. The
fourth -- the tenant-scope check -- is not, and the last paragraph of WHAT IS NOT
CLAIMED HERE says what it cost to find that out.

Every other test of this endpoint reads its source. `test_tender_desk_api.py`
scans `stabler/api/tender_desk.py` as text; `test_operations_desk_source.py`
scans the Vue file; `test_desk_rules.py` executes `_desk_rules` in a site-free
process. Those cover a lot, and none of them can answer the one question the
2026-09-02 P1 was about: when a reader is turned away, WHICH gate turned them
away. Four `frappe.throw(..., frappe.PermissionError)` sites stand between the
request and the desk, three of them carrying the identical sentence "Not
permitted", and a source scanner cannot see which one fired -- only a call can.

That mattered because the client renders the server's own sentence now. A
sourcing user who typed `?view=director` into the address bar and a finance user
whose roles open no desk at all were being told the same thing, and only one of
them has a recovery action ("remove the view from the address"). The gate that
fires decides which sentence the reader gets, so the gate that fires is the
thing that has to be pinned.

Measured while writing this module: `_MODULE_ROLES["tender"]`
(`api/organization.py:137-147`) grants the tender module to `Stabler Tender
Finance`, and that role appears in none of the four `_TENDER_VIEW_ROLES` entries
(`api/tender.py:1863-1880`). So the third refusal -- module yes, no view, no
`view` argument in the request -- is not hypothetical: it is what the finance
role gets today, on any site, with a URL carrying no view at all. That is the
fixture below.

Deliberately kept OUT of `.github/frappe-free-tests.txt`, so `BENCH_TESTS`
collects it and only `make test-bench` runs it -- the same split, and the same
reason, as `test_tender_board_funnel_integration.py`.

It also does not skip. A missing Role and a company with the tender module off
are both things a fixture can create, so it creates them. A site without the
`crm` app is not: `operations_desk` opens by probing `CRM Deal` columns, so on
such a site it cannot answer at all, and this module fails with that sentence
rather than reporting the green of a suite that ran nothing. A module that skips
everything looks exactly like one that proved something.

WHAT IS NOT CLAIMED HERE
  - `_assert_company_scope`, the first of the four gates. Reaching it needs a
    company the reader is not scoped to, and genesis-test.local carries exactly
    one Company -- so the argument that would trip it does not exist there. The
    first version of this module created a second one and deleted it afterwards.
    That is why this paragraph is a measurement and not a guess: inserting a
    Company materialises a `Stabler Company Modules` child row through
    `get_company_module_row` (`stabler_settings.py:90-104`, which appends AND
    commits), deleting the Company leaves that row behind, and `Stabler Settings`
    is then unsaveable -- `LinkValidationError: Could not find Row #2` -- which
    broke every later test on the site, not only this module's. The row was
    removed by hand afterwards. Proving this gate live needs a site with two
    companies, or a fixture that cleans the settings row before the company; it
    does not need a test module that can leave the shared bench site wedged.
    The gate's position in the call order is pinned in `test_tender_desk_api.py`,
    which is where it stays for now.
  - The 403 the browser actually sees. These tests assert `frappe.PermissionError`
    and the sentence it carries. That Frappe maps that class to HTTP 403, and that
    `public/js/api/client.js` unwraps `_server_messages` into `err.message`, is the
    assumption `isForbidden()` rests on and it is asserted in neither half. A
    change to Frappe's exception→status mapping would break the screen with every
    test in this repository still green.
  - Anything the screen does with these fields. The five-state regions, the
    view-recovery hint, which region gets `role="alert"` -- all of that is pinned
    against the Vue source by `public/js/tests/operationsDesk.spec.js`. This module
    asserts what the SERVER sends. Nothing here renders anything.
  - That `unreadable` has a naturally occurring cause. It is observed by forcing
    `list_pending` to raise, because on this path no cheap real failure exists:
    `frappe.get_all` ignores permissions, and the one real `PermissionError` an
    approver could hit -- a company outside their Allowed Companies -- is refused
    by the desk's own `_assert_company_scope` two lines before the queue is asked
    for. What is proven is that the endpoint labels a failed read `unreadable`
    rather than an empty queue. Not that a real cause is still reachable.
  - The seeded approval requests' reference documents. They point at the Company
    itself, because nothing on this path resolves the reference: `list_pending`
    selects columns, and `_config_for("Company")` returns the disabled default
    without touching the row. A real Payment Entry would drag in the cash/bank
    leaf-account fixture `test_approvals_integration.py` skips on. If the desk ever
    renders the referenced document, this stops being adequate.
  - A wrong site timezone. `today` is asserted equal to `frappe.utils.today()` --
    the same call the endpoint makes -- so this catches the field disappearing or
    being computed twice across midnight, not a misconfigured site. The clock
    disagreement D18 is about is between the SERVER and the BROWSER, and the
    browser is not here.
  - Team load's arithmetic. `open_lots` / `overdue_lots` / `won_lots` are counted
    in `tender_desk.py` and asserted nowhere in this file; only the presence /
    absence split -- the `oversight` flag that tells "not your panel" apart from
    "no work in this company" -- is claimed.
  - That `oversight` is not merely `bool(team_load)`. Measured by mutation:
    replacing the flag with that expression breaks no test in this module,
    because it takes an oversight reader whose company holds NO lots to make the
    two disagree, and that needs a second company for the same reason the scope
    gate does. What is pinned live is that the flag follows the reader's role
    rather than a constant -- hardcoding it either way is caught. That it is
    STATED rather than inferred is pinned at the source level in both halves:
    `test_tender_desk_api.py` for the payload field, `operationsDesk.spec.js` for
    the client preferring it over its own length fallback.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api import tender_desk
from stabler.api.organization import _can_access_module
from stabler.api.tender import _tender_views
from stabler.stabler.doctype.stabler_settings.stabler_settings import get_company_module_row

# Three readers, three role states. The emails are stable so a re-run reuses
# them; the roles are RESET on every setUp rather than appended to, because
# every claim below is about a user holding exactly these roles and nothing
# else. `_ensure_user` in test_approvals_integration.py only ever appends,
# which is right for a fixture that wants a capability and wrong for one that
# wants a boundary.
FINANCE = "stabler-desk-finance@test.local"  # tender module, no view window
SOURCING = "stabler-desk-sourcing@test.local"  # exactly one view window
OUTSIDER = "stabler-desk-outsider@test.local"  # no tender module at all

# Created if the site lacks it. `Stabler Tender Finance` ships as a role in the
# module map but a site that never ran the tender role patch would silently give
# this user no roles at all -- and a user with no roles is refused by
# _require_tender, i.e. by the WRONG gate, with the test still green because the
# exception class matches. desk_access is explicit so User.set_system_user
# promotes the holder deterministically.
_TENDER_FINANCE_ROLE = "Stabler Tender Finance"
_TENDER_SOURCING_ROLE = "Stabler Tender Sourcing"


def _drop(doctype: str, name: str) -> None:
	"""Delete a fixture row and make the delete stick.

	Registered with `addCleanup`, which unittest runs AFTER tearDown -- so
	whether the row is still there depends on something this cleanup cannot see:
	tearDown's `frappe.db.rollback()` removes it if nothing committed after it
	was written, and leaves it if something did. Both happen in this module. The
	existence guard is what makes the cleanup right either way; without it a
	`delete_doc` on an already-rolled-back row raises out of a cleanup and masks
	whatever the test actually reported.
	"""
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	frappe.db.commit()


def _forget_settings() -> None:
	"""Drop the cached copy of the `Stabler Settings` singleton.

	Every read of the module flag goes through `frappe.get_single`, which serves
	a cached Document, and the two writers below go around it: `db.set_value`
	writes a child row without touching the parent, and `get_company_module_row`
	appends one from inside the app. Neither invalidates the cached parent, so a
	reader would keep seeing the flag's old value. This is called after each of
	them, and nowhere else -- the flag is otherwise never written.
	"""
	frappe.clear_document_cache("Stabler Settings", "Stabler Settings")


def _ensure_role(role: str) -> None:
	if frappe.db.exists("Role", role):
		return
	frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def _ensure_user(email: str, roles: list[str]) -> None:
	"""Idempotent user whose role set is exactly `roles`."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.set("roles", [])
	for role in roles:
		_ensure_role(role)
		user.append("roles", {"role": role})
	user.set("allowed_companies", [])
	user.save(ignore_permissions=True)
	frappe.db.commit()


class _DeskBenchFixture:
	"""A company with the tender module on, and the three readers.

	A plain mixin, deliberately NOT a `FrappeTestCase` subclass, so unittest does
	not collect it -- the shape `_IntakeBenchFixture` uses
	(`test_tender_intake_master_fields_integration.py`), and for the same reason.

	It does not reuse that fixture's `_enable_tender_module`, though the first
	version of this module did. That method opens the `Stabler Settings`
	singleton and SAVES it, once per setUp and once per tearDown, whether or not
	the flag needs changing -- 26 saves per run of this module, and on a site
	where tender is already on, 26 writes with nothing to write.

	`Stabler Settings` has more than one writer: the app saves it from
	`get_company_module_row` (`stabler_settings.py:90-104`, appends AND commits),
	and any other process on the same site saves it too. That produced
	`TimestampMismatchError` and one `QueryDeadlockError` on genesis-test.local,
	surfacing in whichever test opened the singleton next rather than in the one
	that wrote it -- and, because a bench site is shared, in OTHER suites running
	at the same time. A fixture whose writes can fail somebody else's unrelated
	test run is not a fixture worth keeping, however green its own module looks.

	So the flag is READ first and written only when it is wrong, and written as a
	child row rather than through the parent. A run on a tender-enabled company
	touches the singleton zero times.
	"""

	def setUp(self):
		# Probed, not skipped on. `operations_desk` opens with a has_column loop
		# over CRM Deal, and `has_column` raises TableMissingError rather than
		# returning False when the table is absent (.claude/rules/20-backend-
		# migrations.md) -- so a site without the crm app would fail this module
		# from inside the endpoint with an exception that names a column. It says
		# what is actually missing instead.
		self.assertTrue(
			frappe.db.table_exists("CRM Deal"),
			"this site does not carry CRM Deal; the Operations Desk cannot answer at all",
		)
		self.company = frappe.db.get_value("Company", {}, "name")
		self.assertTrue(self.company, "this site carries no Company; the desk cannot be called at all")
		self._prior_enable_tender = self._tender_module_flag()
		if not self._prior_enable_tender:
			self._set_tender_module(1)
		_ensure_user(FINANCE, [_TENDER_FINANCE_ROLE])
		_ensure_user(SOURCING, [_TENDER_SOURCING_ROLE])
		_ensure_user(OUTSIDER, [])

	def tearDown(self):
		frappe.set_user("Administrator")
		if not self._prior_enable_tender:
			self._set_tender_module(0)
		frappe.db.rollback()

	# ---- the company's tender switch -------------------------------------

	def _module_row(self) -> str:
		"""This company's `Stabler Company Modules` row, seeded if absent.

		Seeded through the app's own `get_company_module_row` rather than by
		appending here: that function is what production uses, it commits, and
		writing a second seeder would be a second definition of what a default
		row contains.
		"""
		filters = {
			"parenttype": "Stabler Settings",
			"parentfield": "company_modules",
			"company": self.company,
		}
		name = frappe.db.get_value("Stabler Company Modules", filters, "name")
		if not name:
			get_company_module_row(self.company)
			_forget_settings()
			name = frappe.db.get_value("Stabler Company Modules", filters, "name")
		self.assertTrue(name, f"no Stabler Company Modules row could be made for {self.company}")
		return name

	def _tender_module_flag(self) -> int:
		return int(frappe.db.get_value("Stabler Company Modules", self._module_row(), "enable_tender") or 0)

	def _set_tender_module(self, enabled: int) -> None:
		"""Set the company's tender flag to a KNOWN state.

		Not to its PRIOR state. `_IntakeBenchFixture._restore_tender_module`
		restores, which on a site that already runs tender is a no-op -- the first
		version of the module-switch test below "turned the module off" by calling
		it, and failed with "PermissionError not raised" because the prior value
		was 1.
		"""
		frappe.db.set_value("Stabler Company Modules", self._module_row(), "enable_tender", enabled)
		frappe.db.commit()
		# The flag is read back through `frappe.get_single`, which serves a cached
		# Document whose child rows this write did not touch.
		_forget_settings()

	def _desk(self, **kwargs) -> dict:
		return tender_desk.operations_desk(company=self.company, **kwargs)

	def _refusal(self, **kwargs) -> str:
		"""The sentence the endpoint refused with.

		`assertRaises` alone would pass for any of the gates, which is the entire
		defect this module exists for -- so every refusal test reads the message
		out and compares it, and the class is asserted separately because it is
		what becomes the 403 the client keys `forbidden` off."""
		with self.assertRaises(frappe.PermissionError) as caught:
			self._desk(**kwargs)
		return str(caught.exception)


class TestTheRefusalsAreToldApart(_DeskBenchFixture, FrappeTestCase):
	def test_the_fixture_puts_each_reader_in_the_role_state_the_tests_assume(self):
		# WHAT WOULD MAKE THIS FAIL: the role maps moving under the fixture --
		# `Stabler Tender Finance` gaining a view window, or losing its place in
		# _MODULE_ROLES["tender"]. Either one silently retargets every refusal
		# test below onto a DIFFERENT gate while they all keep passing, because
		# three of the four gates throw the identical sentence. Every assertion
		# in this class is "which gate fired", and that question is only
		# meaningful while each reader sits where this test says they sit.
		self.assertTrue(
			_can_access_module(FINANCE, "tender"),
			f"{_TENDER_FINANCE_ROLE} no longer opens the tender module; the no-view refusal is unreachable",
		)
		self.assertEqual(_tender_views(FINANCE), [], f"{_TENDER_FINANCE_ROLE} now opens a view window")
		self.assertEqual(
			_tender_views(SOURCING), ["sourcing"], "the sourcing reader no longer holds exactly one view"
		)
		self.assertFalse(_can_access_module(OUTSIDER, "tender"), "the outsider reached the tender module")

	def test_a_reader_with_the_module_but_no_view_is_refused_in_its_own_words(self):
		# WHAT WOULD MAKE THIS FAIL: this refusal collapsing into the generic
		# "Not permitted" the other three carry. It is the one refusal that is
		# reachable with NO view in the address bar, so it is the one where the
		# client's recovery line -- "remove the view from the address" -- is a
		# lie: there is nothing to remove. The screen prints the server's own
		# sentence precisely so these two cases read differently, which only
		# works while the server keeps saying two different things.
		message = self._refusal_as(FINANCE)
		self.assertIn("Access denied to Operations Desk", message)
		self.assertNotIn("Not permitted", message)

	def test_a_reader_without_the_tender_module_is_refused_before_any_view_is_considered(self):
		# WHAT WOULD MAKE THIS FAIL: the module gate moving below the view gate.
		# A user with no tender role would then be told which VIEW they lack --
		# an answer that invites them to try another view, when no view will ever
		# work. Order is the claim here, and it is invisible to a source scanner
		# that can see both calls but not which one runs first for a given user.
		self.assertEqual(self._refusal_as(OUTSIDER), "Not permitted")

	def test_naming_a_view_you_do_not_hold_is_refused_and_not_naming_one_is_not(self):
		# WHAT WOULD MAKE THIS FAIL: `_require_tender_view` losing its `if view:`
		# guard, or the fallback `view = raw_views[0]` being replaced by a
		# hardcoded default. Either turns an ordinary first paint -- no view in
		# the URL -- into a refusal for every reader whose window is not the
		# default one. Both halves are asserted together because the defect is
		# the RELATIONSHIP: the gate must fire for a named view and stay silent
		# for an unnamed one.
		frappe.set_user(SOURCING)
		self.assertEqual(self._refusal(view="director"), "Not permitted")
		self.assertEqual(
			self._desk()["view"],
			"sourcing",
			"a request naming no view was not answered with the reader's own",
		)

	def test_the_company_module_switch_refuses_by_name_and_not_by_role(self):
		# WHAT WOULD MAKE THIS FAIL: `_require_tender` folding its two halves
		# into one message. Tender is opt-in per company
		# (.claude/rules/30-tenant-modules.md), so "your roles do not open this"
		# and "this company does not run this module" are answered by different
		# people -- an administrator flips one, nobody can flip the other. A
		# reader who is told the wrong one goes to the wrong person.
		#
		# Flipped to 0 explicitly rather than by restoring the flag's prior value.
		# On genesis-test.local that prior value is already 1, so the first
		# version of this test turned the module "off" in a company where it
		# stayed on, and failed with "PermissionError not raised". Restoring is
		# not disabling on any site that already runs tender -- which is every
		# site this test says anything about.
		self._set_tender_module(0)
		try:
			frappe.set_user(SOURCING)
			message = self._refusal()
			self.assertIn("Tender module is not enabled", message)
			self.assertIn(self.company, message, "the refusal does not say which company is off")
		finally:
			frappe.set_user("Administrator")
			self._set_tender_module(1)

	# ---- fixture helpers -------------------------------------------------

	def _refusal_as(self, user: str) -> str:
		frappe.set_user(user)
		return self._refusal()


class TestWhatTheDeskSaysAboutItselfWhenItAnswers(_DeskBenchFixture, FrappeTestCase):
	"""The three fields added so the screen could tell an ANSWER from a FAILURE.

	`approvals_state`, `oversight` and `today` all exist because an empty list
	used to mean four different things at once, and the screen had to guess.
	"""

	def setUp(self):
		super().setUp()
		# Two pending requests, so "the queue is empty" and "the queue is not
		# yours" are distinguishable on real rows rather than on two empty lists.
		self.mine = self._approval_request(requested_by="Administrator")
		self.theirs = self._approval_request(requested_by=SOURCING)

	def test_the_desk_states_the_calendar_day_it_reasoned_with(self):
		# WHAT WOULD MAKE THIS FAIL: `today` being dropped, or recomputed per
		# consumer. Every severity, all four counters and the calendar window are
		# derived from one `today_str`; the client used to re-filter the same
		# predicate with the BROWSER's date, so between 00:00 and 05:00 in
		# Tashkent against a UTC host the Today chip and the list it filters
		# showed different numbers, each internally consistent. The fix is that
		# the server says which day it used -- which is worth nothing if the
		# calendar it ships starts on a different one.
		payload = self._desk()
		self.assertEqual(payload["today"], frappe.utils.today())
		self.assertEqual(len(payload["calendar"]), 7)
		self.assertEqual(
			payload["calendar"][0]["date"],
			payload["today"],
			"the week the desk shipped does not start on the day it says it reasoned with",
		)

	def test_oversight_follows_the_readers_role_and_not_a_constant(self):
		# WHAT WOULD MAKE THIS FAIL: `oversight` leaving the payload, or being
		# pinned to either constant -- both halves are asserted because either
		# constant satisfies one reader and lies to the other. team_load is built
		# only under `if oversight:`, so a sourcing reader and a director of a
		# company holding no lots both receive []; the two sentences are opposites
		# -- "this panel is not yours to read" and "there is nothing in this
		# company to spread" -- and the list alone cannot separate them.
		#
		# What this does NOT catch, measured: replacing the flag with
		# `bool(team_load)` -- the exact inference it exists to remove -- kills
		# nothing here, because on a one-company site the two agree for both
		# readers. Separating them needs an oversight reader whose company holds
		# no lots, i.e. a second company. See WHAT IS NOT CLAIMED HERE.
		frappe.set_user(SOURCING)
		theirs = self._desk()
		self.assertIs(theirs["oversight"], False)
		self.assertEqual(theirs["team_load"], [], "a non-oversight reader was sent a team load")
		frappe.set_user("Administrator")
		self.assertIs(self._desk()["oversight"], True)

	def test_an_approver_gets_the_queue_read_and_split_by_who_can_answer_it(self):
		# WHAT WOULD MAKE THIS FAIL: the partition drifting back to `oversight`.
		# You cannot approve your own request, so a director's own pending rows
		# are not decisions they can make -- the old expression OR'd `oversight`
		# in and swallowed them into "yours to decide", promising actions that
		# would be refused, and left waiting_others structurally 0.
		payload = self._desk()
		self.assertEqual(payload["approvals_state"], "read")
		names = {d["name"] for d in payload["decisions"]}
		self.assertIn(self.theirs, names, "a request raised by someone else is not mine to decide")
		self.assertNotIn(self.mine, names, "my own request was offered to me as a decision")
		self.assertEqual(payload["counters"]["awaiting_me"], len(payload["decisions"]))

	def test_a_non_approver_is_told_the_queue_is_not_theirs_and_not_that_it_is_empty(self):
		# WHAT WOULD MAKE THIS FAIL: `not_yours` collapsing back into an empty
		# list. This is the common case -- most desk readers are not approvers --
		# and it is an ANSWER: the queue exists, it is not mine, so a plan without
		# it is complete for me. Reported as a gap it would fire every day for
		# everyone and bury the real one. The two seeded rows are what makes the
		# distinction observable: `decisions == []` here is TRUE and the queue is
		# NOT empty, which is exactly the pair an empty list cannot express.
		frappe.set_user(SOURCING)
		payload = self._desk()
		self.assertEqual(payload["approvals_state"], "not_yours")
		self.assertEqual(payload["decisions"], [])
		frappe.set_user("Administrator")
		# The fixture's own two rows, not a count of the company's queue: another
		# module's leftovers would satisfy a count and prove nothing about these.
		still_pending = frappe.get_all(
			"Stabler Approval Request",
			filters={"name": ["in", [self.mine, self.theirs]], "status": "Pending"},
			pluck="name",
		)
		self.assertEqual(
			sorted(still_pending),
			sorted([self.mine, self.theirs]),
			"the fixture's pending rows are gone, so an empty decision list proves nothing",
		)

	def test_a_queue_that_could_not_be_read_is_not_reported_as_a_queue_with_nothing_in_it(self):
		# WHAT WOULD MAKE THIS FAIL: `except Exception: approvals = []` coming
		# back without a state name. The desk's empty state is a claim about the
		# world -- "all items in this view are up to date" -- and it was being
		# made out of a swallowed exception: two counters at 0, an empty Decision
		# box, and a plan asserting everything was current. Four confident
		# statements, none of them known. The failure is injected because no cheap
		# real cause survives on this path; the claim is about the handling.
		with patch.object(tender_desk, "list_pending", side_effect=RuntimeError("queue is down")):
			payload = self._desk()
		self.assertEqual(payload["approvals_state"], "unreadable")
		self.assertEqual(payload["decisions"], [])
		self.assertEqual(payload["counters"]["awaiting_me"], 0)

	# ---- fixture helpers -------------------------------------------------

	def _approval_request(self, *, requested_by: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Stabler Approval Request",
				# A stand-in reference: nothing on this path resolves it. See
				# WHAT IS NOT CLAIMED HERE.
				"reference_doctype": "Company",
				"reference_name": self.company,
				"company": self.company,
				"status": "Pending",
				"requested_by": requested_by,
				"title": f"Desk integration fixture ({requested_by})",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(_drop, "Stabler Approval Request", doc.name)
		return doc.name


class TestTheDeskCountsTheRowsItCouldNotRead(_DeskBenchFixture, FrappeTestCase):
	"""`skipped` and `calendar_past`, over lots that actually exist.

	Needs `CRM Deal`. A site without the crm app cannot host these claims, and
	this class says so by failing rather than by skipping -- a module that skips
	everything reports the same green as one that proved something.
	"""

	def setUp(self):
		super().setUp()
		for doctype in ("CRM Deal", "CRM Organization", "CRM Deal Status"):
			self.assertTrue(
				frappe.db.table_exists(doctype),
				f"this site does not carry {doctype}; the Operations Desk has nothing to read",
			)
		self.assertTrue(
			frappe.db.has_column("CRM Deal", "custom_tender_intake"),
			"this site has not run the tender intake column patch; every deadline reads as absent",
		)
		self.status = frappe.db.get_value("CRM Deal Status", {"type": "Open"}, "name")
		self.assertTrue(self.status, "this site has no open CRM Deal Status to put a lot in")
		self.organization = self._organization()
		# One lot whose deadline will not parse, one whose deadline has passed.
		self.deal_unparseable = self._lot({"lot_no": "DESK-BAD", "bid_deadline": "not-a-date"})
		self.deal_overdue = self._lot({"lot_no": "DESK-PAST", "bid_deadline": "2020-01-15"})

	def test_a_deadline_that_will_not_parse_is_counted_and_not_silently_dropped(self):
		# WHAT WOULD MAKE THIS FAIL: `skipped` leaving the payload, or build_plan
		# dropping an unparseable row without counting it. A lot with a malformed
		# deadline produces no plan item, and the panel then tells the reader the
		# view is up to date -- the one sentence that must never be produced by a
		# row nobody could read. Measured as a DELTA across the same site rather
		# than as an absolute, so other unparseable rows elsewhere cancel out and
		# the claim stays about this lot.
		before = self._desk()["skipped"]
		self._rewrite_deadline(self.deal_unparseable, "2020-02-20")
		after = self._desk()["skipped"]
		self.assertEqual(
			before - after, 1, "repairing one unreadable deadline did not change the skipped count by one"
		)

	def test_an_overdue_row_reaches_the_past_bucket_and_never_a_day_cell(self):
		# WHAT WOULD MAKE THIS FAIL: the past bucket being dropped, or its
		# boundary loosening to `<=`. A day's count is `due == that day` and
		# everything overdue is dated in the past, so before the bucket existed
		# the desk's loudest row was absent from all seven cells while the Overdue
		# counter directly above them read 1 -- two regions of one screen unable
		# to agree by construction. A `<=` boundary is the same defect with the
		# opposite sign: today's deadline counted twice, and the region adding up
		# to more work than the plan holds.
		payload = self._desk()
		today = payload["today"]
		overdue_in_plan = [i for i in payload["plan"] if i.get("due") and str(i["due"]) < today]
		self.assertIn(
			self.deal_overdue,
			{i.get("reference_name") for i in overdue_in_plan},
			"the seeded past-deadline lot produced no overdue plan row, so this test proves nothing",
		)
		self.assertEqual(payload["calendar_past"]["count"], len(overdue_in_plan))
		for cell in payload["calendar"]:
			for item in cell["items"]:
				self.assertGreaterEqual(
					str(item["due"]), today, f"a past-due row is sitting in the {cell['date']} cell"
				)

	def test_an_oversight_reader_of_a_company_with_lots_gets_a_team_load(self):
		# WHAT WOULD MAKE THIS FAIL: team_load being built from site users rather
		# than from the people the lots point at. It is a map keyed by deal owner,
		# so it holds a row per owner regardless of how much is open -- which is
		# why `[]` from an oversight reader means the company has no lots at all,
		# not that everyone is idle. That reading is what the `oversight` flag
		# lets the client state, and it is only true while the list follows the
		# lots.
		payload = self._desk()
		self.assertIs(payload["oversight"], True)
		self.assertTrue(
			payload["team_load"], "a company holding two seeded lots reported nobody carrying any"
		)

	# ---- fixture helpers -------------------------------------------------

	def _organization(self) -> str:
		title = "UAT Operations Desk Integration Fixture"
		existing = frappe.db.exists("CRM Organization", {"organization_name": title})
		if existing:
			return existing
		org = frappe.new_doc("CRM Organization")
		org.organization_name = title
		org.insert(ignore_permissions=True, ignore_mandatory=True)
		return org.name

	def _lot(self, intake: dict) -> str:
		"""A CRM Deal carrying its tender facts in `custom_tender_intake`.

		Written straight to the column instead of through `save_deal_intake`,
		which is what `test_tender_intake_master_fields_integration.py` uses. That
		endpoint enforces the ADR-202/203/205 contract and would refuse
		`bid_deadline: "not-a-date"` -- and a payload that cannot be stored is
		exactly the payload whose handling `skipped` exists for. The column is
		what `operations_desk` reads (`_parse_intake` on line 116), so this is
		the real input, not a stand-in.

		`status` / `deal_owner` / `next_action_at` are set for the reason the
		model fixture documents: `crm.validate_crm_deal_hygiene` requires an owner
		and a dated next action on an open deal whenever the site-wide
		`enforce_crm_next_action` switch is on, and a fixture cannot see that
		switch from here.
		"""
		deal = frappe.new_doc("CRM Deal")
		deal.company = self.company
		deal.organization = self.organization
		deal.status = self.status
		deal.deal_owner = frappe.session.user
		deal.next_action_at = frappe.utils.now_datetime()
		deal.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.set_value("CRM Deal", deal.name, "custom_tender_intake", json.dumps(intake))
		self.addCleanup(_drop, "CRM Deal", deal.name)
		return deal.name

	def _rewrite_deadline(self, deal: str, deadline: str) -> None:
		raw = frappe.db.get_value("CRM Deal", deal, "custom_tender_intake")
		intake = json.loads(raw)
		intake["bid_deadline"] = deadline
		frappe.db.set_value("CRM Deal", deal, "custom_tender_intake", json.dumps(intake))
