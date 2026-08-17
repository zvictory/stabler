"""The remittance read layer: what it must never return, and what it must not invent.

`remittance_queries` is the only place in the app that reads Remittance Transfer
for a browser, so three separate things have to hold and each is tested the way
it can actually fail.

**The pickup code.** Two guards, and the test proves both are *wired*, not merely
present. The field list is asserted against a whitelist of expressions in the
source, so a projection added later cannot reach a query unguarded; and the
response guard is proved behaviourally by handing the endpoint a database that
returns the digest anyway — every endpoint must raise rather than serialise it.
A source-only test would pass on code that calls the guard and ignores it.

**The permission hook.** `frappe.get_all` sets `ignore_permissions`, which turns
`permissions.remittance_transfer_query` off and lets a cashier read another
company's transfers. The fake `frappe` below therefore has no `get_all` attribute
at all: a module that reaches for one raises `AttributeError` in every test here,
not just in the one that greps for it.

**The numbers nobody defined.** `expires_at` is on the doctype and nothing in the
app writes it. The two expiry queues must therefore say "no policy is configured"
rather than "nothing is expiring" — opposite claims, and only one is true. Both
directions are tested: empty-and-flagged with no data, and populated-and-flagged
the moment a row carries an expiry, which is what proves the flag is measured
instead of hard-coded.

Bench-free: `make check` does not run the bench set, so a test needing one would
not gate a push. The ledger side of these figures is a separate bench test.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_remittance_queries -v
"""

from __future__ import annotations

import datetime
import importlib
import os
import re
import types
import unittest

from stabler.api import _remittance_actions as actions
from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.remittance_queries"
_SRC_PATH = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api", "remittance_queries.py"
)

with open(_SRC_PATH, encoding="utf-8") as _handle:
	_SRC = _handle.read()

_SANDBOX = ModuleSandbox()

_FAKED = (
	_MODULE,
	"frappe",
	"frappe.utils",
	"stabler.api._common",
	"stabler.api.approvals",
	"stabler.api.remittance_commands",
)

TRANSFER = "Remittance Transfer"
EVENT = "Remittance Event"
JOURNAL = "Journal Entry"

NOW = datetime.datetime(2026, 8, 17, 11, 0, 0)
TODAY = "2026-08-17"

CASHIER = ("Remittance Cashier",)
VIEWER = ("Remittance Viewer",)
MANAGER = ("Remittance Finance Manager",)

#: The six queues, written out here so a rename in the module has to be a
#: deliberate edit in two places rather than a silent one in the screen contract.
EXPECTED_QUEUES = (
	"ready_for_payout",
	"expiring_12h",
	"expired_refund_required",
	"refund_awaiting_approval",
	"locked_pickup_code",
	"accounting_exception",
)


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


# --------------------------------------------------------------------------- #
# A database small enough to reason about and strict enough to refuse
# --------------------------------------------------------------------------- #
def _is_bare_date(value) -> bool:
	text = str(value)
	return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _cmp(value) -> str:
	"""Everything compares as text.

	Datetimes render ISO-shaped, so lexicographic order is chronological order and
	a stored string can be compared with a `datetime` bound without either side
	being converted first — which is exactly what the real query layer does when
	`add_to_date` hands it a `datetime` and the column holds a string.
	"""
	return "" if value is None else str(value)


def _matches(row: dict, field: str, condition) -> bool:
	value = row.get(field)
	if not isinstance(condition, (list, tuple)):
		return value == condition

	operator, operand = condition[0], condition[1]
	operator = str(operator).lower()
	if operator == "in":
		return value in tuple(operand)
	if operator == "not in":
		# SQL semantics on purpose: NOT IN over NULL is NULL, which is not true.
		# This is the trap `_refund_open` exists to route around, and a forgiving
		# fake here would make that test a tautology.
		return value is not None and value not in tuple(operand)
	if operator == "is":
		filled = value not in (None, "")
		return filled if str(operand) == "set" else not filled
	if operator == "between":
		low, high = operand
		low = f"{low} 00:00:00" if _is_bare_date(low) else _cmp(low)
		high = f"{high} 23:59:59.999999" if _is_bare_date(high) else _cmp(high)
		return value is not None and low <= _cmp(value) <= high
	if operator == "like":
		return str(operand).strip("%").lower() in _cmp(value).lower()
	if operator == "!=":
		return value != operand
	if operator == ">=":
		return value is not None and _cmp(value) >= _cmp(operand)
	if operator == "<=":
		return value is not None and _cmp(value) <= _cmp(operand)
	if operator == "<":
		return value is not None and _cmp(value) < _cmp(operand)
	raise AssertionError(f"the fake database does not implement operator {operator!r}")


class _FakeDB:
	def __init__(self):
		self.transfers: list[dict] = []
		self.events: list[dict] = []
		self.entries: list[dict] = []
		#: Every field list any query was handed, so a leak can be asserted against
		#: what reached the database rather than against what a docstring claims.
		self.selected: list[list[str]] = []
		#: A database that hands back the digest whatever was selected. Not a
		#: hypothetical: `pickup_code_hash` is a real column on the real table, and
		#: this is the shape a projection bug takes.
		self.leak = False
		#: Whether the caller may read Journal Entry. `False` is the real state for
		#: all four remittance roles — erpnext's journal_entry.json grants read to
		#: Accounts User, Accounts Manager and Auditor only, and v87 adds no DocPerm
		#: — so a read attempted anyway raises, exactly as `db_query` would. Default
		#: `True` so the tests that are about something else keep meaning what they
		#: meant; the tests that are about this flip it.
		self.journal_readable = True
		self._seq = 0

	def add_transfer(self, **fields) -> str:
		self._seq += 1
		name = fields.pop("name", None) or f"REM-2026-{self._seq:05d}"
		row = {
			"name": name,
			"client_request_id": f"reg-{self._seq}",
			"company": "Mikas",
			"sender_name": "Amina",
			"receiver_name": "Bekzod",
			"origin_branch": "Tashkent",
			"origin_city": "Tashkent",
			"destination_branch": "Samarkand",
			"destination_city": "Samarkand",
			"send_currency": "USD",
			"receive_currency": "EUR",
			"commission_mode": "Exclusive",
			"commission_pct": 1.0,
			"principal": 1000.0,
			"commission": 10.0,
			"tendered": 1010.0,
			"receiver_amount": 920.0,
			"exchange_rate": 0.92,
			"register_base_rate": 12600.0,
			"operational_status": "Registered",
			"accounting_status": "Posted",
			"verification_status": "Active",
			"refund_status": "None",
			"code_locked": 0,
			"code_attempts": 0,
			"code_locked_at": None,
			"expires_at": None,
			"registered_by": "cashier@example.com",
			"registered_at": f"{TODAY} 09:00:00",
			"register_journal_entry": "JE-REM-0001",
			"payout_journal_entry": None,
			"refund_journal_entry": None,
			"owner": "cashier@example.com",
			"creation": f"{TODAY} 08:59:00",
			"modified": f"{TODAY} 10:00:00",
		}
		row.update(fields)
		self.transfers.append(row)
		return name

	def add_event(self, transfer: str, event_type: str, occurred_at: str, **fields) -> None:
		row = {
			"name": f"EVT-{len(self.events) + 1:05d}",
			"transfer": transfer,
			"event_type": event_type,
			"occurred_at": occurred_at,
			"actor": "cashier@example.com",
			"branch": "Tashkent",
			"client_request_id": "reg-1",
			"details": "",
		}
		row.update(fields)
		self.events.append(row)

	def add_entry(self, name: str, stage: str) -> None:
		self.entries.append(
			{
				"name": name,
				"posting_date": TODAY,
				"docstatus": 1,
				"total_debit": 1010.0,
				"total_credit": 1010.0,
				"user_remark": f"Remittance — {stage}",
				"stabler_remittance_stage": stage,
			}
		)

	# --- the frappe.get_list surface --------------------------------------- #
	def _table(self, doctype: str) -> list[dict]:
		if doctype == TRANSFER:
			return self.transfers
		if doctype == EVENT:
			return self.events
		if doctype == JOURNAL:
			if not self.journal_readable:
				# frappe/model/db_query.py:621 `_set_permission_map` calls
				# `frappe.has_permission(..., throw=True)` on every doctype a query
				# touches. A read issued without the permission does not come back
				# empty — it takes the whole request down with it.
				raise PermissionError("No permission to read Journal Entry")
			return self.entries
		raise AssertionError(f"unexpected read of {doctype}")

	def get_list(
		self,
		doctype,
		filters=None,
		or_filters=None,
		fields=None,
		order_by=None,
		limit_page_length=None,
		limit_start=None,
	):
		self.selected.append(list(fields or []))
		rows = [
			row
			for row in self._table(doctype)
			if all(_matches(row, field, condition) for field, condition in (filters or {}).items())
		]
		if or_filters:
			rows = [
				row
				for row in rows
				if any(_matches(row, field, [operator, operand]) for field, operator, operand in or_filters)
			]
		for clause in reversed([part.strip() for part in (order_by or "").split(",") if part.strip()]):
			field, _sep, direction = clause.partition(" ")
			rows.sort(key=lambda row, f=field: _cmp(row.get(f)), reverse=direction.strip() == "desc")

		start = int(limit_start or 0)
		rows = rows[start:]
		if limit_page_length:
			rows = rows[: int(limit_page_length)]
		projected = [{field: row.get(field) for field in (fields or [])} for row in rows]
		if self.leak:
			for row in projected:
				row["pickup_code_hash"] = "d41d8cd9"
		return projected


# --------------------------------------------------------------------------- #
# Loading the module under fakes
# --------------------------------------------------------------------------- #
def _load(db: _FakeDB, *, roles=CASHIER):
	_SANDBOX.evict(*_FAKED)

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn
	frappe.get_roles = lambda user=None: list(roles)
	frappe.get_list = db.get_list
	frappe.has_permission = lambda doctype, ptype="read", *_a, **_k: (
		db.journal_readable if doctype == JOURNAL else True
	)
	frappe.PermissionError = PermissionError
	frappe.session = types.SimpleNamespace(user="cashier@example.com")
	# `frappe.get_all` is deliberately NOT defined. It sets ignore_permissions,
	# which switches the company row filter off; a module that reaches for one
	# fails here with AttributeError instead of quietly leaking another tenant.

	utils = types.ModuleType("frappe.utils")
	utils.add_to_date = lambda value, hours=0, **_k: value + datetime.timedelta(hours=hours)
	utils.cint = lambda value: int(value or 0)
	utils.flt = lambda value, precision=None: (
		round(float(value or 0), precision) if precision is not None else float(value or 0)
	)
	utils.get_datetime = lambda value: (
		value if isinstance(value, datetime.datetime) else datetime.datetime.fromisoformat(str(value))
	)
	utils.now_datetime = lambda: NOW
	utils.nowdate = lambda: TODAY
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_a, **_k: None
	common._require_company = lambda company: company

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: None

	commands = types.ModuleType("stabler.api.remittance_commands")
	commands._max_code_attempts = lambda company: 5
	commands._send_precision = lambda: 2

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.api.remittance_commands": commands,
		}
	)
	return importlib.import_module(_MODULE)


def _seeded(**kwargs) -> tuple:
	db = _FakeDB()
	queries = _load(db, **kwargs)
	return db, queries


# --------------------------------------------------------------------------- #
# 1. The pickup code never leaves
# --------------------------------------------------------------------------- #
class PickupCodeTest(unittest.TestCase):
	#: Every expression this module is allowed to hand a query as its field list.
	#: Anything else — a raw tuple, a hand-built list — has skipped the guard.
	ALLOWED_FIELD_SOURCES = frozenset(
		{
			"safe",
			'["name"]',
			'["transfer"]',
			"list(actions.assert_safe_fields(_DETAIL_FIELDS))",
			"list(actions.assert_safe_fields(_EVENT_FIELDS))",
			"list(actions.assert_safe_fields(_JOURNAL_FIELDS))",
		}
	)

	def test_no_projection_names_the_code_or_its_digest(self):
		forbidden = set(actions.FORBIDDEN_READ_FIELDS)
		projections = re.findall(r"^(_\w*FIELDS) = \(\n(.*?)^\)", _SRC, re.M | re.S)
		self.assertTrue(projections, "no field tuples found — the source scan is looking at nothing")
		for name, body in projections:
			named = set(re.findall(r'"([a-z_]+)"', body))
			self.assertEqual(set(), named & forbidden, f"{name} selects a forbidden column")

	def test_every_field_list_reaching_a_query_came_from_the_guard(self):
		# The behavioural half below proves the guard REFUSES; this proves nothing
		# routes around it. A projection added later and passed raw fails here.
		used = re.findall(
			r'(?:\bfields=|"fields":\s*)'
			r"(list\(actions\.assert_safe_fields\(\w+\)\)|\[[^\]]*\]|\w+)",
			_SRC,
		)
		self.assertTrue(used, "no field arguments found — the source scan is looking at nothing")
		# `safe` is on the whitelist above, so the whitelist is only worth
		# anything while `safe` is what the guard returned. Pinned to the choke
		# point itself: without this line, replacing the guard with `list(fields)`
		# leaves every `fields=safe` call site looking correct.
		self.assertIn("safe = list(actions.assert_safe_fields(fields))", _SRC)
		for expression in used:
			self.assertIn(
				expression,
				self.ALLOWED_FIELD_SOURCES,
				f"field list {expression!r} does not come from assert_safe_fields",
			)

	def test_the_guard_refuses_a_forbidden_projection(self):
		db, queries = _seeded()
		db.add_transfer()
		with self.assertRaises(actions.PickupCodeLeak):
			queries._select(({"company": "Mikas"},), ("name", "pickup_code_hash"))

	def test_every_endpoint_refuses_a_database_that_leaks(self):
		# The response guard, proved wired rather than merely present: this fake
		# hands back the digest whatever was selected, so an endpoint that skipped
		# `assert_no_pickup_code` would serialise it to a browser.
		db, queries = _seeded()
		name = db.add_transfer()
		db.add_event(name, "Payout", f"{TODAY} 10:30:00")
		db.leak = True
		for label, call in (
			("work_queue", lambda: queries.work_queue("Mikas", "ready_for_payout")),
			("transfers", lambda: queries.transfers(company="Mikas")),
			("transfer_detail", lambda: queries.transfer_detail(name)),
			("reconciliation", lambda: queries.reconciliation("Mikas")),
		):
			with self.subTest(endpoint=label), self.assertRaises(actions.PickupCodeLeak):
				call()

	def test_the_summary_projects_rather_than_passes_rows_through(self):
		# `operations_summary` is the one read that CANNOT raise on a leaking
		# database, because it returns no rows — only counts and per-currency
		# sums it built itself. That is a stronger property than the guard, so it
		# is asserted directly instead of being folded into the test above and
		# quietly passing for the wrong reason.
		db, queries = _seeded()
		db.add_transfer()
		db.leak = True
		actions.assert_no_pickup_code(queries.operations_summary("Mikas"))

	def test_the_attempt_counter_is_not_the_code(self):
		# `code_attempts` and `code_locked` are read on purpose — a payout screen
		# cannot show a lockout without them, and a count of wrong guesses is not
		# a secret. This pins that distinction so a later "tighten the guard"
		# cannot quietly break the lockout UI.
		db, queries = _seeded()
		name = db.add_transfer(code_attempts=3, code_locked=1, code_locked_at=f"{TODAY} 10:00:00")
		detail = queries.transfer_detail(name)
		self.assertEqual(3, detail["code_state"]["attempts"])
		self.assertEqual(5, detail["code_state"]["max_attempts"])
		self.assertTrue(detail["code_state"]["locked"])
		self.assertNotIn("pickup_code_hash", detail["transfer"])
		# The block is `code_state`, not `pickup_code`: `assert_no_pickup_code`
		# checks KEYS, so a response naming a key `pickup_code` is refused whatever
		# it holds. The first draft of this endpoint used that name and this test
		# is what found it.
		self.assertNotIn("pickup_code", detail)


# --------------------------------------------------------------------------- #
# 2. Lists go through get_list
# --------------------------------------------------------------------------- #
class PermissionPathTest(unittest.TestCase):
	def test_the_module_never_calls_get_all(self):
		# frappe/__init__.py:1365 — get_all "will not check for permissions". It
		# sets ignore_permissions, so `permission_query_conditions` never runs and
		# the company row filter in `permissions.remittance_transfer_query` is off.
		# Matched as a CALL, not as a word: the module docstring names `get_all` to
		# explain why it is banned, and a scan that tripped over its own rationale
		# would have to be deleted the first time anyone documented the rule.
		self.assertNotIn("get_all(", _SRC)

	def test_reads_survive_a_frappe_without_get_all(self):
		# The same claim, enforced rather than grepped: the fake `frappe` has no
		# `get_all` attribute, so any use anywhere on these paths is AttributeError.
		db, queries = _seeded()
		name = db.add_transfer()
		db.add_event(name, "Payout", f"{TODAY} 10:30:00")
		queries.operations_summary("Mikas")
		queries.work_queue("Mikas", "ready_for_payout")
		queries.transfers(company="Mikas")
		queries.transfer_detail(name)
		queries.reconciliation("Mikas")

	def test_every_read_is_company_scoped(self):
		db, queries = _seeded()
		db.add_transfer(company="Mikas")
		db.add_transfer(company="Anjan", sender_name="Someone Else")
		self.assertEqual(1, queries.transfers(company="Mikas")["total"])
		self.assertEqual(
			["Mikas"],
			[row["company"] for row in queries.work_queue("Mikas", "ready_for_payout")["rows"]],
		)


# --------------------------------------------------------------------------- #
# 3. The six queues
# --------------------------------------------------------------------------- #
class QueueTest(unittest.TestCase):
	def test_the_six_names_are_exactly_these(self):
		_db, queries = _seeded()
		self.assertEqual(EXPECTED_QUEUES, queries.QUEUES)

	def test_every_queue_name_has_a_branch_and_nothing_else_does(self):
		_db, queries = _seeded()
		for queue in queries.QUEUES:
			shapes = queries._queue_shapes(queue)
			self.assertTrue(shapes, f"{queue} resolves to no filter at all")
			for shape in shapes:
				self.assertIsInstance(shape, dict)
		with self.assertRaises(_Thrown):
			queries._queue_shapes("ready_for_payout ")
		with self.assertRaises(_Thrown):
			queries._queue_shapes("nonexistent_queue")

	def test_work_queue_refuses_a_name_that_is_not_one_of_the_six(self):
		_db, queries = _seeded()
		with self.assertRaises(_Thrown):
			queries.work_queue("Mikas", "everything")

	def test_ready_for_payout_holds_only_what_can_be_paid_out(self):
		db, queries = _seeded()
		payable = db.add_transfer()
		db.add_transfer(code_locked=1)
		db.add_transfer(refund_status="Approved")
		db.add_transfer(accounting_status="Unposted")
		rows = queries.work_queue("Mikas", "ready_for_payout")["rows"]
		self.assertEqual([payable], [row["name"] for row in rows])

	def test_a_null_refund_status_is_not_dropped_from_the_queue(self):
		# SQL `NOT IN (...)` over NULL is NULL, so a single `not in` filter would
		# hide exactly the oldest rows — the ones written before the field existed.
		db, queries = _seeded()
		legacy = db.add_transfer(refund_status=None)
		rows = queries.work_queue("Mikas", "ready_for_payout")["rows"]
		self.assertIn(legacy, [row["name"] for row in rows])

	def test_locked_and_refund_queues_pick_their_own_rows(self):
		db, queries = _seeded()
		db.add_transfer()
		locked = db.add_transfer(code_locked=1)
		requested = db.add_transfer(refund_status="Requested")
		self.assertEqual(
			[locked],
			[row["name"] for row in queries.work_queue("Mikas", "locked_pickup_code")["rows"]],
		)
		self.assertEqual(
			[requested],
			[row["name"] for row in queries.work_queue("Mikas", "refund_awaiting_approval")["rows"]],
		)

	def test_the_exception_queue_catches_an_obligation_that_never_posted(self):
		db, queries = _seeded()
		db.add_transfer()
		broken = db.add_transfer(accounting_status="Unposted")
		orphan = db.add_transfer(register_journal_entry=None)
		rows = queries.work_queue("Mikas", "accounting_exception")["rows"]
		self.assertEqual({broken, orphan}, {row["name"] for row in rows})


# --------------------------------------------------------------------------- #
# 4. The deadline nobody defined
# --------------------------------------------------------------------------- #
class ExpiryPolicyTest(unittest.TestCase):
	def test_the_expiry_queues_say_no_policy_rather_than_no_rows(self):
		db, queries = _seeded()
		db.add_transfer()
		for queue in ("expiring_12h", "expired_refund_required"):
			answer = queries.work_queue("Mikas", queue)
			self.assertFalse(answer["policy_configured"], queue)
			self.assertEqual([], answer["rows"], queue)
			self.assertEqual(0, answer["total"], queue)

	def test_the_summary_repeats_the_flag_it_cannot_answer(self):
		db, queries = _seeded()
		db.add_transfer()
		queues = queries.operations_summary("Mikas")["queues"]
		self.assertFalse(queues["expiring_12h"]["policy_configured"])
		self.assertFalse(queues["expired_refund_required"]["policy_configured"])
		self.assertTrue(queues["ready_for_payout"]["policy_configured"])

	def test_the_flag_is_measured_not_hard_coded(self):
		# The whole point: the day something starts writing `expires_at`, the
		# queues fill on their own. A hard-coded False would pass every other test
		# in this class and fail this one.
		db, queries = _seeded()
		soon = db.add_transfer(expires_at=f"{TODAY} 18:00:00")
		stale = db.add_transfer(expires_at=f"{TODAY} 08:00:00")

		expiring = queries.work_queue("Mikas", "expiring_12h")
		self.assertTrue(expiring["policy_configured"])
		self.assertEqual([soon], [row["name"] for row in expiring["rows"]])

		expired = queries.work_queue("Mikas", "expired_refund_required")
		self.assertTrue(expired["policy_configured"])
		self.assertEqual([stale], [row["name"] for row in expired["rows"]])


# --------------------------------------------------------------------------- #
# 5. The server decides which buttons exist
# --------------------------------------------------------------------------- #
class AllowedActionsTest(unittest.TestCase):
	def test_every_annotated_projection_carries_the_state_fields(self):
		# A missing state column does not raise — `_remittance_actions._field`
		# reads None and the predicate quietly answers "not locked", "no refund".
		# So the projection is the guard, and this is the test that keeps it one.
		_db, queries = _seeded()
		required = set(actions.STATE_FIELDS)
		for name in ("_ROW_FIELDS", "_DETAIL_FIELDS", "_RECON_FIELDS"):
			self.assertLessEqual(required, set(getattr(queries, name)), name)

	def test_a_cashier_is_offered_payout_and_a_viewer_is_offered_nothing(self):
		db, queries = _seeded()
		db.add_transfer()
		rows = queries.work_queue("Mikas", "ready_for_payout")["rows"]
		# A cashier at a ready transfer may hand over the cash OR take a refund
		# request; `next_action` is the first in `_remittance_actions` table order,
		# which is the order a desk works them.
		self.assertEqual([actions.PAYOUT, actions.REQUEST_REFUND], rows[0]["allowed_actions"])
		self.assertEqual(actions.PAYOUT, rows[0]["next_action"])

		db, queries = _seeded(roles=VIEWER)
		db.add_transfer()
		rows = queries.work_queue("Mikas", "ready_for_payout")["rows"]
		self.assertEqual([], rows[0]["allowed_actions"])
		self.assertIsNone(rows[0]["next_action"])

	def test_a_locked_transfer_is_never_offered_payout(self):
		# This is what `code_locked` in the projection buys. Drop the column and
		# `_payable` reads None, decides the code is unlocked, and the
		# reconciliation screen grows a Pay out button on a locked transfer.
		db, queries = _seeded(roles=MANAGER)
		db.add_transfer(code_locked=1)
		rows = queries.reconciliation("Mikas")["aged_open"]["rows"]
		self.assertEqual(1, len(rows))
		self.assertNotIn(actions.PAYOUT, rows[0]["allowed_actions"])
		self.assertIn(actions.UNLOCK_PICKUP_CODE, rows[0]["allowed_actions"])


# --------------------------------------------------------------------------- #
# 6. Money is never added across currencies
# --------------------------------------------------------------------------- #
class SummaryTest(unittest.TestCase):
	def test_currencies_are_separate_rows_and_there_is_no_total(self):
		db, queries = _seeded()
		db.add_transfer(send_currency="USD", tendered=1010.0)
		db.add_transfer(send_currency="USD", tendered=505.0)
		db.add_transfer(send_currency="EUR", tendered=200.0)
		card = queries.operations_summary("Mikas")["scorecards"]["registered_today"]
		self.assertEqual(3, card["count"])
		self.assertEqual(
			[
				{"currency": "EUR", "count": 1, "amount": 200.0},
				{"currency": "USD", "count": 2, "amount": 1515.0},
			],
			card["rows"],
		)
		self.assertNotIn("amount", card)
		self.assertNotIn("total", card)

	def test_paid_out_today_is_dated_from_the_event_trail(self):
		# The master has `registered_at` and nothing else — no `paid_out_at`. A
		# summary that dated payout from `modified` would move the figure every
		# time anything at all was written to the row.
		db, queries = _seeded()
		paid = db.add_transfer(operational_status="Paid Out")
		db.add_event(paid, "Payout", f"{TODAY} 10:30:00")
		db.add_transfer(operational_status="Paid Out")  # paid out, but not today
		card = queries.operations_summary("Mikas")["scorecards"]["paid_out_today"]
		self.assertEqual(1, card["count"])
		self.assertEqual([{"currency": "EUR", "count": 1, "amount": 920.0}], card["rows"])

	def test_commission_names_the_balance_and_the_flow_apart(self):
		db, queries = _seeded()
		db.add_transfer(commission=10.0)
		paid = db.add_transfer(operational_status="Paid Out", commission=7.0)
		db.add_event(paid, "Payout", f"{TODAY} 10:30:00")
		card = queries.operations_summary("Mikas")["scorecards"]["commission"]
		self.assertEqual([{"currency": "USD", "count": 1, "amount": 10.0}], card["deferred_open"])
		self.assertEqual([{"currency": "USD", "count": 1, "amount": 7.0}], card["earned_today"])


# --------------------------------------------------------------------------- #
# 7. Search, filters and one transfer in full
# --------------------------------------------------------------------------- #
class TransfersTest(unittest.TestCase):
	def test_search_matches_the_desk_as_well_as_the_parties(self):
		db, queries = _seeded()
		db.add_transfer(sender_name="Amina", origin_branch="Tashkent")
		bukhara = db.add_transfer(sender_name="Dilnoza", origin_branch="Bukhara")
		self.assertEqual(
			[bukhara],
			[row["name"] for row in queries.transfers(company="Mikas", query="bukhara")["rows"]],
		)
		self.assertEqual(1, queries.transfers(company="Mikas", query="Dilnoza")["total"])

	def test_an_exception_filter_and_a_status_filter_cannot_contradict_each_other(self):
		db, queries = _seeded()
		db.add_transfer()
		broken = db.add_transfer(accounting_status="Unposted")
		only = queries.transfers(company="Mikas", has_exception=1)
		self.assertEqual([broken], [row["name"] for row in only["rows"]])
		# `Paid Out` cannot be any exception shape, so the honest answer is empty —
		# not "every paid out transfer".
		none = queries.transfers(company="Mikas", has_exception=1, status="Paid Out")
		self.assertEqual([], none["rows"])
		self.assertEqual(0, none["total"])

	def test_excluding_exceptions_keeps_the_healthy_rows(self):
		db, queries = _seeded()
		healthy = db.add_transfer()
		db.add_transfer(accounting_status="Unposted")
		answer = queries.transfers(company="Mikas", has_exception=0)
		self.assertEqual([healthy], [row["name"] for row in answer["rows"]])

	def test_detail_keeps_the_four_axes_apart_and_shows_the_frozen_quote(self):
		db, queries = _seeded()
		name = db.add_transfer(operational_status="Paid Out", verification_status="Consumed")
		db.add_entry("JE-REM-0001", "Register")
		db.add_event(name, "Register", f"{TODAY} 09:00:00")
		db.add_event(name, "Payout", f"{TODAY} 10:30:00")
		detail = queries.transfer_detail(name)

		self.assertEqual(
			{
				"operational": "Paid Out",
				"accounting": "Posted",
				"verification": "Consumed",
				"refund": "None",
			},
			detail["status"],
		)
		self.assertEqual(12600.0, detail["quote"]["register_base_rate"])
		self.assertEqual(["Register", "Payout"], [event["event_type"] for event in detail["stages"]])
		self.assertEqual(["JE-REM-0001"], [entry["name"] for entry in detail["journal_entries"]])
		self.assertEqual("cashier@example.com", detail["audit"]["registered_by"])

	def test_detail_reads_the_refund_decision_off_the_trail(self):
		# The master holds only the current `refund_status`; who approved it and
		# why it was rejected exist nowhere else.
		db, queries = _seeded()
		name = db.add_transfer(refund_status="Approved")
		db.add_event(name, "Refund request", f"{TODAY} 09:30:00", details="Sender changed their mind")
		db.add_event(name, "Refund approval", f"{TODAY} 09:45:00", actor="manager@example.com")
		refund = queries.transfer_detail(name)["refund"]
		self.assertEqual("Approved", refund["status"])
		self.assertEqual("Sender changed their mind", refund["requested"]["details"])
		self.assertEqual("manager@example.com", refund["approved"]["actor"])
		self.assertIsNone(refund["rejected"])

	def test_a_missing_transfer_is_a_sentence_not_a_traceback(self):
		_db, queries = _seeded()
		with self.assertRaises(_Thrown):
			queries.transfer_detail("REM-2026-99999")
		with self.assertRaises(_Thrown):
			queries.transfer_detail("")


# --------------------------------------------------------------------------- #
# 8. Reconciliation: flows respect the window, the liability does not
# --------------------------------------------------------------------------- #
class ReconciliationTest(unittest.TestCase):
	def test_the_open_liability_ignores_the_date_filter(self):
		# An obligation opened in June is still owed in August. A liability that
		# shrinks when you narrow a date filter is not a liability.
		db, queries = _seeded()
		db.add_transfer(registered_at="2026-06-01 09:00:00")
		windowed = queries.reconciliation("Mikas", from_date=TODAY, to_date=TODAY)
		self.assertEqual([], windowed["register_cash_in"])
		self.assertEqual(
			[{"currency": "EUR", "count": 1, "amount": 920.0}],
			windowed["open_in_transit_liability"],
		)

	def test_variance_is_a_stage_that_posted_without_naming_its_entry(self):
		db, queries = _seeded()
		db.add_transfer()
		orphan = db.add_transfer(operational_status="Paid Out", payout_journal_entry=None)
		variance = queries.reconciliation("Mikas")["variance"]
		self.assertEqual(1, variance["count"])
		self.assertEqual([orphan], [row["name"] for row in variance["rows"]])

	def test_open_rows_carry_an_age_but_no_invented_threshold(self):
		db, queries = _seeded()
		db.add_transfer(registered_at="2026-08-07 09:00:00")
		aged = queries.reconciliation("Mikas")["aged_open"]
		self.assertEqual(1, aged["count"])
		self.assertEqual(10, aged["rows"][0]["age_days"])

	def test_the_expired_set_is_empty_and_says_why(self):
		db, queries = _seeded()
		db.add_transfer()
		expired = queries.reconciliation("Mikas")["expired"]
		self.assertFalse(expired["policy_configured"])
		self.assertEqual(0, expired["count"])
		self.assertEqual([], expired["rows"])

	def test_the_branch_breakdown_groups_by_desk_and_currency(self):
		db, queries = _seeded()
		db.add_transfer(origin_branch="Tashkent", receive_currency="EUR", receiver_amount=920.0)
		db.add_transfer(origin_branch="Tashkent", receive_currency="EUR", receiver_amount=80.0)
		db.add_transfer(origin_branch="Bukhara", receive_currency="USD", receiver_amount=500.0)
		self.assertEqual(
			[
				{"branch": "Bukhara", "currency": "USD", "count": 1, "open_amount": 500.0},
				{"branch": "Tashkent", "currency": "EUR", "count": 2, "open_amount": 1000.0},
			],
			queries.reconciliation("Mikas")["by_branch"],
		)


# --------------------------------------------------------------------------- #
# 9. An approved refund is authorised cash, not a posted reversal
# --------------------------------------------------------------------------- #
class OpenLiabilityTest(unittest.TestCase):
	"""What `approve_refund` does to the books, which is nothing.

	`remittance_commands.approve_refund:982` says so in as many words — "No posting
	here, deliberately". The obligation and the deferred commission stay submitted
	until `complete_refund` reverses them. So there are two different questions
	about the same set of rows and they have different answers:

	* *What may a cashier pay out?* — not this row. `_assert_payable:563` refuses a
	  transfer whose refund is Approved, and the work queue has to agree.
	* *What does the desk still owe?* — this row, in full. The GL is carrying it.

	Answering the second with the first is how a reconciliation screen reports less
	than the ledger holds, and it is silent: the row is not flagged as a variance
	either, because the master and the JE agree with each other perfectly.
	"""

	def test_an_approved_refund_is_still_owed_until_the_reversal_posts(self):
		db, queries = _seeded()
		db.add_transfer(receiver_amount=920.0, commission=10.0)
		db.add_transfer(refund_status="Approved", receiver_amount=500.0, commission=25.0)
		recon = queries.reconciliation("Mikas")
		self.assertEqual(
			[{"currency": "EUR", "count": 2, "amount": 1420.0}],
			recon["open_in_transit_liability"],
		)
		self.assertEqual(
			[{"currency": "USD", "count": 2, "amount": 35.0}],
			recon["commission"]["deferred_open"],
		)
		# The branch breakdown reads the same set, so it fails the same way.
		self.assertEqual(
			[{"branch": "Tashkent", "currency": "EUR", "count": 2, "open_amount": 1420.0}],
			recon["by_branch"],
		)

	def test_a_completed_refund_is_not_owed(self):
		# The far side of the same line: `complete_refund` writes Refunded/Reversed
		# (remittance_commands.py:1104-1111), and it is THAT pair — not the refund
		# column — that takes the row off the books. Without this test the fix above
		# could be "drop the refund filter" applied one step too far.
		db, queries = _seeded()
		db.add_transfer(receiver_amount=920.0)
		db.add_transfer(
			operational_status="Refunded",
			accounting_status="Reversed",
			refund_status="Completed",
			receiver_amount=500.0,
		)
		self.assertEqual(
			[{"currency": "EUR", "count": 1, "amount": 920.0}],
			queries.reconciliation("Mikas")["open_in_transit_liability"],
		)

	def test_the_payout_queue_still_refuses_what_the_liability_counts(self):
		db, queries = _seeded()
		payable = db.add_transfer()
		approved = db.add_transfer(refund_status="Approved")
		rows = queries.work_queue("Mikas", "ready_for_payout")["rows"]
		self.assertEqual([payable], [row["name"] for row in rows])
		self.assertNotIn(approved, [row["name"] for row in rows])

	def test_the_summary_reports_the_balance_and_the_payable_subset_apart(self):
		db, queries = _seeded()
		db.add_transfer(receiver_amount=920.0, commission=10.0)
		db.add_transfer(refund_status="Approved", receiver_amount=500.0, commission=25.0)
		cards = queries.operations_summary("Mikas")["scorecards"]
		# The card named "ready payout" is the payable subset — one row.
		self.assertEqual(1, cards["in_transit_ready_payout"]["count"])
		self.assertEqual(
			[{"currency": "EUR", "count": 1, "amount": 920.0}],
			cards["in_transit_ready_payout"]["rows"],
		)
		# The commission BALANCE is the whole open obligation — both rows.
		self.assertEqual(
			[{"currency": "USD", "count": 2, "amount": 35.0}],
			cards["commission"]["deferred_open"],
		)

	def test_a_null_refund_status_is_both_payable_and_owed(self):
		# The NULL split `_refund_open` exists for, carried over to the Python twin:
		# `None not in (...)` is True in Python where `NOT IN` over NULL is not true
		# in SQL, so the two halves have to be tested separately or one of them
		# passes for the wrong reason.
		db, queries = _seeded()
		db.add_transfer(refund_status=None, receiver_amount=920.0)
		self.assertEqual(
			1, queries.operations_summary("Mikas")["scorecards"]["in_transit_ready_payout"]["count"]
		)
		self.assertEqual(
			[{"currency": "EUR", "count": 1, "amount": 920.0}],
			queries.reconciliation("Mikas")["open_in_transit_liability"],
		)


# --------------------------------------------------------------------------- #
# 10. The ledger block is the Auditor's; the transfer belongs to everyone
# --------------------------------------------------------------------------- #
class JournalEntryVisibilityTest(unittest.TestCase):
	"""`transfer_detail` must not need Journal Entry read to answer at all.

	`register_remittance` writes `register_journal_entry` on every transfer, so the
	JE read is never skipped in practice, and `frappe.get_list` on a doctype the
	caller cannot read raises rather than returning nothing. That took the whole
	endpoint down for every one of the four remittance roles: no quote, no status
	axes, no lockout counter, for a cashier looking at their own transfer.

	The plan gives the ledger block to the Auditor (:460) and gives the Cashier
	Draft/Register/Payout. So the fix is not to hand the GL to everybody — it is to
	let the endpoint answer without it, and to SAY that it did.
	"""

	def test_a_caller_without_ledger_permission_still_gets_the_transfer(self):
		db, queries = _seeded()
		db.journal_readable = False
		name = db.add_transfer()
		db.add_entry("JE-REM-0001", "Register")
		detail = queries.transfer_detail(name)  # must not raise
		self.assertEqual([], detail["journal_entries"])
		self.assertFalse(detail["journal_entries_visible"])
		# Everything the 403 used to take with it.
		self.assertEqual("Posted", detail["status"]["accounting"])
		self.assertEqual(12600.0, detail["quote"]["register_base_rate"])
		self.assertEqual(5, detail["code_state"]["max_attempts"])
		# The link name is on the master, so it survives — only the voucher body is
		# withheld, and a screen can still show what the transfer claims it posted.
		self.assertEqual("JE-REM-0001", detail["transfer"]["register_journal_entry"])

	def test_the_flag_tells_may_not_read_apart_from_nothing_posted(self):
		# Both answer `journal_entries: []`, and they are opposite facts. A screen
		# that rendered "No journal entries" at the first one would be reporting a
		# clean ledger to someone who was simply not allowed to look.
		db, queries = _seeded()
		unposted = db.add_transfer(
			operational_status="Draft", accounting_status="Unposted", register_journal_entry=None
		)
		detail = queries.transfer_detail(unposted)
		self.assertEqual([], detail["journal_entries"])
		self.assertTrue(detail["journal_entries_visible"])

	def test_a_reader_with_the_permission_still_gets_the_vouchers(self):
		db, queries = _seeded()
		name = db.add_transfer()
		db.add_entry("JE-REM-0001", "Register")
		detail = queries.transfer_detail(name)
		self.assertEqual(["JE-REM-0001"], [entry["name"] for entry in detail["journal_entries"]])
		self.assertTrue(detail["journal_entries_visible"])

	def test_the_ledger_read_asks_first_rather_than_catching_the_refusal(self):
		# `try/except frappe.PermissionError` would pass every test above and be
		# wrong: `get_list` raises PermissionError for the row-scope hook too, so
		# catching it would also swallow a company-isolation refusal and answer
		# `journal_entries_visible: True` with an empty list. Asking names the one
		# condition being handled.
		self.assertIn('frappe.has_permission(JOURNAL, "read")', _SRC)
		self.assertNotIn("except frappe.PermissionError", _SRC)


if __name__ == "__main__":
	unittest.main()
