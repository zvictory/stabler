"""The payout command: the lock, the code, and the counter that survives a refusal.

Payout is where the cash actually leaves the drawer, so three separate things have
to hold and each is tested the way it can actually fail.

**The lock.** Asserted twice, exactly as `test_remittance_register_command` does:
once against the source text — the cheap check a reader can see — and once against
a fake database that refuses to hand out a transfer, or to post its payout entry,
on a row nobody locked. The source assertion alone would pass on code that locks a
different row; the behavioural one alone would pass on code that locks after
deciding, if the fake were ever loosened.

**The code.** The hashing helpers are the REAL ones from `stabler.api.remittance`,
imported against stubs the way `test_remittance_pickup_code` imports them, because
faking a compare that is supposed to be constant-time and salted would test
nothing. That is what lets the plaintext case be a real test: a stored value that
was never migrated must not open the drawer, and it must not cost the receiver an
attempt either.

**The counter.** `frappe.throw` rolls the transaction back, so a failed-attempt
counter written and then thrown over is a counter that was never written — the
lockout would be unreachable and the brute force free. The fake records commits so
the ordering can be asserted rather than assumed.

Bench-free: the bench set is not part of `make check`, so a test needing one would
not gate a push. The ledger side of payout is proved on a real ledger in
`test_remittance_accounting_bench.py`.
"""

from __future__ import annotations

import importlib
import os
import types
import unittest

from stabler.tests.module_sandbox import ModuleSandbox

_MODULE = "stabler.api.remittance_commands"
_SRC = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api", "remittance_commands.py"
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

_MANAGER_ROLES = ("Accounts Manager", "System Manager", "Stabler Admin")


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
		self.events: list[dict] = []
		self.settings: dict[str, dict] = {}
		self.locked: set[str] = set()
		self.writes: list[tuple[str, dict]] = []
		self.commits = 0
		self._seq = 0

	# --- the refusal that makes this a test and not a mock ------------------ #
	def require_lock(self, name: str, what: str) -> None:
		if name not in self.locked:
			raise AssertionError(f"{what} on {name} happened without the row lock")

	# --- seeding ------------------------------------------------------------ #
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
			"registered_at": "2026-08-17 09:00:00",
			"modified": "2026-08-17 10:00:00",
		}
		row.update(fields)
		self.rows[name] = row
		return name

	def insert(self, fields: dict) -> None:
		if fields.get("doctype") == EVENT:
			self.events.append(dict(fields))
			return
		raise AssertionError(f"unexpected insert of {fields.get('doctype')}")

	def write(self, name: str, patch: dict) -> None:
		self.rows[name].update(patch)
		self.rows[name]["modified"] = "2026-08-17 11:00:00"
		self.writes.append((name, dict(patch)))

	# --- frappe.db surface -------------------------------------------------- #
	def get_default(self, key):
		return 2 if key == "currency_precision" else None

	def get_value(self, doctype, filters, fieldname=None, for_update=False):
		if doctype == SETTINGS:
			return (self.settings.get(filters) or {}).get(fieldname)
		if doctype == EVENT:
			match = next(
				(
					event
					for event in self.events
					if all(event.get(field) == value for field, value in filters.items())
				),
				None,
			)
			return match.get(fieldname) if match else None
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
		if or_filters:
			rows = [
				row
				for row in rows
				if any(
					str(pattern).strip("%").lower() in str(row.get(field) or "").lower()
					for field, _op, pattern in or_filters
				)
			]
		return [{field: row.get(field) for field in (fields or [])} for row in rows[: limit or None]]

	def commit(self):
		self.commits += 1


def _load(db: _FakeDB, *, roles=("Cashier",)):
	_SANDBOX.evict(*_FAKED)

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.db = db
	frappe.session = types.SimpleNamespace(user="cashier@example.com")
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn
	frappe.get_roles = lambda user=None: list(roles)
	frappe.PermissionError = PermissionError
	frappe.UniqueValidationError = type("UniqueValidationError", (Exception,), {})
	frappe.DuplicateEntryError = frappe.UniqueValidationError

	def _get_doc(source, name=None):
		if name is not None:
			# The whole point of the lock: state read for a decision must be locked.
			db.require_lock(name, "state read")
			return _Doc(db, db.rows[name])
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
	approvals._APPROVER_ROLES = _MANAGER_ROLES

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

	# The REAL hashing helpers, imported against the stubs above. A faked compare
	# would make every pickup-code assertion below a tautology.
	remittance = importlib.import_module("stabler.api.remittance")

	accounting = types.ModuleType("stabler.api.remittance_accounting")

	def _post_payout(transfer, *, posting_date=None, submit=True):
		# The obligation must never be closed off an unlocked row.
		db.require_lock(transfer.name, "payout posting")
		transfer.db_set("payout_journal_entry", "JE-REM-0002", notify=False)
		return {"journal_entry": "JE-REM-0002"}

	accounting.post_payout = _post_payout
	accounting.post_register = lambda transfer, **_k: {"journal_entry": "JE-REM-0001"}

	_SANDBOX.install({"stabler.api.remittance": remittance, "stabler.api.remittance_accounting": accounting})
	return importlib.import_module(_MODULE), remittance


def _func_body(src: str, name: str) -> str:
	start = src.index(f"def {name}(")
	rest = src[start:]
	ends = [pos for pos in (rest.find("\ndef ", 1), rest.find("\n__all__", 1)) if pos != -1]
	return rest[: min(ends)] if ends else rest


class PayoutCommandSourceTest(unittest.TestCase):
	"""The orderings the money depends on, asserted where a reader can see them."""

	@classmethod
	def setUpClass(cls):
		with open(_SRC, encoding="utf-8") as fh:
			cls.src = fh.read()
		cls.body = _func_body(cls.src, "payout_transfer")
		cls.unlock = _func_body(cls.src, "unlock_pickup_code")
		cls.refusal = _func_body(cls.src, "_refuse_the_code")

	def test_the_row_is_locked(self):
		self.assertIn("for_update=True", self.body)

	def test_lock_precedes_the_state_read(self):
		# Deciding on unlocked state is the double payout: both cashiers see
		# Registered, both hand over the cash.
		self.assertLess(self.body.index("for_update=True"), self.body.index("frappe.get_doc(TRANSFER"))

	def test_lock_precedes_the_code_check(self):
		self.assertLess(self.body.index("for_update=True"), self.body.index("_verify_the_code("))

	def test_lock_precedes_the_posting(self):
		self.assertLess(self.body.index("for_update=True"), self.body.index("post_payout("))

	def test_unlock_locks_the_row_before_reading_it(self):
		self.assertLess(self.unlock.index("for_update=True"), self.unlock.index("frappe.get_doc(TRANSFER"))

	def test_the_attempt_is_committed_before_the_refusal(self):
		"""A throw rolls back — an uncommitted lockout never happened."""
		self.assertLess(self.refusal.index("frappe.db.commit()"), self.refusal.index("frappe.throw("))

	def test_no_lockout_expiry_is_implemented(self):
		"""Contested policy: a manager is the only exit until someone decides.

		A lockout that quietly expires on a timer is indistinguishable from one
		that was never applied. Reading the setting needs the field name as a
		string literal, so its absence is what pins the decision down; the prose
		around it is free to explain why.
		"""
		self.assertFalse(
			'"lockout_minutes"' in self.src,
			"lockout_minutes is read — a time-based auto-unlock is an open policy question",
		)


class PayoutTest(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.api, self.remittance = _load(self.db)
		self.code = "ABCD2345"
		self.name = self.db.add_transfer(pickup_code_hash=self.remittance.store_pickup_code(self.code))

	def _payout(self, **overrides):
		request = {"name": self.name, "pickup_code": self.code, "client_request_id": "pay-1"}
		request.update(overrides)
		return self.api.payout_transfer(**request)

	def test_payout_posts_and_transitions_under_the_lock(self):
		result = self._payout()

		self.assertEqual(result["operational_status"], "Paid Out")
		self.assertEqual(result["verification_status"], "Consumed")
		self.assertEqual(result["payout_journal_entry"], "JE-REM-0002")
		self.assertIn(self.name, self.db.locked)

	def test_the_entry_is_posted_before_the_transfer_is_marked_paid(self):
		"""A reader catching the row mid-command must never see Paid Out with an
		obligation still open."""
		self._payout()

		order = [patch for _name, patch in self.db.writes]
		posted = next(i for i, patch in enumerate(order) if patch.get("payout_journal_entry"))
		paid = next(i for i, patch in enumerate(order) if patch.get("operational_status") == "Paid Out")
		self.assertLess(posted, paid)

	def test_every_mutation_returns_a_version(self):
		result = self._payout()

		self.assertEqual(result["version"], self.db.rows[self.name]["modified"])

	def test_payout_appends_an_event(self):
		self._payout()

		self.assertEqual([event["event_type"] for event in self.db.events], ["Payout"])
		self.assertEqual(self.db.events[0]["client_request_id"], "pay-1")
		self.assertEqual(self.db.events[0]["branch"], "Samarkand")

	def test_the_code_is_typed_loosely_and_still_verifies(self):
		# The receiver reads it off a slip; case and spacing are not the secret.
		self._payout(pickup_code=f"  {self.code.lower()} ")

		self.assertEqual(self.db.rows[self.name]["operational_status"], "Paid Out")

	def test_a_wrong_code_pays_out_nothing(self):
		with self.assertRaises(_Thrown):
			self._payout(pickup_code="ZZZZ9999")

		self.assertEqual(self.db.rows[self.name]["operational_status"], "Registered")
		self.assertIsNone(self.db.rows[self.name].get("payout_journal_entry"))

	def test_a_wrong_code_costs_an_attempt_that_reaches_disk(self):
		"""The counter is the whole defence — and a throw rolls the transaction back."""
		with self.assertRaises(_Thrown):
			self._payout(pickup_code="ZZZZ9999")

		self.assertEqual(self.db.rows[self.name]["code_attempts"], 1)
		self.assertEqual(self.db.commits, 1)
		self.assertEqual([event["event_type"] for event in self.db.events], ["Failed code attempt"])

	def test_the_fifth_wrong_code_locks_the_transfer(self):
		for _attempt in range(5):
			with self.assertRaises(_Thrown):
				self._payout(pickup_code="ZZZZ9999")

		row = self.db.rows[self.name]
		self.assertEqual(row["code_attempts"], 5)
		self.assertEqual(row["code_locked"], 1)
		self.assertEqual(row["verification_status"], "Locked")
		self.assertEqual(row["code_locked_at"], "2026-08-17 11:00:00")
		self.assertIn("Lock", [event["event_type"] for event in self.db.events])

	def test_a_locked_transfer_refuses_even_the_correct_code(self):
		"""Otherwise the lockout is decoration: the attacker's next guess is free."""
		for _attempt in range(5):
			with self.assertRaises(_Thrown):
				self._payout(pickup_code="ZZZZ9999")

		with self.assertRaises(_Thrown):
			self._payout()

		self.assertEqual(self.db.rows[self.name]["operational_status"], "Registered")
		# A refusal on an already-locked row must not inflate the counter further.
		self.assertEqual(self.db.rows[self.name]["code_attempts"], 5)

	def test_the_attempt_limit_comes_from_settings(self):
		self.db.settings["Mikas"] = {"max_code_attempts": 3}

		for _attempt in range(3):
			with self.assertRaises(_Thrown):
				self._payout(pickup_code="ZZZZ9999")

		self.assertEqual(self.db.rows[self.name]["code_locked"], 1)

	def test_a_plaintext_stored_code_never_opens_the_drawer(self):
		"""The pre-hash format must not verify — accepting it reinstates the defect
		it replaced, where anyone who could read the field could collect the cash."""
		self.db.rows[self.name]["pickup_code_hash"] = self.code

		with self.assertRaises(_Thrown) as caught:
			self._payout()

		self.assertIn("bench migrate", str(caught.exception))
		# And it is not the receiver's mistake, so it must not spend their attempts.
		self.assertEqual(self.db.rows[self.name]["code_attempts"], 0)

	def test_an_unposted_obligation_is_never_paid_out(self):
		"""Registered + Unposted would debit an obligation that was never created."""
		self.db.rows[self.name]["accounting_status"] = "Unposted"

		with self.assertRaises(_Thrown) as caught:
			self._payout()

		self.assertIn("never posted", str(caught.exception))
		self.assertIsNone(self.db.rows[self.name].get("payout_journal_entry"))

	def test_a_refunded_transfer_is_refused(self):
		self.db.rows[self.name]["operational_status"] = "Refunded"

		with self.assertRaises(_Thrown):
			self._payout()

	def test_an_approved_refund_blocks_the_payout(self):
		"""The cash is already committed back to the sender at the origin desk."""
		self.db.rows[self.name]["refund_status"] = "Approved"

		with self.assertRaises(_Thrown):
			self._payout()

	def test_a_requested_refund_does_not_block_the_payout(self):
		"""A request is not a commitment; letting it freeze the receiver's cash
		would turn the refund form into a denial of service on the counter."""
		self.db.rows[self.name]["refund_status"] = "Requested"

		self.assertEqual(self._payout()["operational_status"], "Paid Out")

	def test_a_replayed_key_returns_the_original_and_does_not_pay_twice(self):
		first = self._payout()
		replay = self._payout()

		self.assertFalse(first["replayed"])
		self.assertTrue(replay["replayed"])
		self.assertEqual(replay["payout_journal_entry"], "JE-REM-0002")
		self.assertEqual([event["event_type"] for event in self.db.events], ["Payout"])

	def test_a_second_payout_under_a_new_key_is_refused(self):
		"""A fresh key on a paid transfer is a second withdrawal, not a retry."""
		self._payout()

		with self.assertRaises(_Thrown) as caught:
			self._payout(client_request_id="pay-2")

		self.assertIn("already been paid out", str(caught.exception))

	def test_a_missing_request_id_is_refused(self):
		with self.assertRaises(_Thrown):
			self._payout(client_request_id="  ")

		self.assertEqual(self.db.rows[self.name]["operational_status"], "Registered")

	def test_an_unknown_transfer_is_refused(self):
		with self.assertRaises(_Thrown):
			self._payout(name="REM-2026-99999")


class PayoutQueueTest(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.api, _remittance = _load(self.db)

	def test_the_queue_excludes_registered_but_unposted(self):
		"""Offering it would let a cashier debit an obligation that was never created."""
		payable = self.db.add_transfer()
		self.db.add_transfer(accounting_status="Unposted")

		rows = self.api.payout_queue("Mikas")

		self.assertEqual([row["name"] for row in rows], [payable])

	def test_the_queue_excludes_transfers_that_are_already_paid(self):
		payable = self.db.add_transfer()
		self.db.add_transfer(operational_status="Paid Out")

		self.assertEqual([row["name"] for row in self.api.payout_queue("Mikas")], [payable])

	def test_another_companys_transfers_are_not_listed(self):
		mine = self.db.add_transfer()
		self.db.add_transfer(company="Anjan")

		self.assertEqual([row["name"] for row in self.api.payout_queue("Mikas")], [mine])

	def test_the_receiver_can_be_found_by_name(self):
		"""v1 could only match an exact id, which sent the cashier off the screen."""
		wanted = self.db.add_transfer(receiver_name="Dilnoza Karimova")
		self.db.add_transfer(receiver_name="Bekzod")

		rows = self.api.payout_queue("Mikas", query="dilnoza")

		self.assertEqual([row["name"] for row in rows], [wanted])

	def test_the_sender_can_be_found_by_name(self):
		wanted = self.db.add_transfer(sender_name="Aziz Rahimov")
		self.db.add_transfer(sender_name="Amina")

		rows = self.api.payout_queue("Mikas", query="Rahimov")

		self.assertEqual([row["name"] for row in rows], [wanted])

	def test_the_reference_and_the_id_still_match(self):
		wanted = self.db.add_transfer(client_request_id="ref-9001")
		self.db.add_transfer()

		self.assertEqual([row["name"] for row in self.api.payout_queue("Mikas", query="ref-9001")], [wanted])
		self.assertEqual([row["name"] for row in self.api.payout_queue("Mikas", query=wanted)], [wanted])

	def test_the_queue_never_hands_out_the_code(self):
		"""A digest plus a 32-glyph alphabet is a short offline search."""
		self.db.add_transfer(pickup_code_hash="s1$salt$digest")

		row = self.api.payout_queue("Mikas")[0]

		self.assertNotIn("pickup_code_hash", row)
		self.assertNotIn("pickup_code", row)


class UnlockTest(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.code = "ABCD2345"

	def _locked_transfer(self, api, remittance):
		return self.db.add_transfer(
			pickup_code_hash=remittance.store_pickup_code(self.code),
			code_locked=1,
			code_attempts=5,
			verification_status="Locked",
			code_locked_at="2026-08-17 10:30:00",
		)

	def test_a_cashier_cannot_unlock(self):
		"""A lockout a cashier can lift is not a lockout."""
		api, remittance = _load(self.db, roles=("Cashier",))
		name = self._locked_transfer(api, remittance)

		with self.assertRaises(_Thrown):
			api.unlock_pickup_code(name)

		self.assertEqual(self.db.rows[name]["code_locked"], 1)

	def test_a_manager_unlocks_and_the_counter_goes_back_to_zero(self):
		"""Leaving the counter at the limit would re-lock on the next mistype,
		which is not an unlock."""
		api, remittance = _load(self.db, roles=("Accounts Manager",))
		name = self._locked_transfer(api, remittance)

		result = api.unlock_pickup_code(name, reason="ID checked at the desk")

		self.assertEqual(result["code_locked"], 0)
		self.assertEqual(result["code_attempts"], 0)
		self.assertEqual(self.db.rows[name]["verification_status"], "Active")
		self.assertIsNone(self.db.rows[name]["code_locked_at"])
		self.assertIn(name, self.db.locked)

	def test_the_unlock_is_the_exit_from_the_lockout(self):
		"""End to end: the right code opens the drawer again, and only after a
		manager has been through it."""
		api, remittance = _load(self.db, roles=("Accounts Manager",))
		name = self._locked_transfer(api, remittance)

		with self.assertRaises(_Thrown):
			api.payout_transfer(name=name, pickup_code=self.code, client_request_id="pay-1")
		api.unlock_pickup_code(name)
		result = api.payout_transfer(name=name, pickup_code=self.code, client_request_id="pay-1")

		self.assertEqual(result["operational_status"], "Paid Out")

	def test_the_unlock_is_recorded(self):
		api, remittance = _load(self.db, roles=("Accounts Manager",))
		name = self._locked_transfer(api, remittance)

		api.unlock_pickup_code(name, reason="ID checked at the desk")

		self.assertEqual([event["event_type"] for event in self.db.events], ["Unlock"])
		self.assertIn("ID checked at the desk", self.db.events[0]["details"])

	def test_unlocking_twice_is_not_an_error(self):
		"""Two managers pressing the button must not produce a failure."""
		api, remittance = _load(self.db, roles=("Accounts Manager",))
		name = self._locked_transfer(api, remittance)

		api.unlock_pickup_code(name)
		result = api.unlock_pickup_code(name)

		self.assertEqual(result["code_locked"], 0)
		self.assertEqual([event["event_type"] for event in self.db.events], ["Unlock"])

	def test_a_paid_out_transfer_cannot_be_unlocked(self):
		"""There is no pickup left; reopening the code would only invite a second one."""
		api, remittance = _load(self.db, roles=("Accounts Manager",))
		name = self._locked_transfer(api, remittance)
		self.db.rows[name]["operational_status"] = "Paid Out"

		with self.assertRaises(_Thrown):
			api.unlock_pickup_code(name)


if __name__ == "__main__":
	unittest.main()
