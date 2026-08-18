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
from decimal import Decimal

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
	"stabler.api.remittance_accounting",
	"stabler.api.remittance_commands",
)

TRANSFER = "Remittance Transfer"
EVENT = "Remittance Event"
JOURNAL = "Journal Entry"

NOW = datetime.datetime(2026, 8, 17, 11, 0, 0)
TODAY = "2026-08-17"

BASE_CURRENCY = "UZS"

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


def _sort_cmp(value):
	"""ORDER BY, which is not the same comparison as WHERE.

	`_cmp` above stringifies deliberately, because that is what makes a stored
	datetime string comparable with a `datetime` bound in a filter. Applying it to
	ORDER BY as well made this fake sort an INT as text — 9 above 10 — which is
	not what MariaDB does, and it let `code_attempts desc` look correct on the very
	path a locked queue actually loads through. Numbers sort as numbers here; a
	NULL sorts first on ascending, which is MariaDB's behaviour and the module's.
	"""
	if value is None or value == "":
		return (0, 0.0, "")
	if isinstance(value, (int, float)) and not isinstance(value, bool):
		return (1, float(value), "")
	return (1, 0.0, str(value))


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
		#: What the faked `build_legs` hands back. Empty by default so the tests that
		#: are about something else stay about it.
		self.legs: list[dict] = []
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
			rows.sort(key=lambda row, f=field: _sort_cmp(row.get(f)), reverse=direction.strip() == "desc")

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

	def _throw(message, exc=None, *_a, **_k):
		# The class matters. `posting_preview` refuses with `frappe.PermissionError`,
		# and to a caller that is a different event from a validation refusal —
		# collapsing both into `_Thrown` would let a test pass on either one.
		raise (exc or _Thrown)(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn
	frappe.get_roles = lambda user=None: list(roles)
	frappe.get_list = db.get_list
	frappe.has_permission = lambda doctype, ptype="read", *_a, **_k: (
		db.journal_readable if doctype == JOURNAL else True
	)
	frappe.PermissionError = PermissionError

	def _get_doc(doctype, name, *_a, **_k):
		# Keyed, unlike `get_all` below: a preview is asked for one named transfer.
		for row in db.transfers:
			if row["name"] == name:
				return types.SimpleNamespace(**row)
		raise _Thrown(f"{doctype} {name} does not exist")

	frappe.get_doc = _get_doc
	frappe.get_cached_value = lambda doctype, name, field, *_a, **_k: BASE_CURRENCY
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

	# Faked for the same reason as the two above: importing the real one drags in
	# `frappe.utils.getdate`, ERPNext's exchange-rate helper and the settings
	# doctype, none of which this suite models. That the legs are the ones the
	# LEDGER receives is proved in test_remittance_accounting_bench.py against a
	# real ledger, which is the only place such a claim means anything. What is
	# provable here is what `posting_preview` does with legs it is handed: who it
	# hands them to, and whether it repeats the arithmetic instead of reporting it.
	accounting = types.ModuleType("stabler.api.remittance_accounting")
	accounting.REGISTER = "Register"
	accounting.PAYOUT = "Payout"
	accounting.REFUND = "Refund"
	accounting.build_legs = lambda *_a, **_k: {"legs": [dict(leg) for leg in db.legs]}

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.api.remittance_accounting": accounting,
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
		# `code_attempts` and `verification_status` are read on purpose — a payout
		# screen cannot show a lockout without them, and a count of wrong guesses is
		# not a secret. This pins that distinction so a later "tighten the guard"
		# cannot quietly break the lockout UI.
		db, queries = _seeded()
		name = db.add_transfer(
			code_attempts=3, verification_status="Locked", code_locked_at=f"{TODAY} 10:00:00"
		)
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
		db.add_transfer(verification_status="Locked")
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
		locked = db.add_transfer(verification_status="Locked")
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
# 3b. The approved refund that appeared nowhere
# --------------------------------------------------------------------------- #
class ApprovedRefundVisibilityTest(unittest.TestCase):
	"""An approved refund is unfinished work with a cashier standing at a drawer.

	`approve_refund` posts nothing — the obligation and the deferred commission
	stay in the GL until `complete_refund` reverses them — so the transfer is
	waiting on the ORIGIN desk to count the cash back out. It used to match no
	queue on the whole operations screen: the three payout queues drop it by
	design (`_refund_open` mirrors what the payout endpoint would refuse),
	`locked_pickup_code` wants a locked code, and the exception shapes describe a
	broken row, which an approved refund is not. Work with nobody looking at it is
	how a desk loses a day.
	"""

	def _queues_holding(self, queries, name: str) -> set:
		found = set()
		for queue in queries.QUEUES:
			rows = queries.work_queue("Mikas", queue)["rows"]
			if name in [row["name"] for row in rows]:
				found.add(queue)
		return found

	def test_an_approved_refund_reaches_a_queue_at_all(self):
		# The regression proper. Asserted across all six rather than against the one
		# so a future filter change cannot fix this queue by breaking another.
		db, queries = _seeded()
		approved = db.add_transfer(refund_status="Approved")
		self.assertEqual({"refund_awaiting_approval"}, self._queues_holding(queries, approved))

	def test_the_queue_carries_both_open_refund_states_and_neither_closed_one(self):
		db, queries = _seeded()
		requested = db.add_transfer(refund_status="Requested")
		approved = db.add_transfer(refund_status="Approved")
		# Completed: the cash is already back with the sender. Rejected: the transfer
		# went on living and is payable again. Neither is refund work.
		db.add_transfer(refund_status="Completed")
		db.add_transfer(refund_status="Rejected")
		db.add_transfer(refund_status="None")
		rows = queries.work_queue("Mikas", "refund_awaiting_approval")["rows"]
		self.assertEqual({requested, approved}, {row["name"] for row in rows})

	def test_the_tile_counts_what_the_list_shows(self):
		# The count is what a manager reads before deciding there is nothing to do.
		# A queue that lists the row and counts it out is worse than one that hides
		# it, because it looks answered.
		db, queries = _seeded()
		db.add_transfer(refund_status="Approved")
		db.add_transfer(refund_status="Requested")
		summary = queries.operations_summary("Mikas")
		rows = queries.work_queue("Mikas", "refund_awaiting_approval")["rows"]
		self.assertEqual(len(rows), summary["queues"]["refund_awaiting_approval"]["count"])
		self.assertEqual(2, len(rows))

	def test_an_approved_refund_is_still_not_offered_for_payout(self):
		# Widening the refund queue must not widen the payable set: paying out a
		# transfer whose refund was approved hands the same money to two people.
		db, queries = _seeded()
		db.add_transfer(refund_status="Approved")
		self.assertEqual([], queries.work_queue("Mikas", "ready_for_payout")["rows"])


# --------------------------------------------------------------------------- #
# 3c. Each queue leads with what is closest to hurting
# --------------------------------------------------------------------------- #
class QueueOrderTest(unittest.TestCase):
	"""A queue is worked, not browsed, so `registered_at desc` is wrong for all six.

	Every queue used to fall through to `_ORDER` — newest registration first —
	which for "expiring within 12 hours" is very nearly the reverse of
	soonest-deadline-first, and for a locked code ignores the one number that says
	which transfer is about to be lost. D11 in the design council record; the
	wording is PROMPT_remittance_design_v2.txt:315-316.
	"""

	def _names(self, queries, queue, **kwargs):
		return [row["name"] for row in queries.work_queue("Mikas", queue, **kwargs)["rows"]]

	def test_expiring_leads_with_the_soonest_deadline(self):
		db, queries = _seeded()
		# Registration order is deliberately the reverse of deadline order. Under
		# the old default the newest registration led, which put the LAST deadline
		# at the top of the screen whose entire job is the next one.
		late = db.add_transfer(registered_at=f"{TODAY} 10:00:00", expires_at=f"{TODAY} 20:00:00")
		soon = db.add_transfer(registered_at=f"{TODAY} 09:00:00", expires_at=f"{TODAY} 13:00:00")
		self.assertEqual([soon, late], self._names(queries, "expiring_12h"))

	def test_expired_leads_with_the_one_that_has_been_owed_longest(self):
		db, queries = _seeded()
		recent = db.add_transfer(expires_at=f"{TODAY} 10:00:00")
		oldest = db.add_transfer(expires_at="2026-08-15 10:00:00")
		self.assertEqual([oldest, recent], self._names(queries, "expired_refund_required"))

	def test_the_payout_and_refund_queues_lead_with_the_oldest_request(self):
		# Oldest first, because the person who has waited longest is the one whose
		# patience the desk is spending.
		db, queries = _seeded()
		newer = db.add_transfer(registered_at=f"{TODAY} 10:00:00")
		older = db.add_transfer(registered_at="2026-08-14 08:00:00")
		self.assertEqual([older, newer], self._names(queries, "ready_for_payout"))

		fresh = db.add_transfer(registered_at=f"{TODAY} 10:30:00", refund_status="Requested")
		stale = db.add_transfer(registered_at="2026-08-13 08:00:00", refund_status="Approved")
		self.assertEqual([stale, fresh], self._names(queries, "refund_awaiting_approval"))

	def test_attempts_are_counted_rather_than_spelled(self):
		# 9 against 10, because those are the smallest two values whose numeric and
		# textual order disagree — with 1 and 5 a text sort passes. Sorting an Int as
		# text buries the transfer nearest to being lost under the one with a single
		# failed attempt.
		db, queries = _seeded()
		fewer = db.add_transfer(verification_status="Locked", code_attempts=9)
		most = db.add_transfer(verification_status="Locked", code_attempts=10)
		self.assertEqual([most, fewer], self._names(queries, "locked_pickup_code"))

	def test_the_same_holds_once_a_filter_forces_the_union_path(self):
		# A desk filter doubles every shape, so the rows come back unioned and are
		# ordered by `_sorted_by` in Python rather than by the database. The two
		# executors of one order string have to agree, and this queue is where they
		# would most visibly not.
		db, queries = _seeded()
		fewer = db.add_transfer(verification_status="Locked", code_attempts=9)
		most = db.add_transfer(verification_status="Locked", code_attempts=10)
		self.assertEqual([most, fewer], self._names(queries, "locked_pickup_code", desk="Tashkent"))

	def test_every_queue_breaks_a_tie_on_the_name(self):
		# Asserted against the order strings themselves, not against paged output.
		# The failure this prevents is MariaDB returning tied rows in a different
		# arrangement for the page-1 query than for the page-2 query, so page 2
		# repeats a row and silently drops another. No in-process fake can reproduce
		# that — Python's sort is stable and a dict preserves insertion order, so a
		# behavioural test here passes with or without the tiebreaker and would be a
		# green light over nothing.
		_db, queries = _seeded()
		for queue in queries.QUEUES:
			with self.subTest(queue=queue):
				self.assertTrue(
					queries._QUEUE_ORDER[queue].endswith("name asc"),
					f"{queue} has no total order, so its page boundary is not stable",
				)


# --------------------------------------------------------------------------- #
# 3d. The two filters, on both regions of the screen
# --------------------------------------------------------------------------- #
class QueueFilterTest(unittest.TestCase):
	"""The queue takes the same `currency` and `desk` the scorecards take.

	Before this only `operations_summary` had a currency argument, so narrowing
	the filter left the queue rows and the queue counts untouched beside a
	narrowed scorecard — which reads as a filter that silently failed.
	"""

	def test_the_currency_filter_reaches_the_queue_rows(self):
		db, queries = _seeded()
		usd = db.add_transfer(send_currency="USD")
		db.add_transfer(send_currency="EUR")
		rows = queries.work_queue("Mikas", "ready_for_payout", currency="USD")["rows"]
		self.assertEqual([usd], [row["name"] for row in rows])

	def test_a_desk_matches_either_leg_because_it_works_both(self):
		# A desk pays out what arrives at it and counts cash back out on refunds of
		# what it registered. Filtering one leg would hide half of its own work —
		# the same shape of blindness this bead was opened for.
		db, queries = _seeded()
		outbound = db.add_transfer(origin_branch="Tashkent", destination_branch="Bukhara")
		inbound = db.add_transfer(origin_branch="Bukhara", destination_branch="Tashkent")
		db.add_transfer(origin_branch="Bukhara", destination_branch="Samarkand")
		rows = queries.work_queue("Mikas", "ready_for_payout", desk="Tashkent")["rows"]
		self.assertEqual({outbound, inbound}, {row["name"] for row in rows})

	def test_a_row_matching_both_legs_is_listed_once(self):
		# The desk filter is a union of two shapes; a same-desk transfer satisfies
		# both, and a union that did not dedupe would count it twice in the tile.
		db, queries = _seeded()
		db.add_transfer(origin_branch="Tashkent", destination_branch="Tashkent")
		answer = queries.work_queue("Mikas", "ready_for_payout", desk="Tashkent")
		self.assertEqual(1, len(answer["rows"]))
		self.assertEqual(1, answer["total"])

	def test_the_tile_counts_are_narrowed_by_the_same_two_filters(self):
		# The counts sit directly above the rows. A tile reading 2 over a list of 1
		# is a screen contradicting itself.
		db, queries = _seeded()
		db.add_transfer(send_currency="USD", origin_branch="Tashkent")
		db.add_transfer(send_currency="EUR", origin_branch="Tashkent")
		db.add_transfer(send_currency="USD", origin_branch="Bukhara", destination_branch="Bukhara")
		summary = queries.operations_summary("Mikas", currency="USD", desk="Tashkent")
		rows = queries.work_queue("Mikas", "ready_for_payout", currency="USD", desk="Tashkent")["rows"]
		self.assertEqual(1, summary["queues"]["ready_for_payout"]["count"])
		self.assertEqual(1, len(rows))

	def test_the_answer_repeats_the_filters_it_was_given(self):
		# The screen renders its own filter state from the response, so a server
		# that dropped an argument must not answer as though it had applied it.
		db, queries = _seeded()
		db.add_transfer()
		answer = queries.work_queue("Mikas", "ready_for_payout", currency="USD", desk="Tashkent")
		self.assertEqual("USD", answer["currency"])
		self.assertEqual("Tashkent", answer["desk"])
		unfiltered = queries.work_queue("Mikas", "ready_for_payout")
		self.assertIsNone(unfiltered["currency"])
		self.assertIsNone(unfiltered["desk"])


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
		# This is what `verification_status` in the projection buys. Drop the column
		# and `_payable` reads None, which is not the string "Locked", so it decides
		# the code is unlocked and the reconciliation screen grows a Pay out button
		# on a locked transfer.
		db, queries = _seeded(roles=MANAGER)
		db.add_transfer(verification_status="Locked")
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


# --------------------------------------------------------------------------- #
# 10. The posting preview answers to the posting, not to the row
# --------------------------------------------------------------------------- #
def _leg(account: str, currency: str, side: str, amount: str, rate: str, base: str) -> dict:
	"""One journal-entry row in the shape `build_legs` emits — base values Decimal.

	`base` is `amount * rate` rounded to the minor unit, which is what
	`_remittance_accounting._assert_closes` re-derives before it will let a leg
	through. Kept true here so a reader can check the fixture's arithmetic instead
	of taking it on faith.
	"""
	zero = Decimal(0)
	return {
		"account": account,
		"account_currency": currency,
		"debit_in_account_currency": Decimal(amount) if side == "debit" else zero,
		"credit_in_account_currency": Decimal(amount) if side == "credit" else zero,
		"debit": Decimal(base) if side == "debit" else zero,
		"credit": Decimal(base) if side == "credit" else zero,
		"exchange_rate": Decimal(rate),
	}


#: A 49.999,99 USD transfer out of a UZS-base company, paying 44.120,75 EUR.
#: Every leg's base value is its own amount times its own rate, to the minor
#: unit, and the two credits close the debit EXACTLY in Decimal:
#:
#:     595.641.155,19 + 21.642.221,35 = 617.283.376,54
#:
#: In float64 they do not: the same sum lands 1,19e-07 above the debit, which is
#: a hundred and twenty times the fixed 1e-9 this endpoint first compared
#: against. Nothing here is contrived to be awkward — UZS is the base currency
#: `remittance_accounting` itself falls back to, and every base figure a UZS
#: tenant posts is past ~4,5e6, where 1e-9 is already smaller than one ulp.
_CENTS_LEGS = (
	_leg("Origin Desk Cash - U", "USD", "debit", "49999.99", "12345.67", "617283376.54"),
	_leg("Receiver Obligation - U", "EUR", "credit", "44120.75", "13500.25", "595641155.19"),
	_leg("Deferred Commission - U", "UZS", "credit", "21642221.35", "1", "21642221.35"),
)


class PostingPreviewGateTest(unittest.TestCase):
	"""Who may see a journal entry that has not been written yet.

	The payload is GL account names, debits, credits and a transfer's base
	valuation. `Remittance Viewer` and `Remittance Auditor` hold `read` on
	Remittance Transfer — masked list and reports is the whole of the Viewer's
	brief — so gating on the doctype would have let either walk their own list and
	enumerate every desk cash, obligation, deferred-commission and commission-income
	account the company has. Gating on Journal Entry read instead would have blanked
	the preview for everybody, since none of the four remittance roles carries it.
	So the gate is the action, and these tests are what says so.
	"""

	def test_a_viewer_is_refused_the_payout_preview(self):
		db, queries = _seeded(roles=VIEWER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer()

		with self.assertRaises(PermissionError):
			queries.posting_preview(name, "Payout")

	def test_a_cashier_is_shown_the_payout_preview(self):
		db, queries = _seeded(roles=CASHIER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer()

		preview = queries.posting_preview(name, "Payout")

		self.assertEqual(len(_CENTS_LEGS), len(preview["rows"]))
		self.assertEqual(BASE_CURRENCY, preview["base_currency"])

	def test_a_cashier_is_refused_a_refund_preview_nobody_has_approved(self):
		"""The state half of the same gate, and the claim the old test name made.

		A cashier holds `complete_refund`; they do not hold it on a transfer whose
		refund has not been approved. Before the gate, previewing this returned a
		full reversal plan for a posting `complete_refund` would refuse — a screen
		showing a cashier the cash they are about to hand back on a refund that was
		never authorised.
		"""
		db, queries = _seeded(roles=CASHIER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer()

		with self.assertRaises(PermissionError):
			queries.posting_preview(name, "Refund")

	def test_the_refund_preview_opens_once_the_refund_is_approved(self):
		db, queries = _seeded(roles=CASHIER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer(refund_status="Approved")

		self.assertTrue(queries.posting_preview(name, "Refund")["rows"])

	def test_a_paid_out_transfer_has_no_payout_left_to_preview(self):
		db, queries = _seeded(roles=CASHIER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer(operational_status="Paid Out")

		with self.assertRaises(PermissionError):
			queries.posting_preview(name, "Payout")

	def test_register_is_not_a_previewable_stage(self):
		"""Dropped, rather than left as the one stage with no gate behind it.

		No action covers registering, so there was nothing to check it against; the
		screen that would want it — New Transfer — has no transfer to key on, and
		this endpoint refuses caller-supplied amounts by design; and for a transfer
		that HAS registered, `transfer_detail` already serves the posted entry to
		whoever may read the ledger. What was left was an ungated one.
		"""
		db, queries = _seeded(roles=CASHIER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer()

		with self.assertRaises(_Thrown):
			queries.posting_preview(name, "Register")


class PostingPreviewBalanceTest(unittest.TestCase):
	"""`balanced` restates the builder's verdict. It must never re-derive it.

	`build_legs` proves debit == credit exactly, in Decimal, and raises if it does
	not (`_remittance_accounting._assert_closes`). The first version of this
	endpoint threw that proof away: it cast every leg to float, re-added them, and
	compared the two sums against a fixed 1e-9. On a UZS-base tenant that is well
	below one float64 ulp, so a sound entry came back `balanced: false` — under
	which the screen prints "This entry does not balance. Do not hand over cash —
	report it." above a totals row showing two identical numbers. The cost is a
	refused payout and an escalation about a ledger fault that does not exist.
	"""

	def test_an_entry_that_closes_in_decimal_is_reported_balanced(self):
		db, queries = _seeded(roles=CASHIER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer()

		preview = queries.posting_preview(name, "Payout")

		self.assertTrue(
			preview["balanced"],
			"an entry the poster proved sound was reported to the cashier as broken",
		)

	def test_the_fixture_is_one_a_float_re_sum_gets_wrong(self):
		"""Guards the test above: it only means anything on legs that trip float.

		Without this, someone tidying `_CENTS_LEGS` into round numbers would leave a
		green test that cannot fail — which is the state the bench suite's balance
		test was in.
		"""
		debit = sum(float(leg["debit"]) for leg in _CENTS_LEGS)
		credit = sum(float(leg["credit"]) for leg in _CENTS_LEGS)

		self.assertNotEqual(debit, credit, "these legs close in float, so they prove nothing")
		self.assertEqual(
			sum(leg["debit"] for leg in _CENTS_LEGS),
			sum(leg["credit"] for leg in _CENTS_LEGS),
			"these legs do not close in Decimal either, so the fixture is simply wrong",
		)

	def test_the_totals_are_the_base_column_the_screen_adds_up(self):
		db, queries = _seeded(roles=CASHIER)
		db.legs = list(_CENTS_LEGS)
		name = db.add_transfer()

		preview = queries.posting_preview(name, "Payout")

		self.assertAlmostEqual(617283376.54, preview["total_debit"], places=2)
		self.assertAlmostEqual(617283376.54, preview["total_credit"], places=2)

	def test_the_preview_goes_out_through_the_pickup_code_guard(self):
		# Every other whitelisted return in this module wraps. Nothing in this one
		# can carry the code today, which is exactly why the wrapper is the thing
		# that catches the edit which adds a transfer field to the payload.
		self.assertIn("return actions.assert_no_pickup_code(", _SRC)


if __name__ == "__main__":
	unittest.main()
