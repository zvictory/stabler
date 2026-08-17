"""The pickup-digest guard, proved against a real site instead of a model of one.

`test_remittance_transfer_doctype.py` covers the guard bench-free, against a
hand-built Document whose `get_permlevel_access` returns whatever the test sets.
That proves the guard reads its own inputs correctly. It cannot prove the two
things the guard actually exists for:

* that Frappe really DOES silently discard `pickup_code_hash` (permlevel 1) when
  the saving user's roles carry no write grant at that level — nothing anywhere
  ran the real `Document.validate_higher_perm_levels`; and
* that a real user, holding a real role, calling the real whitelisted command on
  a real site, is refused — rather than storing a transfer that can never be
  paid out because its code digest is empty.

A fake `get_permlevel_access` is a value this suite chooses. The real one is
derived from `tabDocPerm` and `tabHas Role`. Those come apart exactly when it
matters: when the permlevel patch has not run on a site. That is the state this
file reproduces, and it is why deleting the permlevel-1 rows is the fixture
rather than an act of vandalism — v87 creates the roles, v89 adds the grant, and
a site that got the first without the second is precisely what the guard's own
message tells the operator to go and fix.

The negative case alone would pass against a guard that refused everyone, so
every refusal here is paired with the same call succeeding once the grant is
back.

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
		# From v87_remittance_roles. Ensured here so a site that has not migrated
		# fails on the guard, not on the fixture.
		_ensure("Role", CASHIER, {"role_name": CASHIER, "desk_access": 0})

	def setUp(self) -> None:
		super().setUp()
		self.origin = _ensure("Branch", "REM-PERMLEVEL-ORIGIN", {"branch": "REM-PERMLEVEL-ORIGIN"})
		self.destination = _ensure("Branch", "REM-PERMLEVEL-DEST", {"branch": "REM-PERMLEVEL-DEST"})
		self._user(CASHIER_EMAIL, CASHIER)
		self.addCleanup(frappe.set_user, "Administrator")

	def tearDown(self) -> None:
		frappe.db.rollback()
		# The meta cache is process-level and outlives the rollback. Without this,
		# a later module in the same `make test-bench` run would inherit a
		# Remittance Transfer whose permlevel-1 grant this file deleted.
		frappe.clear_cache(doctype=TRANSFER)

	# -- fixtures -----------------------------------------------------------

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

	def _become_the_cashier(self) -> None:
		frappe.set_user(CASHIER_EMAIL)
		# A user who does not actually hold the role is refused for a different
		# reason entirely, and every assertion below would pass for it.
		self.assertIn(CASHIER, frappe.get_roles(), "the role fixture did not land")

	def _grant_levels(self) -> set:
		return {
			perm.permlevel
			for perm in frappe.get_meta(TRANSFER).permissions
			if perm.role in frappe.get_roles() and perm.get("write")
		}

	def _unrun_the_permlevel_patch(self) -> None:
		"""Put the site in the state the guard's own message describes.

		v87 creates the remittance roles; v89 adds their permlevel-1 write grant.
		Deleting the permlevel-1 rows reproduces a site that got the first and
		not the second — the only state in which Frappe discards the digest.
		DML on `tabDocPerm` rather than saving the DocType: a DocType save runs
		schema sync, which the test transaction could not roll back.
		"""
		frappe.db.delete("DocPerm", {"parent": TRANSFER, "permlevel": 1})
		frappe.clear_cache(doctype=TRANSFER)

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
		does not exist yet and dies with AttributeError. Only ``insert()`` calls
		it in a state where it works, which is another reason a hand-built fake
		could never have shown any of this.
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

		Every existing test asserts what the guard does GIVEN that Frappe wipes
		the field. Nothing asserted that it wipes it — and the harm is not the
		wipe, it is the row: a transfer whose pickup code can never be matched,
		accepted at the counter with the customer's cash. That row is what this
		test produces, and it is what the guard exists to make unreachable.
		"""
		self._unrun_the_permlevel_patch()
		self._become_the_cashier()
		self.assertNotIn(1, self._grant_levels(), "the fixture did not remove the grant")

		name = self._insert_with_the_guard_out_of_the_way(self._draft())

		self.assertFalse(
			frappe.db.get_value(TRANSFER, name, DIGEST_FIELD),
			"the site is expected to discard a permlevel-1 field the saver cannot write",
		)

	def test_the_digest_reaches_the_row_for_a_role_that_holds_the_grant(self):
		"""The other half: the loss is caused by the missing grant, nothing else.

		Same user, same document, same insert — only the grant differs. Without
		this, a Frappe that dropped the field for everyone, or a fixture that
		broke the document some other way, would satisfy the test above and the
		guard would be defending against a cause that was never established.
		"""
		self._become_the_cashier()
		self.assertIn(1, self._grant_levels(), "this site has not run the permlevel patch")

		name = self._insert_with_the_guard_out_of_the_way(self._draft())

		self.assertEqual(frappe.db.get_value(TRANSFER, name, DIGEST_FIELD), DIGEST)

	def test_a_grantless_role_is_refused_when_it_registers(self):
		"""The operator-visible claim: no transfer is stored that cannot be paid.

		Registering is the only way a digest is ever written, so this is the one
		path on which the loss would be silent and permanent.
		"""
		self._unrun_the_permlevel_patch()
		self._become_the_cashier()
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

	def test_the_same_registration_is_not_refused_once_the_grant_is_there(self):
		"""The differential for the refusal above, on the same command.

		A guard that refused every cashier would satisfy the previous test. Same
		user, same call, same site — only the grant differs — and this time the
		digest has to reach the stored row.

		The command is allowed to fail LATER: genesis-test.local has no
		Remittance Settings for the test company, so `post_register` cannot book
		the obligation. Seeding a ledger is not this bead's subject and would
		make the test fail for reasons that have nothing to do with permlevels.
		What is pinned is narrower and is exactly the claim: the registration is
		not refused for the digest, and the row it inserted carries one. Both
		assertions still hold on a site that IS configured, where nothing raises.
		"""
		self._become_the_cashier()
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
