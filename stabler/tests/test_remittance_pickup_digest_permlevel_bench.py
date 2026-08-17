"""The pickup-digest guard, proved against a real site instead of a model of one.

`test_remittance_transfer_doctype.py` covers the guard bench-free, against a
hand-built Document whose `get_permlevel_access` returns whatever the test sets.
That proves the guard reads its own inputs correctly. It cannot prove the two
things the guard actually exists for:

* that the site really DOES silently discard `pickup_code_hash` (permlevel 1)
  when the saving user's roles carry no write grant at that level — nothing
  anywhere ran the real `Document.validate_higher_perm_levels`; and
* that a real user, holding a real role, calling the real whitelisted command on
  a real site, is refused — rather than storing a transfer that can never be
  paid out because its code digest is empty.

A fake `get_permlevel_access` is a value this suite chooses. The real one is
derived from `tabDocPerm` and `tabHas Role`, and those come apart exactly when
it matters: on a site where the permlevel patch has not run.

WHY THE GRANTLESS SIDE USES A ROLE OF ITS OWN. No shipped role fits "may create
a transfer, holds no permlevel-1 write": Cashier and Finance Manager hold both,
Viewer and Auditor hold neither, so their insert is refused by document
permission long before the guard runs. The obvious fixture — delete the
permlevel-1 DocPerm rows to reproduce a site that got v87 without v89 — is the
one thing this file must not do. The rows come back on rollback, but the doctype
meta rebuilt from them is written to a Redis cache that is shared by every
`bench run-tests` process and is not transactional (the Makefile runs one
process per module, so Redis, not memory, is what they have in common). An
interrupted run would leave genesis-test.local serving a Remittance Transfer
with no permlevel-1 grant, failing every later registration for a cause that no
longer exists in the database, until someone thought to run `bench clear-cache`.

So the fixture only ever ADDS: a throwaway role with `create` at permlevel 0 and
no write grant anywhere. `get_permlevel_access("write")` returns `[]` for it for
precisely the reason it would on an unpatched site, so Frappe resets the digest
and the guard throws identically — and the worst a leaked cache entry can carry
is one extra grant for a role nobody holds.

The grant-present half then uses the REAL `Remittance Cashier`, which also makes
these tests notice if v89 is ever reverted on a site.

A negative-only suite would pass against a guard that refused everyone, so every
refusal here is paired with the same path succeeding for a role that is granted.

Bench-only by derivation: not in `.github/frappe-free-tests.txt`, so the
Makefile's BENCH_TESTS picks it up automatically.

    cd ~/frappe-bench-local && bench --site <test-site> run-tests \\
        --module stabler.tests.test_remittance_pickup_digest_permlevel_bench
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api.remittance_commands import register_remittance
from stabler.stabler.doctype.remittance_transfer.remittance_transfer import RemittanceTransfer

TRANSFER = "Remittance Transfer"
DIGEST_FIELD = "pickup_code_hash"
DIGEST = "s1$0123456789abcdef$deadbeef"

CASHIER = "Remittance Cashier"
CASHIER_EMAIL = "rem-permlevel-cashier@example.com"

#: Stands in for a Cashier on a site that got v87 and not v89. Not a shipped
#: role, and deliberately not one: see the module docstring.
GRANTLESS_ROLE = "_Test Remittance Permlevel Gap"
GRANTLESS_EMAIL = "rem-permlevel-grantless@example.com"


def _ensure(doctype: str, name: str, values: dict) -> str:
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	return doc.name


class PickupDigestPermlevelOnALiveSite(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		companies = frappe.get_all("Company", pluck="name", order_by="creation asc", limit=1)
		if not companies:
			raise AssertionError("No Company on this site — no transfer can be registered.")
		cls.company = companies[0]
		cls.currency = frappe.db.get_value("Company", cls.company, "default_currency")

	def setUp(self) -> None:
		super().setUp()
		# Every fixture is per-test, not per-class: this class rolls back in
		# tearDown, so anything seeded in setUpClass would survive only the first
		# test and the rest would die on the fixture instead of on the guard.
		_ensure("Role", CASHIER, {"role_name": CASHIER, "desk_access": 0})  # from v87
		self._ensure_the_grantless_role()

		self.origin = _ensure("Branch", "REM-PERMLEVEL-ORIGIN", {"branch": "REM-PERMLEVEL-ORIGIN"})
		self.destination = _ensure("Branch", "REM-PERMLEVEL-DEST", {"branch": "REM-PERMLEVEL-DEST"})
		self._user(CASHIER_EMAIL, CASHIER)
		self._user(GRANTLESS_EMAIL, GRANTLESS_ROLE)
		self.addCleanup(frappe.set_user, "Administrator")

	def tearDown(self) -> None:
		frappe.db.rollback()
		# Redundant on the happy path — frappe's cache_manager already clears the
		# doctype cache on rollback — but this file writes a DocPerm row, and the
		# meta cache it feeds is Redis-backed and shared with every other
		# `bench run-tests` process, so the clear is stated rather than assumed.
		frappe.clear_cache(doctype=TRANSFER)

	# -- fixtures -----------------------------------------------------------

	def _ensure_the_grantless_role(self) -> None:
		"""Add a role that may create a transfer and may not write permlevel 1.

		Additive on purpose. A DocPerm row rather than a Custom DocPerm: one
		Custom DocPerm on a doctype makes Frappe ignore the shipped permissions
		entirely, which would silently disarm every other permission this
		doctype has.
		"""
		_ensure("Role", GRANTLESS_ROLE, {"role_name": GRANTLESS_ROLE, "desk_access": 0})
		if frappe.db.exists("DocPerm", {"parent": TRANSFER, "role": GRANTLESS_ROLE}):
			return
		frappe.get_doc(
			{
				"doctype": "DocPerm",
				"parent": TRANSFER,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": GRANTLESS_ROLE,
				"permlevel": 0,
				"read": 1,
				"create": 1,
			}
		).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=TRANSFER)

	def _user(self, email: str, role: str) -> None:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": role,
					"send_welcome_email": 0,
					"roles": [{"role": role}],
				}
			).insert(ignore_permissions=True)
			return
		user = frappe.get_doc("User", email)
		if role not in {r.role for r in user.roles}:
			user.append("roles", {"role": role})
			user.save(ignore_permissions=True)

	def _become(self, email: str, role: str) -> None:
		frappe.set_user(email)
		# A user who does not actually hold the role is refused for a different
		# reason entirely, and every assertion below would pass for it.
		self.assertIn(role, frappe.get_roles(), f"the {role} fixture did not land")

	def _grant_levels(self) -> set:
		return {
			perm.permlevel
			for perm in frappe.get_meta(TRANSFER).permissions
			if perm.role in frappe.get_roles() and perm.get("write")
		}

	def _draft(self, **overrides):
		return frappe.get_doc(
			{
				"doctype": TRANSFER,
				"company": self.company,
				"sender_name": "Amina Yusupova",
				"receiver_name": "Bekzod Tursunov",
				"origin_branch": self.origin,
				"destination_branch": self.destination,
				"send_currency": self.currency,
				"receive_currency": self.currency,
				"commission_mode": "Inclusive",
				"commission_pct": 1,
				"principal": 990.10,
				"commission": 9.90,
				"tendered": 1000.00,
				"receiver_amount": 990.10,
				"exchange_rate": 1,
				"operational_status": "Draft",
				"accounting_status": "Unposted",
				"verification_status": "Not Issued",
				"refund_status": "None",
				"code_attempts": 0,
				"client_request_id": frappe.generate_hash(length=12),
				DIGEST_FIELD: DIGEST,
				**overrides,
			}
		)

	def _insert_with_the_guard_out_of_the_way(self, doc) -> str:
		"""Insert past our own guard, to see what the SITE does unaided.

		The guard's whole purpose is to make this state unreachable, so the only
		way to observe the state is to stand the guard down for one insert. What
		is left running is Frappe's real ``validate_higher_perm_levels`` — the
		thing no test in this repo had ever executed.

		It cannot simply be called directly: on an unsaved document Frappe's
		``reset_values_if_no_permlevel_access`` dereferences a ``ref_doc`` that
		does not exist yet and dies with AttributeError. Only ``insert()`` reaches
		it in a state where it works, which is one more thing a hand-built fake
		could never have shown.
		"""
		with patch.object(RemittanceTransfer, "_assert_new_rows_carry_the_code_digest", lambda _self: None):
			doc.insert()
		return doc.name

	def _register(self, key: str):
		return register_remittance(
			company=self.company,
			origin_branch=self.origin,
			destination_branch=self.destination,
			send_currency=self.currency,
			receive_currency=self.currency,
			sender_name="Amina Yusupova",
			receiver_name="Bekzod Tursunov",
			amount=1000,
			exchange_rate=1,
			client_request_id=key,
			commission_mode="Exclusive",
			commission_pct=1,
		)

	# -- what only a live site can show -------------------------------------

	def test_the_site_really_stores_a_transfer_nobody_can_collect(self):
		"""The premise the whole guard rests on, executed for the first time.

		Every existing test asserts what the guard does GIVEN that the site wipes
		the field. Nothing asserted that it wipes it — and the harm is not the
		wipe, it is the row: a transfer whose pickup code can never be matched,
		accepted at the counter with the customer's cash already taken. That row
		is what this test produces, and it is what the guard makes unreachable.
		"""
		self._become(GRANTLESS_EMAIL, GRANTLESS_ROLE)
		self.assertNotIn(1, self._grant_levels(), "the grantless fixture is not grantless")

		name = self._insert_with_the_guard_out_of_the_way(self._draft())

		self.assertFalse(
			frappe.db.get_value(TRANSFER, name, DIGEST_FIELD),
			"the site is expected to discard a permlevel-1 field the saver cannot write",
		)

	def test_the_digest_reaches_the_row_for_the_role_that_holds_the_grant(self):
		"""The other half: the loss is caused by the missing grant, nothing else.

		Same document, same insert, the real shipped Cashier — so this also fails
		if v89 is ever reverted and the people who register money lose the grant.
		Without it, a Frappe that dropped the field for everyone, or a fixture
		that broke the document some other way, would satisfy the test above and
		the guard would be defending against a cause never established.
		"""
		self._become(CASHIER_EMAIL, CASHIER)
		self.assertIn(1, self._grant_levels(), "this site has not run the permlevel patch (v89)")

		name = self._insert_with_the_guard_out_of_the_way(self._draft())

		self.assertEqual(frappe.db.get_value(TRANSFER, name, DIGEST_FIELD), DIGEST)

	def test_a_role_without_the_grant_is_refused_when_it_registers(self):
		"""The operator-visible claim: no transfer is stored that cannot be paid.

		Registering is the only path on which a digest is ever written, so it is
		the only path on which the loss would be silent and permanent. This is
		the case the bead asked for, and the one that fails if the guard is
		removed.
		"""
		self._become(GRANTLESS_EMAIL, GRANTLESS_ROLE)
		key = frappe.generate_hash(length=12)

		with self.assertRaises(frappe.ValidationError) as caught:
			self._register(key)

		message = str(caught.exception)
		self.assertIn("permlevel 1", message, "the refusal must name what is wrong")
		self.assertIn("patch", message, "and what to do about it")
		self.assertFalse(
			frappe.db.exists(TRANSFER, {"client_request_id": key}),
			"a refused registration must leave no transfer behind",
		)

	def test_the_shipped_cashier_is_not_refused_when_it_registers(self):
		"""The differential for the refusal above, on the same command.

		A guard that refused every cashier would satisfy the previous test.

		The command is allowed to fail LATER: genesis-test.local has no
		Remittance Settings for the test company, so `post_register` cannot book
		the obligation. Seeding a ledger is not this bead's subject and would
		make this fail for reasons that have nothing to do with permlevels. What
		is pinned is exactly the claim — the registration is not refused for the
		digest, and the row it inserted carries one. Both assertions still hold
		on a configured site, where nothing raises at all.
		"""
		self._become(CASHIER_EMAIL, CASHIER)
		key = frappe.generate_hash(length=12)

		try:
			self._register(key)
		except frappe.ValidationError as err:
			self.assertNotIn("permlevel 1", str(err), "a granted cashier must not be refused for the digest")

		stored = frappe.db.get_value(
			TRANSFER, {"client_request_id": key}, ["name", DIGEST_FIELD], as_dict=True
		)
		self.assertIsNotNone(stored, "the registration stored no transfer at all")
		self.assertTrue(stored.get(DIGEST_FIELD), "the stored transfer carries no pickup-code digest")
