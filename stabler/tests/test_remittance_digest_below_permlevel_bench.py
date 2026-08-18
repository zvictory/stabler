"""The digest reaches the row, and no longer needs the site to have been migrated.

`pickup_code_hash` is permlevel 1 and stays that way -- not because of anything this
SPA calls (it makes no generic read against this doctype), but because
`/api/resource/Remittance Transfer` answers any session holding `read`, and the
Viewer and Auditor roles hold exactly `{read: 1}`. Permlevel is the only thing that
keeps a salted pickup digest out of that read.

What changed is where it is WRITTEN. Carrying it in the insert payload put it in
reach of `Document.validate_higher_perm_levels`, which silently resets a permlevel
field the saving user cannot write — so a site that had not run the v89 write grant
stored a transfer with no digest, and the whole apparatus that noticed (a doctype
guard, 113 lines of frappe-free tests, 318 lines of bench tests) existed to defend
the insert against itself. `_new_transfer` now writes the digest with `db_set`
immediately after the insert, below the permlevel layer.

So this file replaces all of it with the two claims that are actually left:

* the digest reaches the stored row; and
* it reaches it for a role holding NO permlevel-1 write grant — which is the
  property the change bought, and the one thing that silently regresses if anyone
  ever moves the digest back into the payload.

The second is why this is a bench test and not a frappe-free one: a fake Document
cannot show that the real `validate_higher_perm_levels` no longer has anything to
reset.

    cd ~/frappe-bench-local && bench --site <test-site> run-tests \
        --module stabler.tests.test_remittance_digest_below_permlevel_bench
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api.remittance_commands import register_remittance

TRANSFER = "Remittance Transfer"
DIGEST_FIELD = "pickup_code_hash"

#: A role that may create a transfer and holds no write grant at permlevel 1 —
#: i.e. a Cashier on a site where v89 never ran. Added, never subtracted: deleting
#: the shipped permlevel-1 rows would poison the doctype meta in a Redis cache that
#: every `bench run-tests` process shares and that no rollback reaches.
GRANTLESS_ROLE = "_Test Remittance Permlevel Gap"
GRANTLESS_EMAIL = "rem-digest-grantless@example.com"


def _ensure(doctype: str, name: str, values: dict) -> str:
	if frappe.db.exists(doctype, name):
		return name
	return (
		frappe.get_doc({"doctype": doctype, **values})
		.insert(ignore_permissions=True, ignore_if_duplicate=True)
		.name
	)


class DigestIsWrittenBelowPermlevel(FrappeTestCase):
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
		self.origin = _ensure("Branch", "REM-DIGEST-ORIGIN", {"branch": "REM-DIGEST-ORIGIN"})
		self.destination = _ensure("Branch", "REM-DIGEST-DEST", {"branch": "REM-DIGEST-DEST"})
		self._grantless_role()
		self._user(GRANTLESS_EMAIL, GRANTLESS_ROLE)
		self.addCleanup(frappe.set_user, "Administrator")

	def tearDown(self) -> None:
		frappe.db.rollback()
		frappe.clear_cache(doctype=TRANSFER)

	def _grantless_role(self) -> None:
		_ensure("Role", GRANTLESS_ROLE, {"role_name": GRANTLESS_ROLE, "desk_access": 0})
		if frappe.db.exists("DocPerm", {"parent": TRANSFER, "role": GRANTLESS_ROLE}):
			return
		# A DocPerm row and not a Custom DocPerm: one Custom DocPerm makes Frappe
		# ignore the shipped permissions entirely and would disarm the whole doctype.
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
		if frappe.db.exists("User", email):
			return
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": role,
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)

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

	def test_a_role_with_no_permlevel_grant_still_stores_the_digest(self):
		"""The property the change bought, and the one that regresses silently.

		This same call used to be refused outright, because the insert payload put
		the digest in reach of a permlevel reset. Nothing about the field's read
		protection changed — only where it is written. If anyone moves it back into
		the payload, this is what goes red.

		The command is allowed to fail LATER: genesis-test.local has no Remittance
		Settings for the test company, so `post_register` cannot book the
		obligation. That is a ledger fixture, not this file's subject; the row and
		its digest are already written by then, and both assertions still hold on a
		configured site where nothing raises at all.
		"""
		frappe.set_user(GRANTLESS_EMAIL)
		self.assertIn(GRANTLESS_ROLE, frappe.get_roles(), "the role fixture did not land")
		self.assertNotIn(
			1,
			{
				perm.permlevel
				for perm in frappe.get_meta(TRANSFER).permissions
				if perm.role in frappe.get_roles() and perm.get("write")
			},
			"this role is supposed to have no permlevel-1 write grant",
		)
		key = frappe.generate_hash(length=12)

		try:
			self._register(key)
		except frappe.ValidationError as err:
			# The ONLY failure this test tolerates is the ledger-fixture gap named in
			# the docstring; anything else means the registration itself was refused.
			# A refusal at the permission layer raises `frappe.PermissionError`, which
			# is a plain Exception in frappe (exceptions.py:40) and not a
			# `ValidationError` -- it is not caught here at all, and errors the test.
			self.assertIn(
				"Remittance Settings",
				str(err),
				f"registration failed for a reason this test does not tolerate: {err}",
			)

		stored = frappe.db.get_value(
			TRANSFER, {"client_request_id": key}, ["name", DIGEST_FIELD], as_dict=True
		)
		self.assertIsNotNone(stored, "the registration stored no transfer at all")
		self.assertTrue(
			stored.get(DIGEST_FIELD),
			"the stored transfer carries no pickup-code digest — it can never be paid out",
		)
