"""The refund command: three states, one lock, and a race that must have a loser.

Refund is the only remittance path where authority and cash are separated by a
person, so the tests are grouped by the thing that can actually go wrong.

**The lock, and the read that goes through it.** Asserted twice, exactly as
`test_remittance_payout_command` does: once against the source text — the cheap
check a reader can see — and once against a fake database. The fake here is
deliberately stronger than payout's, because payout's cannot fail on the defect
that cost this module a P0. Its `require_lock` is satisfied by any caller that
took the row lock, so `frappe.db.get_value(..., for_update=True)` followed by a
plain `frappe.get_doc(...)` passes it — which is precisely the broken shape. This
fake models the snapshot instead: `open_snapshot()` freezes what a NON-locking
read will return, so a step that locks and then reads without `for_update` sees
the pre-race row and decides on state that no longer exists. That is REPEATABLE
READ in an in-memory dict, and it is what makes `RefundRaceTest` a behavioural
test rather than a source assertion wearing a behavioural coat.

**The role, which is the only gate there is.** `@frappe.whitelist()` admits any
authenticated user, `db_set` consults no permission, and the refund Journal Entry
is inserted with `ignore_permissions=True`. So a refund endpoint without a role
check is reachable by anyone with a session — the tests below spend that fact
rather than assuming a DocPerm somewhere catches it.

**The cash, which moves exactly once.** Approving posts nothing; completing posts
once; a replay posts nothing again. Each of those is asserted on the ledger side
of the fake (`refund_journal_entry`, `accounting_status`), not on the message.

Bench-free: the bench set is not part of `make check`, so a test needing one would
not gate a push. The ledger side of refund is proved on a real ledger in
`test_remittance_accounting_bench.py`.
"""

from __future__ import annotations

import importlib
import os
import re
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.remittance_commands"
_SRC = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api", "remittance_commands.py"
)
#: The patch that actually creates the Roles the refund gates name — stabler-tvma.
_ROLE_PATCH_SRC = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "patches", "v87_remittance_roles.py"
)

_SANDBOX = ModuleSandbox()

_FAKED = (
	_MODULE,
	"frappe",
	"frappe.model",
	"frappe.model.naming",
	"frappe.utils",
	"stabler.api._common",
	"stabler.api.approvals",
	"stabler.api.money",
	"stabler.api.remittance",
	"stabler.api.remittance_accounting",
)

TRANSFER = "Remittance Transfer"
EVENT = "Remittance Event"
SETTINGS = "Remittance Settings"

CASHIER = "Remittance Cashier"
MANAGER = "Remittance Finance Manager"
VIEWER = "Remittance Viewer"
AUDITOR = "Remittance Auditor"

#: The rate the obligation opened at. Only used to prove it is named in the
#: refusal a moved corridor produces — see `RefundRateBandTest`.
FROZEN_RATE = 12000.0


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


class _Doc:
	"""A document view onto one row of the fake database."""

	def __init__(self, db, fields: dict):
		object.__setattr__(self, "_db", db)
		object.__setattr__(self, "_fields", dict(fields))

	def __getattr__(self, field):
		try:
			return self._fields[field]
		except KeyError:
			return None

	def __setattr__(self, field, value):
		self._fields[field] = value

	def get(self, field, default=None):
		return self._fields.get(field, default)

	def insert(self):
		self._db.insert(self._fields)
		return self

	def db_set(self, patch, value=None, notify=True):
		patch = patch if isinstance(patch, dict) else {patch: value}
		self._fields.update(patch)
		self._db.write(self.name, patch)


class _FakeDB:
	def __init__(self):
		self.rows: dict[str, dict] = {}
		#: What a NON-locking read returns once a snapshot has been opened. Empty
		#: unless a test stages a race, so every other test sees a plain database.
		self.stale: dict[str, dict] = {}
		self.events: list[dict] = []
		self.settings: dict[str, dict] = {}
		self.locked: set[str] = set()
		self.writes: list[tuple[str, dict]] = []
		self.commits = 0
		self._seq = 0
		self._clock = 0

	# --- the refusals that make this a test and not a mock ------------------- #
	def require_lock(self, name: str, what: str) -> None:
		if name not in self.locked:
			raise AssertionError(f"{what} on {name} happened without the row lock")

	def open_snapshot(self, name: str) -> None:
		"""Freeze what an unlocked read of this row will see from here on.

		This is the half of REPEATABLE READ that the payout fake cannot express.
		`SELECT ... FOR UPDATE` returns the latest committed row, but it does not
		advance the transaction's consistent-read snapshot — and in a Frappe request
		that snapshot is already open, established by the session and permission
		reads, long before the handler blocks on anyone's lock. So the loser of a
		race acquires the lock after the winner commits and a plain `frappe.get_doc`
		still hands back the pre-race row.

		A test calls this at the moment the loser's request would have started, then
		lets the winner commit. Any refund step that reads state without
		`for_update=True` from then on decides on a transfer that no longer exists.
		"""
		self.stale[name] = dict(self.rows[name])

	def read(self, name: str, *, locked: bool) -> dict:
		return self.rows[name] if locked else self.stale.get(name, self.rows[name])

	# --- seeding ------------------------------------------------------------- #
	def add_transfer(self, **fields) -> str:
		self._seq += 1
		name = fields.pop("name", None) or f"REM-2026-{self._seq:05d}"
		row = {
			"name": name,
			"doctype": TRANSFER,
			"company": "Mikas",
			"client_request_id": f"reg-{self._seq}",
			"sender_name": "Amina",
			"receiver_name": "Bekzod",
			"origin_branch": "Tashkent",
			"destination_branch": "Samarkand",
			"send_currency": "USD",
			"receive_currency": "EUR",
			"principal": 1000.0,
			"commission": 10.0,
			"tendered": 1010.0,
			"receiver_amount": 920.0,
			"operational_status": "Registered",
			"accounting_status": "Posted",
			"verification_status": "Active",
			"refund_status": "None",
			"code_attempts": 0,
			"code_locked": 0,
			"register_journal_entry": "JE-REM-0001",
			"register_base_rate": FROZEN_RATE,
			"registered_at": "2026-08-17 09:00:00",
			"modified": "2026-08-17 10:00:00",
		}
		row.update(fields)
		self.rows[name] = row
		return name

	def insert(self, fields: dict) -> None:
		if fields.get("doctype") == EVENT:
			self._clock += 1
			self.events.append({**fields, "creation": self._clock})
			return
		raise AssertionError(f"unexpected insert of {fields.get('doctype')}")

	def write(self, name: str, patch: dict) -> None:
		self.rows[name].update(patch)
		self.rows[name]["modified"] = "2026-08-17 11:00:00"
		self.writes.append((name, dict(patch)))

	# --- frappe.db surface --------------------------------------------------- #
	def get_default(self, key):
		return 2 if key == "currency_precision" else None

	def get_value(self, doctype, filters, fieldname=None, for_update=False, order_by=None):
		if doctype == SETTINGS:
			return (self.settings.get(filters) or {}).get(fieldname)
		if doctype == EVENT:
			matches = [
				event
				for event in self.events
				if all(event.get(field) == value for field, value in filters.items())
			]
			# `order_by="creation desc"` is how the command asks for the LATEST event
			# of a kind, which is what a request that was rejected and made again needs.
			if order_by and "desc" in order_by:
				matches.reverse()
			return matches[0].get(fieldname) if matches else None
		if for_update:
			# Locking a row that is not there is how the command 404s.
			if filters in self.rows:
				self.locked.add(filters)
		row = self.rows.get(filters)
		return row.get(fieldname) if row else None

	def get_all(self, doctype, filters=None, or_filters=None, fields=None, order_by=None, limit=None):
		rows = [
			row
			for row in self.rows.values()
			if all(row.get(field) == value for field, value in (filters or {}).items())
		]
		return [{field: row.get(field) for field in (fields or [])} for row in rows[: limit or None]]

	def commit(self):
		self.commits += 1


def _load(db: _FakeDB, *, roles=(CASHIER,), refund_raises: Exception | None = None):
	"""Import the command module against the fakes. Returns the module and a
	MUTABLE role list, so one test can act as the desk and then as the manager."""
	_SANDBOX.evict(*_FAKED)

	current_roles = list(roles)

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.db = db
	frappe.session = types.SimpleNamespace(user="desk@example.com")
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn
	frappe.get_roles = lambda user=None: list(current_roles)
	frappe.PermissionError = PermissionError
	# In Frappe, `throw` raises ValidationError. `_post_the_refund` catches exactly
	# that class and re-throws with context, so the stand-in has to BE that class or
	# the wrapping under test would never trigger.
	frappe.ValidationError = _Thrown
	frappe.UniqueValidationError = type("UniqueValidationError", (Exception,), {})
	frappe.DuplicateEntryError = frappe.UniqueValidationError

	def _get_doc(source, name=None, *, for_update=False):
		if name is not None:
			# Two separate refusals. The lock must have been taken at all...
			db.require_lock(name, "state read")
			# ...and the state must be read THROUGH it, or the row served is the one
			# the request's snapshot froze. See `_FakeDB.open_snapshot`.
			return _Doc(db, db.read(name, locked=for_update))
		return _Doc(db, source)

	frappe.get_doc = _get_doc
	frappe.get_all = db.get_all

	model = types.ModuleType("frappe.model")
	naming = types.ModuleType("frappe.model.naming")
	naming.make_autoname = lambda *_a, **_k: ""
	model.naming = naming
	frappe.model = model

	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value: int(value or 0)
	utils.flt = lambda value, precision=None: (
		round(float(value or 0), precision) if precision is not None else float(value or 0)
	)
	utils.get_datetime_str = lambda value: str(value)
	utils.getdate = lambda value=None: value
	utils.now_datetime = lambda: "2026-08-17 11:00:00"
	utils.nowdate = lambda: "2026-08-17"
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._assert_can_read = lambda *_a, **_k: None
	common._require_company = lambda company: company

	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: None
	approvals._APPROVER_ROLES = ("Accounts Manager", "System Manager", "Stabler Admin")

	money = types.ModuleType("stabler.api.money")
	for attr in (
		"_date_filters",
		"_round2",
		"_validate_account",
		"bank_cash_accounts",
		"get_exchange_rate_for_currencies",
		"journal_entry_detail",
	):
		setattr(money, attr, lambda *_a, **_k: None)

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.model": model,
			"frappe.model.naming": naming,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.api.money": money,
		}
	)

	# The REAL hashing helpers, imported against the stubs above: the race tests
	# drive a real payout, and a faked code compare would make that a tautology.
	remittance = importlib.import_module("stabler.api.remittance")

	accounting = types.ModuleType("stabler.api.remittance_accounting")

	def _post_payout(transfer, *, posting_date=None, submit=True):
		db.require_lock(transfer.name, "payout posting")
		transfer.db_set("payout_journal_entry", "JE-REM-0002", notify=False)
		return {"journal_entry": "JE-REM-0002"}

	def _post_refund(transfer, *, posting_date=None, submit=True):
		# The obligation must never be reversed off an unlocked row.
		db.require_lock(transfer.name, "refund posting")
		if refund_raises is not None:
			raise refund_raises
		# Mirrors the real `post_refund`, which writes both of these itself.
		transfer.db_set(
			{"refund_journal_entry": "JE-REM-0003", "accounting_status": "Reversed"}, notify=False
		)
		return {"journal_entry": "JE-REM-0003"}

	accounting.post_payout = _post_payout
	accounting.post_refund = _post_refund
	accounting.post_register = lambda transfer, **_k: {"journal_entry": "JE-REM-0001"}

	_SANDBOX.install({"stabler.api.remittance": remittance, "stabler.api.remittance_accounting": accounting})
	return importlib.import_module(_MODULE), current_roles, remittance


# Every read of the transfer row by name, however it is spelled. The kwarg each one
# carries is the whole question below, so the pattern swallows the argument list.
_STATE_READS = re.compile(r"frappe\.get_doc\(\s*TRANSFER\s*,[^)]*\)")
_COLUMN_READS = re.compile(r"frappe\.db\.get_value\(\s*TRANSFER[^)]*\)")

#: Every function the refund path is made of. A bare read hiding in any one of them
#: is the defect, so the source tests sweep the set rather than the entry points.
_REFUND_FUNCTIONS = (
	"_locked_transfer",
	"_assert_refundable",
	"_already",
	"_post_the_refund",
	"request_refund",
	"approve_refund",
	"reject_refund",
	"complete_refund",
)
_REFUND_ENTRY_POINTS = ("request_refund", "approve_refund", "reject_refund", "complete_refund")


def _func_body(src: str, name: str) -> str:
	start = src.index(f"def {name}(")
	rest = src[start:]
	ends = [pos for pos in (rest.find("\ndef ", 1), rest.find("\n__all__", 1)) if pos != -1]
	return rest[: min(ends)] if ends else rest


class RefundCommandSourceTest(unittest.TestCase):
	"""The orderings the money depends on, asserted where a reader can see them."""

	@classmethod
	def setUpClass(cls):
		with open(_SRC, encoding="utf-8") as fh:
			cls.src = fh.read()
		cls.bodies = {name: _func_body(cls.src, name) for name in _REFUND_FUNCTIONS}

	def test_the_row_is_locked_before_it_is_read(self):
		body = self.bodies["_locked_transfer"]
		self.assertIn("for_update=True", body)
		self.assertLess(body.index("for_update=True"), body.index("frappe.get_doc(TRANSFER"))

	def test_every_state_read_goes_through_the_lock(self):
		"""Ordering is not enough: the state must be read THROUGH the lock.

		This bench runs REPEATABLE READ. `SELECT ... FOR UPDATE` returns the latest
		committed row but does not advance the transaction's consistent-read
		snapshot, and in a Frappe request that snapshot is already open by the time
		the handler runs. So a step that locks and then reads with a plain
		`frappe.get_doc` gets the pre-race row: `Registered`, `refund_status` as it
		was. It would approve a refund on a transfer that has just been paid out.

		`RefundRaceTest` proves the same thing behaviourally. Both are kept: the
		behavioural one can only see the paths a test happens to drive, this one
		sees every read in the file.
		"""
		for name in _REFUND_FUNCTIONS:
			for read in _STATE_READS.findall(self.bodies[name]):
				with self.subTest(f"{name}: {read}"):
					self.assertIn("for_update=True", read, f"{name} decides on a non-locking read")

	def test_no_refund_step_reads_a_transfer_column_off_the_lock(self):
		"""The other way to read stale state: a single-column `db.get_value`.

		It is not covered by the test above and it is the easier mistake — one line,
		no doc, and it reads from the same stale snapshot.
		"""
		for name in _REFUND_FUNCTIONS:
			for read in _COLUMN_READS.findall(self.bodies[name]):
				with self.subTest(f"{name}: {read}"):
					self.assertIn("for_update=True", read, f"{name} reads a transfer column unlocked")

	def test_every_entry_point_opens_through_the_one_locked_read(self):
		"""One choke point, so no step can acquire half the discipline."""
		for name in _REFUND_ENTRY_POINTS:
			with self.subTest(name):
				self.assertIn("_locked_transfer(", self.bodies[name])

	def test_the_locked_read_carries_the_tenant_check(self):
		self.assertIn("_assert_company_scope(", self.bodies["_locked_transfer"])

	def test_approval_revalidates_the_operational_state_after_the_lock(self):
		"""Council decision D32, and the reason this slice exists.

		A role check answers "may this person approve refunds" — true of the manager
		whatever the row is doing. Without the state re-check under the lock a
		transfer can be paid out AND refunded, and the second writer wins silently.
		"""
		body = self.bodies["approve_refund"]
		self.assertIn("_assert_refundable(", body)
		self.assertLess(body.index("_locked_transfer("), body.index("_assert_refundable("))

	def test_completion_revalidates_the_state_before_it_posts(self):
		body = self.bodies["complete_refund"]
		self.assertIn("_assert_refundable(", body)
		self.assertLess(body.index("_assert_refundable("), body.index("_post_the_refund("))
		self.assertLess(body.index("_locked_transfer("), body.index("_post_the_refund("))

	def test_the_request_revalidates_the_state_too(self):
		body = self.bodies["request_refund"]
		self.assertIn("_assert_refundable(", body)
		self.assertLess(body.index("_locked_transfer("), body.index("_assert_refundable("))

	def test_the_operational_state_is_what_gets_rechecked(self):
		"""Pins WHICH fields the re-check reads. A guard that re-read only
		`refund_status` would pass every ordering test above and still let a paid-out
		transfer be refunded."""
		body = self.bodies["_assert_refundable"]
		self.assertIn("operational_status", body)
		self.assertIn("accounting_status", body)

	def test_approving_posts_nothing(self):
		"""Approval carries authority; completion moves cash. Collapsing them is how
		a refund gets paid without anyone counting it."""
		self.assertNotIn("post_refund", self.bodies["approve_refund"])
		self.assertNotIn("post_refund", self.bodies["reject_refund"])
		self.assertNotIn("post_refund", self.bodies["request_refund"])

	def test_rejection_is_deliberately_not_gated_on_refundability(self):
		"""Pinned decision, not an oversight.

		A request that sat in the queue while the receiver collected the cash must
		still be closeable. Requiring the transfer to be refundable would strand the
		row in `Requested` for good, with a manual database edit as the only exit.
		"""
		self.assertNotIn("_assert_refundable(", self.bodies["reject_refund"])

	def test_the_decision_and_the_desk_are_different_role_sets(self):
		"""A cashier who could approve their own request is not a control."""
		self.assertIn("_assert_refund_manager()", self.bodies["approve_refund"])
		self.assertIn("_assert_refund_manager()", self.bodies["reject_refund"])
		self.assertIn("_assert_refund_desk()", self.bodies["request_refund"])
		self.assertIn("_assert_refund_desk()", self.bodies["complete_refund"])

	def test_the_gates_name_only_roles_a_patch_actually_creates(self):
		"""A gate keyed on a role nobody creates locks everyone out; a gate keyed on a
		placeholder lets everyone in. Both are silent, so the two files are compared.

		`v87_remittance_roles.py` (stabler-tvma) is what puts these Roles in the
		database. If a refund gate ever names something that patch does not create,
		this fails rather than shipping a door with no lock in it.
		"""
		with open(_ROLE_PATCH_SRC, encoding="utf-8") as fh:
			patch = fh.read()
		created = set(re.findall(r'"([^"]+)"', re.search(r"_ROLES = \((.*?)\)", patch, re.S).group(1)))
		self.assertIn(MANAGER, created, "the role patch no longer creates the finance manager role")

		# The gates no longer carry their own role tuples: they read `_remittance_actions`,
		# the same table every read path answers `allowed_actions` with, so an action
		# offered to a role the endpoint then refuses is not expressible. That module is
		# Frappe-free, so the real tuples are read here rather than re-parsed out of source.
		from stabler.api import _remittance_actions

		named = set(_remittance_actions.DESK_ROLES) | set(_remittance_actions.MANAGER_ROLES)
		named -= set(_remittance_actions._LEGACY_APPROVER_ROLES)  # pre-existing, not created by v87
		self.assertIn(MANAGER, named)
		self.assertEqual(named - created - {"System Manager"}, set())

	def test_the_cbu_band_is_neither_widened_nor_overridden(self):
		"""stabler-22vj is an open policy decision. This slice makes the refusal
		legible and changes nothing about the band itself."""
		# The two shapes a workaround would actually take: reaching into the
		# validator, or setting the flag that switches it off. Prose about the band
		# is fine and is the point — the bead reference is what carries the decision
		# forward to whoever settles it.
		self.assertNotIn("from stabler.api._accounts", self.src)
		self.assertNotIn("ignore_exchange_rate", self.src)
		self.assertIn("stabler-22vj", self.src)


class _RefundCase(unittest.TestCase):
	"""Shared setup: one registered, posted transfer and a role the test can change."""

	roles = (CASHIER,)
	refund_raises: Exception | None = None

	def setUp(self):
		self.db = _FakeDB()
		self.api, self.roles_now, self.remittance = _load(
			self.db, roles=self.roles, refund_raises=self.refund_raises
		)
		self.code = "ABCD2345"
		self.name = self.db.add_transfer(pickup_code_hash=self.remittance.store_pickup_code(self.code))

	def _as(self, *roles):
		self.roles_now[:] = list(roles)

	def _request(self, **overrides):
		request = {"name": self.name, "reason": "Receiver never came", "client_request_id": "ref-req-1"}
		request.update(overrides)
		return self.api.request_refund(**request)

	def _approve(self, **overrides):
		request = {"name": self.name, "client_request_id": "ref-ok-1"}
		request.update(overrides)
		return self.api.approve_refund(**request)

	def _reject(self, **overrides):
		request = {"name": self.name, "reason": "Sender changed their mind", "client_request_id": "ref-no-1"}
		request.update(overrides)
		return self.api.reject_refund(**request)

	def _complete(self, **overrides):
		request = {"name": self.name, "client_request_id": "ref-done-1"}
		request.update(overrides)
		return self.api.complete_refund(**request)

	def _payout(self, **overrides):
		request = {"name": self.name, "pickup_code": self.code, "client_request_id": "pay-1"}
		request.update(overrides)
		return self.api.payout_transfer(**request)

	def _approved(self):
		"""Drive the row to Approved through the real endpoints, not by seeding."""
		self._as(CASHIER)
		self._request()
		self._as(MANAGER)
		self._approve()
		self._as(CASHIER)

	@property
	def row(self):
		return self.db.rows[self.name]

	@property
	def event_types(self):
		return [event["event_type"] for event in self.db.events]


class RefundRequestTest(_RefundCase):
	def test_a_request_records_the_ask_and_moves_no_cash(self):
		result = self._request()

		self.assertEqual(result["refund_status"], "Requested")
		self.assertEqual(result["operational_status"], "Registered")
		# The obligation is untouched: nothing is reversed until the cash is counted.
		self.assertEqual(result["accounting_status"], "Posted")
		self.assertIsNone(result["refund_journal_entry"])
		self.assertIn(self.name, self.db.locked)

	def test_the_request_is_recorded_at_the_origin_desk_with_its_reason(self):
		self._request(reason="Receiver moved to Bukhara")

		self.assertEqual(self.event_types, ["Refund request"])
		event = self.db.events[0]
		self.assertEqual(event["branch"], "Tashkent")
		self.assertEqual(event["client_request_id"], "ref-req-1")
		self.assertIn("Receiver moved to Bukhara", event["details"])

	def test_every_mutation_returns_a_version(self):
		self.assertEqual(self._request()["version"], self.row["modified"])

	def test_a_reason_is_required(self):
		"""It is the only field on the whole three-step path that carries why."""
		with self.assertRaises(_Thrown) as caught:
			self._request(reason="   ")

		self.assertIn("reason is required", str(caught.exception))
		self.assertEqual(self.row["refund_status"], "None")

	def test_a_missing_request_id_is_refused(self):
		with self.assertRaises(_Thrown):
			self._request(client_request_id="  ")

		self.assertEqual(self.row["refund_status"], "None")

	def test_an_unknown_transfer_is_refused(self):
		with self.assertRaises(_Thrown) as caught:
			self._request(name="REM-2026-99999")

		self.assertIn("does not exist", str(caught.exception))

	def test_a_paid_out_transfer_cannot_be_refund_requested(self):
		self.row["operational_status"] = "Paid Out"

		with self.assertRaises(_Thrown) as caught:
			self._request()

		self.assertIn("Paid Out", str(caught.exception))
		self.assertEqual(self.row["refund_status"], "None")

	def test_an_unposted_transfer_cannot_be_refund_requested(self):
		"""There is no obligation to reverse, so there is nothing to refund."""
		self.row["accounting_status"] = "Unposted"

		with self.assertRaises(_Thrown) as caught:
			self._request()

		self.assertIn("no posted obligation", str(caught.exception))

	def test_a_replayed_key_returns_the_original_and_records_one_request(self):
		first = self._request()
		replay = self._request()

		self.assertFalse(first["replayed"])
		self.assertTrue(replay["replayed"])
		self.assertEqual(self.event_types, ["Refund request"])

	def test_a_second_request_under_a_new_key_is_refused(self):
		self._request()

		with self.assertRaises(_Thrown) as caught:
			self._request(client_request_id="ref-req-2")

		self.assertIn("awaiting a decision", str(caught.exception))

	def test_a_rejected_request_can_be_made_again(self):
		"""A rejection ends the request, not the transfer. Refusing a second ask
		would leave the sender with no path but a database edit."""
		self._request()
		self._as(MANAGER)
		self._reject()
		self._as(CASHIER)

		result = self._request(client_request_id="ref-req-2", reason="Manager asked for the receipt")

		self.assertEqual(result["refund_status"], "Requested")
		self.assertEqual(self.event_types, ["Refund request", "Refund rejection", "Refund request"])

	def test_the_second_request_is_replayed_on_its_own_key_not_the_first(self):
		"""The trail holds two `Refund request` events by then; the one that counts
		is the latest."""
		self._request()
		self._as(MANAGER)
		self._reject()
		self._as(CASHIER)
		self._request(client_request_id="ref-req-2")

		replay = self._request(client_request_id="ref-req-2")

		self.assertTrue(replay["replayed"])
		self.assertEqual(self.event_types.count("Refund request"), 2)

	def test_a_user_with_no_remittance_role_cannot_request(self):
		"""There is nothing else in the way: whitelist admits any session, `db_set`
		checks no permission, and the refund entry is inserted ignoring permissions."""
		self._as("Employee")

		with self.assertRaises(_Thrown):
			self._request()

		self.assertEqual(self.row["refund_status"], "None")

	def test_a_viewer_cannot_request(self):
		self._as(VIEWER)

		with self.assertRaises(_Thrown):
			self._request()

	def test_a_manager_may_also_request(self):
		self._as(MANAGER)

		self.assertEqual(self._request()["refund_status"], "Requested")


class RefundApprovalTest(_RefundCase):
	def setUp(self):
		super().setUp()
		self._request()
		self._as(MANAGER)

	def test_an_approval_authorises_and_moves_no_cash(self):
		result = self._approve()

		self.assertEqual(result["refund_status"], "Approved")
		self.assertEqual(result["operational_status"], "Registered")
		# The whole point of the two steps: authority now, cash at the desk later.
		self.assertEqual(result["accounting_status"], "Posted")
		self.assertIsNone(result["refund_journal_entry"])
		self.assertEqual(self.event_types, ["Refund request", "Refund approval"])

	def test_the_approval_is_recorded_with_its_actor_and_note(self):
		self._approve(note="Documents checked at the counter")

		event = self.db.events[-1]
		self.assertEqual(event["event_type"], "Refund approval")
		self.assertIn("desk@example.com", event["details"])
		self.assertIn("Documents checked at the counter", event["details"])

	def test_a_cashier_cannot_approve(self):
		"""An approval the requester can grant themselves is not an approval."""
		self._as(CASHIER)

		with self.assertRaises(_Thrown) as caught:
			self._approve()

		self.assertIn("Remittance Finance Manager", str(caught.exception))
		self.assertEqual(self.row["refund_status"], "Requested")

	def test_an_auditor_cannot_approve(self):
		self._as(AUDITOR)

		with self.assertRaises(_Thrown):
			self._approve()

		self.assertEqual(self.row["refund_status"], "Requested")

	def test_a_system_manager_can_approve(self):
		"""It already holds every DocPerm on the aggregate; excluding it would only
		mean a locked-out site is repaired by hand."""
		self._as("System Manager")

		self.assertEqual(self._approve()["refund_status"], "Approved")

	def test_approving_without_a_request_is_refused(self):
		self.row["refund_status"] = "None"

		with self.assertRaises(_Thrown) as caught:
			self._approve()

		self.assertIn("no refund request to approve", str(caught.exception))
		self.assertEqual(self.row["refund_status"], "None")

	def test_approving_a_rejected_request_is_refused(self):
		self._reject()

		with self.assertRaises(_Thrown):
			self._approve(client_request_id="ref-ok-2")

		self.assertEqual(self.row["refund_status"], "Rejected")

	def test_a_replayed_key_returns_the_original_and_approves_once(self):
		first = self._approve()
		replay = self._approve()

		self.assertFalse(first["replayed"])
		self.assertTrue(replay["replayed"])
		self.assertEqual(self.event_types.count("Refund approval"), 1)

	def test_a_second_approval_under_a_new_key_is_refused(self):
		self._approve()

		with self.assertRaises(_Thrown) as caught:
			self._approve(client_request_id="ref-ok-2")

		self.assertIn("already has an approved refund", str(caught.exception))

	def test_an_unposted_obligation_cannot_be_approved_for_refund(self):
		self.row["accounting_status"] = "Unposted"

		with self.assertRaises(_Thrown) as caught:
			self._approve()

		self.assertIn("no posted obligation", str(caught.exception))


class RefundRejectionTest(_RefundCase):
	def setUp(self):
		super().setUp()
		self._request()
		self._as(MANAGER)

	def test_a_rejection_closes_the_request_and_moves_nothing(self):
		result = self._reject()

		self.assertEqual(result["refund_status"], "Rejected")
		self.assertEqual(result["operational_status"], "Registered")
		self.assertEqual(result["accounting_status"], "Posted")
		self.assertIsNone(result["refund_journal_entry"])

	def test_the_rejection_is_its_own_event_with_the_reason(self):
		"""Filed under `Refund rejection`, not under `Refund approval` with a sad
		note — a trail you have to read the free text of is not a trail."""
		self._reject(reason="No proof the receiver was told")

		event = self.db.events[-1]
		self.assertEqual(event["event_type"], "Refund rejection")
		self.assertIn("No proof the receiver was told", event["details"])
		self.assertEqual(event["branch"], "Tashkent")

	def test_a_reason_is_required(self):
		with self.assertRaises(_Thrown) as caught:
			self._reject(reason=" ")

		self.assertIn("reason is required", str(caught.exception))
		self.assertEqual(self.row["refund_status"], "Requested")

	def test_a_cashier_cannot_reject(self):
		self._as(CASHIER)

		with self.assertRaises(_Thrown):
			self._reject()

		self.assertEqual(self.row["refund_status"], "Requested")

	def test_rejecting_without_a_request_is_refused(self):
		self.row["refund_status"] = "None"

		with self.assertRaises(_Thrown) as caught:
			self._reject()

		self.assertIn("no refund request to reject", str(caught.exception))

	def test_rejecting_an_approved_refund_is_refused(self):
		"""Once approved, the exit is the completion or a new decision trail — a
		rejection here would silently cancel an authorisation."""
		self._approve()

		with self.assertRaises(_Thrown):
			self._reject(client_request_id="ref-no-2")

		self.assertEqual(self.row["refund_status"], "Approved")

	def test_a_stale_request_on_a_paid_out_transfer_can_still_be_rejected(self):
		"""Deliberate asymmetry: rejection moves no money, and refusing it would
		strand the row in Requested with a manual edit as the only way out."""
		self.row["operational_status"] = "Paid Out"

		result = self._reject()

		self.assertEqual(result["refund_status"], "Rejected")
		self.assertEqual(self.event_types[-1], "Refund rejection")

	def test_a_replayed_key_returns_the_original_and_rejects_once(self):
		first = self._reject()
		replay = self._reject()

		self.assertFalse(first["replayed"])
		self.assertTrue(replay["replayed"])
		self.assertEqual(self.event_types.count("Refund rejection"), 1)

	def test_a_second_rejection_under_a_new_key_is_refused(self):
		self._reject()

		with self.assertRaises(_Thrown) as caught:
			self._reject(client_request_id="ref-no-2")

		self.assertIn("already has a rejected refund", str(caught.exception))


class RefundCompletionTest(_RefundCase):
	def setUp(self):
		super().setUp()
		self._approved()

	def test_completion_posts_and_transitions_under_the_lock(self):
		result = self._complete()

		self.assertEqual(result["operational_status"], "Refunded")
		self.assertEqual(result["refund_status"], "Completed")
		self.assertEqual(result["accounting_status"], "Reversed")
		self.assertEqual(result["refund_journal_entry"], "JE-REM-0003")
		# The code dies with the transfer: the cash left the origin desk, so there is
		# nothing at the destination counter left to collect.
		self.assertEqual(result["verification_status"], "Expired")
		self.assertIn(self.name, self.db.locked)

	def test_the_entry_is_posted_before_the_transfer_is_marked_refunded(self):
		"""A reader catching the row mid-command must never see Refunded with the
		obligation still open."""
		self._complete()

		order = [patch for _name, patch in self.db.writes]
		posted = next(i for i, patch in enumerate(order) if patch.get("refund_journal_entry"))
		refunded = next(i for i, patch in enumerate(order) if patch.get("operational_status") == "Refunded")
		self.assertLess(posted, refunded)

	def test_the_completion_is_recorded_at_the_origin_desk(self):
		self._complete()

		event = self.db.events[-1]
		self.assertEqual(event["event_type"], "Refund completion")
		self.assertEqual(event["branch"], "Tashkent")
		self.assertIn("Amina", event["details"])
		self.assertIn("1010.0", event["details"])

	def test_the_whole_trail_is_four_events_in_order(self):
		self._complete()

		self.assertEqual(self.event_types, ["Refund request", "Refund approval", "Refund completion"])

	def test_completing_an_unapproved_request_is_refused(self):
		"""The two steps exist so that nobody both authorises and pays."""
		self.row["refund_status"] = "Requested"

		with self.assertRaises(_Thrown) as caught:
			self._complete()

		self.assertIn("only goes back out on an approved refund", str(caught.exception))
		self.assertIsNone(self.row.get("refund_journal_entry"))
		self.assertEqual(self.row["accounting_status"], "Posted")

	def test_completing_a_rejected_refund_is_refused(self):
		self.row["refund_status"] = "Rejected"

		with self.assertRaises(_Thrown):
			self._complete()

		self.assertIsNone(self.row.get("refund_journal_entry"))

	def test_completing_with_no_refund_at_all_is_refused(self):
		self.row["refund_status"] = "None"

		with self.assertRaises(_Thrown):
			self._complete()

		self.assertIsNone(self.row.get("refund_journal_entry"))

	def test_a_replayed_key_returns_the_original_and_posts_once(self):
		first = self._complete()
		replay = self._complete()

		self.assertFalse(first["replayed"])
		self.assertTrue(replay["replayed"])
		self.assertEqual(replay["refund_journal_entry"], "JE-REM-0003")
		self.assertEqual(self.event_types.count("Refund completion"), 1)

	def test_a_second_completion_under_a_new_key_is_refused(self):
		"""A fresh key on a refunded transfer is a second withdrawal, not a retry."""
		self._complete()

		with self.assertRaises(_Thrown) as caught:
			self._complete(client_request_id="ref-done-2")

		self.assertIn("already been refunded", str(caught.exception))

	def test_a_user_with_no_remittance_role_cannot_complete(self):
		self._as("Employee")

		with self.assertRaises(_Thrown):
			self._complete()

		self.assertIsNone(self.row.get("refund_journal_entry"))

	def test_a_viewer_cannot_complete(self):
		self._as(VIEWER)

		with self.assertRaises(_Thrown):
			self._complete()

		self.assertIsNone(self.row.get("refund_journal_entry"))

	def test_a_refunded_transfer_can_no_longer_be_paid_out(self):
		"""End to end, through both commands: the cash leaves once."""
		self._complete()

		with self.assertRaises(_Thrown):
			self._payout()

		self.assertEqual(self.row["operational_status"], "Refunded")


class RefundRaceTest(_RefundCase):
	"""Concurrent payout versus refund — a named acceptance test, not an edge case.

	Each test opens the loser's snapshot BEFORE the winner commits, so a step that
	reads state without `for_update=True` sees the pre-race row. With the locking
	read the loser refuses; without it, it writes on top of the winner and the
	transfer is both paid out and refunded.
	"""

	def test_a_payout_that_wins_the_race_refuses_the_approval(self):
		self._request()
		self._as(MANAGER)
		# The manager's request opens its snapshot here: Registered, refund Requested.
		self.db.open_snapshot(self.name)
		# ...and the cashier at the destination collects the cash and commits first.
		self._as(CASHIER)
		self._payout()
		self._as(MANAGER)

		with self.assertRaises(_Thrown) as caught:
			self._approve()

		self.assertIn("Paid Out", str(caught.exception))
		self.assertEqual(self.row["refund_status"], "Requested")
		self.assertEqual(self.row["operational_status"], "Paid Out")

	def test_a_payout_that_wins_the_race_refuses_the_completion(self):
		"""The dangerous half: this is the step that would reverse the obligation a
		second time, on cash that has already left the destination drawer.

		The payout here is staged directly rather than driven through
		`payout_transfer`, and that is not a shortcut. Once the refund is Approved,
		`_assert_payable` refuses the new payout command — so the writer that can
		still reach this state is one that does not consult `refund_status` at all.
		That writer exists today: `api/remittance.py` contains no `for_update`
		anywhere and its payout works off the Journal Entry chain, not this row.
		"""
		self._approved()
		self.db.open_snapshot(self.name)
		self.db.write(self.name, {"operational_status": "Paid Out", "verification_status": "Consumed"})

		with self.assertRaises(_Thrown) as caught:
			self._complete()

		self.assertIn("Paid Out", str(caught.exception))
		self.assertIsNone(self.row.get("refund_journal_entry"))
		self.assertEqual(self.row["accounting_status"], "Posted")
		self.assertEqual(self.row["refund_status"], "Approved")

	def test_a_payout_that_wins_the_race_refuses_a_fresh_request(self):
		self.db.open_snapshot(self.name)
		self._payout()

		with self.assertRaises(_Thrown) as caught:
			self._request()

		self.assertIn("Paid Out", str(caught.exception))
		self.assertEqual(self.row["refund_status"], "None")

	def test_a_refund_that_wins_the_race_refuses_the_payout(self):
		"""The mirror. `_assert_payable` reads the same row through the same lock."""
		self._request()
		# The cashier's payout screen was drawn while the refund was merely Requested,
		# which deliberately does not block a payout. The approval lands in between.
		self.db.open_snapshot(self.name)
		self._as(MANAGER)
		self._approve()
		self._as(CASHIER)

		with self.assertRaises(_Thrown) as caught:
			self._payout()

		self.assertIn("refund", str(caught.exception).lower())
		self.assertEqual(self.row["operational_status"], "Registered")
		self.assertIsNone(self.row.get("payout_journal_entry"))

	def test_a_completed_refund_wins_over_a_later_payout(self):
		self._approved()
		self.db.open_snapshot(self.name)
		self._complete()

		with self.assertRaises(_Thrown):
			self._payout()

		self.assertEqual(self.row["operational_status"], "Refunded")
		self.assertIsNone(self.row.get("payout_journal_entry"))

	def test_the_race_fake_really_does_serve_a_stale_row(self):
		"""Guards the guard: if `open_snapshot` stopped diverging, every test in this
		class would pass on code that reads unlocked, and none of them would say so."""
		self.db.open_snapshot(self.name)
		self.db.write(self.name, {"operational_status": "Paid Out"})

		self.assertEqual(self.db.read(self.name, locked=True)["operational_status"], "Paid Out")
		self.assertEqual(self.db.read(self.name, locked=False)["operational_status"], "Registered")


class RefundRateBandTest(_RefundCase):
	"""ADR-008's frozen rate versus the +/-20% CBU band — stabler-22vj, left alone.

	The band is not widened, overridden or routed around here. What is tested is
	that when it refuses, the refusal says which transfer and which frozen rate,
	instead of surfacing as a bare sentence about a conversion rate the cashier
	never typed.
	"""

	refund_raises = _Thrown(
		"Conversion rate 12000.0 is outside the allowed CBU tolerance band (+/-20%) for USD to UZS."
	)

	def test_the_band_refusal_names_the_transfer_and_the_frozen_rate(self):
		self._approved()

		with self.assertRaises(_Thrown) as caught:
			self._complete()

		message = str(caught.exception)
		self.assertIn(self.name, message)
		self.assertIn("12000.0", message)
		# The validator's own words are carried, not replaced: the cause has to
		# survive the wrapping or the wrapping is just noise.
		self.assertIn("CBU tolerance band", message)

	def test_a_refused_refund_leaves_the_transfer_exactly_as_it_was(self):
		self._approved()

		with self.assertRaises(_Thrown):
			self._complete()

		self.assertEqual(self.row["operational_status"], "Registered")
		self.assertEqual(self.row["refund_status"], "Approved")
		self.assertEqual(self.row["accounting_status"], "Posted")
		self.assertIsNone(self.row.get("refund_journal_entry"))

	def test_the_refusal_can_be_retried_once_the_policy_question_is_settled(self):
		"""It stays Approved, so the same manager decision still stands."""
		self._approved()
		with self.assertRaises(_Thrown):
			self._complete()

		self.assertEqual(self.row["refund_status"], "Approved")


class RefundFaultTest(_RefundCase):
	"""A programming or database fault must not come back dressed as a refund refusal."""

	refund_raises = RuntimeError("the accounting module is broken")

	def test_a_non_validation_error_propagates_unchanged(self):
		self._approved()

		with self.assertRaises(RuntimeError) as caught:
			self._complete()

		self.assertEqual(str(caught.exception), "the accounting module is broken")


if __name__ == "__main__":
	unittest.main()
