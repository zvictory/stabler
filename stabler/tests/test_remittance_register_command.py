"""The register command: the lock, the replay and the code that is shown once.

These are the invariants a document cannot enforce about its own callers, so they
are tested here rather than in `test_remittance_transfer_doctype`.

Two of them are tested twice on purpose. The ordering of the row lock is asserted
against the source text — the cheap check that survives a refactor moving the call
into a helper — and again behaviourally, against a fake database that refuses any
state read or posting on a row nobody locked. The source assertion alone would pass
on code that locks a different row; the behavioural one alone would pass on code
that locks after deciding, if the fake were ever loosened. Precedents for both:
`test_imports_api_invariants.py` and `test_crm_company_scope.py`.

Bench-free: the bench set is not part of `make check`, so a test needing one would
not gate a push. The ledger side of registration is proved on a real ledger in
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


def tearDownModule():
	"""The fakes below are process-wide — hand ``sys.modules`` back intact."""
	_SANDBOX.restore()


class _Thrown(Exception):
	"""Stands in for frappe.throw, which raises rather than returns."""


class _Duplicate(Exception):
	"""Stands in for the MariaDB 1062 a unique index raises."""


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

	def reload(self):
		# The whole point of the lock: state read for a decision must be locked state.
		self._db.require_lock(self.name, "state re-read")
		object.__setattr__(self, "_fields", dict(self._db.rows[self.name]))
		return self

	def db_set(self, patch, value=None, notify=True):
		patch = patch if isinstance(patch, dict) else {patch: value}
		self._fields.update(patch)
		self._db.write(self.name, patch)


class _FakeDB:
	def __init__(self):
		self.rows: dict[str, dict] = {}
		self.locked: set[str] = set()
		self.writes: list[tuple[str, dict]] = []
		self.events: list[dict] = []
		self.rollbacks = 0
		self.inserts = 0
		self.duplicate_on_insert = False
		self._seq = 0

	# --- the refusal that makes this a test and not a mock ------------------ #
	def require_lock(self, name: str, what: str) -> None:
		if name not in self.locked:
			raise AssertionError(f"{what} on {name} happened without the row lock")

	def insert(self, fields: dict) -> None:
		if fields.get("doctype") == "Remittance Event":
			self.events.append(dict(fields))
			return
		key = fields.get("client_request_id")
		if self.duplicate_on_insert:
			# A rival worker won the unique index a microsecond ago: the row now
			# exists, and only the index knows it — the caller's pre-check missed.
			self.duplicate_on_insert = False
			self._store(dict(fields))
		if any(row.get("client_request_id") == key for row in self.rows.values()):
			raise _Duplicate("Duplicate entry 'KEY' for key 'client_request_id' (1062)")
		self._store(fields)

	def _store(self, fields: dict) -> None:
		self._seq += 1
		fields["name"] = f"REM-2026-{self._seq:05d}"
		fields["modified"] = f"2026-08-17 10:00:0{self._seq}"
		self.rows[fields["name"]] = dict(fields)
		self.inserts += 1

	def write(self, name: str, patch: dict) -> None:
		self.rows[name].update(patch)
		self.rows[name]["modified"] = "2026-08-17 10:30:00"
		self.writes.append((name, dict(patch)))

	# --- frappe.db surface -------------------------------------------------- #
	def get_default(self, key):
		return 2 if key == "currency_precision" else None

	def get_value(self, doctype, filters, fieldname=None, for_update=False):
		if isinstance(filters, dict):
			match = next(
				(
					row
					for row in self.rows.values()
					if all(row.get(field) == value for field, value in filters.items())
				),
				None,
			)
			return match.get(fieldname) if match else None
		if for_update:
			self.locked.add(filters)
		row = self.rows.get(filters)
		return row.get(fieldname) if row else None

	def rollback(self):
		self.rollbacks += 1


def _load(db: _FakeDB):
	_SANDBOX.evict(
		_MODULE,
		"frappe",
		"frappe.utils",
		"stabler.api._common",
		"stabler.api.approvals",
		"stabler.api.remittance",
		"stabler.api.remittance_accounting",
	)

	frappe = types.ModuleType("frappe")

	def _throw(message, *_a, **_k):
		raise _Thrown(message)

	frappe.throw = _throw
	frappe._ = lambda s: s
	frappe.db = db
	frappe.session = types.SimpleNamespace(user="cashier@example.com")
	frappe.whitelist = lambda *_a, **_k: lambda fn: fn
	frappe.UniqueValidationError = _Duplicate
	frappe.DuplicateEntryError = _Duplicate

	def _get_doc(source, name=None):
		if name is not None:
			return _Doc(db, db.rows[name])
		return _Doc(db, source)

	frappe.get_doc = _get_doc

	utils = types.ModuleType("frappe.utils")
	utils.cint = lambda value: int(value or 0)
	utils.flt = lambda value, precision=None: (
		round(float(value or 0), precision) if precision is not None else float(value or 0)
	)
	utils.get_datetime_str = lambda value: str(value)
	utils.now_datetime = lambda: "2026-08-17 10:30:00"
	utils.nowdate = lambda: "2026-08-17"
	frappe.utils = utils

	common = types.ModuleType("stabler.api._common")
	common._require_company = lambda company: company
	approvals = types.ModuleType("stabler.api.approvals")
	approvals._assert_company_scope = lambda company: None
	# Imported by the payout command, which shares this module with register.
	approvals._APPROVER_ROLES = ("Accounts Manager", "System Manager", "Stabler Admin")

	remittance = types.ModuleType("stabler.api.remittance")
	remittance._gen_pickup_code = lambda: "ABC123"
	remittance.store_pickup_code = lambda code: f"sha256$salt${code}"
	remittance.is_hashed_pickup_code = lambda stored: bool(stored)
	remittance._pickup_code_matches = lambda stored, provided: False

	accounting = types.ModuleType("stabler.api.remittance_accounting")

	def _post_register(transfer, *, posting_date=None, submit=True):
		# The obligation must never be posted off an unlocked row.
		db.require_lock(transfer.name, "register posting")
		transfer.db_set(
			{"accounting_status": "Posted", "register_journal_entry": "JE-REM-0001"}, notify=False
		)
		return {"journal_entry": "JE-REM-0001", "register_base_rate": 1}

	accounting.post_register = _post_register
	accounting.post_payout = lambda transfer, **_k: {"journal_entry": "JE-REM-0002"}

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.utils": utils,
			"stabler.api._common": common,
			"stabler.api.approvals": approvals,
			"stabler.api.remittance": remittance,
			"stabler.api.remittance_accounting": accounting,
		}
	)
	return importlib.import_module(_MODULE)


def _request(**overrides) -> dict:
	request = {
		"company": "Mikas",
		"origin_branch": "Tashkent",
		"destination_branch": "Samarkand",
		"send_currency": "USD",
		"receive_currency": "EUR",
		"sender_name": "Amina",
		"receiver_name": "Bekzod",
		"amount": 1000,
		"exchange_rate": 0.92,
		"client_request_id": "req-1",
		"commission_mode": "Exclusive",
		"commission_pct": 1,
	}
	request.update(overrides)
	return request


def _func_body(src: str, name: str) -> str:
	start = src.index(f"def {name}(")
	rest = src[start:]
	ends = [pos for pos in (rest.find("\ndef ", 1), rest.find("\n__all__", 1)) if pos != -1]
	return rest[: min(ends)] if ends else rest


class RegisterCommandSourceTest(unittest.TestCase):
	"""The ordering the transaction depends on, asserted where a reader can see it."""

	@classmethod
	def setUpClass(cls):
		with open(_SRC, encoding="utf-8") as fh:
			cls.body = _func_body(fh.read(), "register_remittance")

	def test_the_row_is_locked(self):
		self.assertIn("for_update=True", self.body)

	def test_lock_precedes_the_state_read(self):
		# Deciding on unlocked state is the double-post: both callers read Unposted.
		self.assertLess(self.body.index("for_update=True"), self.body.index("transfer.reload()"))

	def test_lock_precedes_the_posting(self):
		self.assertLess(self.body.index("for_update=True"), self.body.index("post_register("))


class RegisterCommandTest(unittest.TestCase):
	def setUp(self):
		self.db = _FakeDB()
		self.api = _load(self.db)

	def test_register_posts_and_transitions_under_the_lock(self):
		result = self.api.register_remittance(**_request())

		self.assertEqual(result["operational_status"], "Registered")
		self.assertEqual(result["accounting_status"], "Posted")
		self.assertEqual(result["register_journal_entry"], "JE-REM-0001")
		self.assertIn(result["name"], self.db.locked)

	def test_registered_is_never_written_before_posted(self):
		"""Registered + Unposted must be unreachable, not merely rejected.

		A reader that catches the row between the two writes must never see a
		registered transfer whose obligation has not been posted.
		"""
		self.api.register_remittance(**_request())

		order = [patch for _name, patch in self.db.writes]
		posted = next(i for i, patch in enumerate(order) if patch.get("accounting_status") == "Posted")
		registered = next(
			i for i, patch in enumerate(order) if patch.get("operational_status") == "Registered"
		)
		self.assertLess(posted, registered)

	def test_the_triple_is_priced_not_taken_from_the_caller(self):
		result = self.api.register_remittance(**_request())

		self.assertEqual(result["principal"], 1000.0)
		self.assertEqual(result["commission"], 10.0)
		self.assertEqual(result["tendered"], 1010.0)
		# ADR-006: the obligation crosses at the principal, never at the tendered.
		self.assertEqual(result["receiver_amount"], 920.0)

	def test_every_mutation_returns_a_version(self):
		"""Without a version the caller cannot pass `modified` back to check_concurrency."""
		result = self.api.register_remittance(**_request())

		self.assertEqual(result["version"], self.db.rows[result["name"]]["modified"])

	def test_registration_appends_an_event(self):
		result = self.api.register_remittance(**_request())

		self.assertEqual([event["event_type"] for event in self.db.events], ["Register"])
		self.assertEqual(self.db.events[0]["transfer"], result["name"])
		self.assertEqual(self.db.events[0]["client_request_id"], "req-1")

	def test_pickup_code_is_returned_once_and_stored_hashed(self):
		first = self.api.register_remittance(**_request())
		replay = self.api.register_remittance(**_request())

		self.assertEqual(first["pickup_code"], "ABC123")
		# A replay is how a captured request would ask for the code a second time.
		self.assertIsNone(replay["pickup_code"])
		# The row keeps the hash and no plaintext column to read it back from.
		self.assertTrue(self.db.rows[first["name"]]["pickup_code_hash"])
		self.assertIsNone(self.db.rows[first["name"]].get("pickup_code"))

	def test_replay_returns_the_original_and_does_not_register_twice(self):
		first = self.api.register_remittance(**_request())
		replay = self.api.register_remittance(**_request())

		self.assertEqual(replay["name"], first["name"])
		self.assertTrue(replay["replayed"])
		self.assertFalse(first["replayed"])
		self.assertEqual(self.db.inserts, 1)
		self.assertEqual(len(self.db.events), 1)

	def test_replay_with_a_different_amount_is_refused(self):
		self.api.register_remittance(**_request())

		with self.assertRaises(_Thrown) as caught:
			self.api.register_remittance(**_request(amount=2000))

		# Silently returning the first transfer would hide a client bug that
		# charged the customer one figure and registered another.
		message = str(caught.exception)
		self.assertIn("principal", message)
		self.assertEqual(self.db.inserts, 1)

	def test_replay_with_a_different_rate_is_refused(self):
		self.api.register_remittance(**_request())

		with self.assertRaises(_Thrown) as caught:
			self.api.register_remittance(**_request(exchange_rate=0.93))

		self.assertIn("exchange_rate", str(caught.exception))

	def test_a_missing_request_id_is_refused(self):
		with self.assertRaises(_Thrown):
			self.api.register_remittance(**_request(client_request_id="  "))
		self.assertEqual(self.db.inserts, 0)

	def test_the_duplicate_key_race_yields_to_the_winner(self):
		"""The SELECT and the INSERT are not atomic; the unique index settles it."""
		self.db.duplicate_on_insert = True

		result = self.api.register_remittance(**_request())

		self.assertEqual(self.db.rollbacks, 1)
		# One key, one transfer — the loser must not leave a second row behind.
		self.assertEqual(self.db.inserts, 1)
		self.assertTrue(result["replayed"])
		self.assertIsNone(result["pickup_code"])

	def test_a_non_duplicate_insert_failure_is_not_swallowed(self):
		def _boom(fields):
			raise RuntimeError("disk on fire")

		self.db.insert = _boom

		with self.assertRaises(RuntimeError):
			self.api.register_remittance(**_request())


if __name__ == "__main__":
	unittest.main()
