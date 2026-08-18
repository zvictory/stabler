"""`allowed_actions` as a REAL Cashier and a REAL Finance Manager see it.

`test_remittance_actions.py` runs bench-free and proves the table: which role
holds which action, in which state, over the full cross-product. What it cannot
prove is the only claim an operator cares about — that a Frappe user who really
holds `Remittance Cashier`, logged in, calling the endpoint, gets back a list
without **Approve refund**, **Reject refund** or **Unlock**, and without the
pickup code in any of its three column names.

A fake role list is a variable this test file sets; a real one is a row in
`tabHas Role` that `frappe.get_roles()` reads back. Those come apart when the
role name in the table has a typo, when the patch that creates the role has not
run, or when the endpoint reads the roles of the wrong user. Only this file
notices.

Two lessons from this session's reviews are encoded as fixtures rather than as
comments:

* the role fixture is ASSERTED to have landed before any action assertion runs.
  A `Remittance Cashier` who does not actually hold the role is offered nothing,
  and every "is not offered" assertion below would pass on code with no role gate
  at all.
* the queue is asserted to be NON-EMPTY before anything is asserted about its
  rows. A guard that returns zero rows satisfies every negative assertion ever
  written.

`frappe.get_list` and never `frappe.get_all` for anything that stands in for a
user's own read: `frappe/__init__.py:1365` documents `get_all` as "will **not**
check for permissions", and `limit_page_length=0` defeats the default page of 20
so a row cannot hide behind pagination and pass for the wrong reason.

Bench-only, by derivation: it is not in `.github/frappe-free-tests.txt`, so the
Makefile's BENCH_TESTS picks it up automatically.

    cd ~/frappe-bench-local && bench --site <test-site> run-tests \\
        --module stabler.tests.test_remittance_allowed_actions_bench
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from stabler.api import _remittance_actions as actions
from stabler.api.remittance_commands import payout_queue

CASHIER_EMAIL = "rem-actions-cashier@example.com"
MANAGER_EMAIL = "rem-actions-manager@example.com"
VIEWER_EMAIL = "rem-actions-viewer@example.com"

_USERS = {
	CASHIER_EMAIL: actions.CASHIER,
	MANAGER_EMAIL: actions.FINANCE_MANAGER,
	VIEWER_EMAIL: actions.VIEWER,
}


def _ensure(doctype: str, name: str, values: dict) -> str:
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	return doc.name


class RemittanceAllowedActionsBenchTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		companies = frappe.get_all("Company", pluck="name", order_by="creation asc", limit=1)
		if not companies:
			raise AssertionError("No Company on this site — the queue cannot be read.")
		cls.company = companies[0]
		cls.currency = frappe.db.get_value("Company", cls.company, "default_currency")
		# The roles come from v87_remittance_roles; ensure them so a site that has
		# not migrated fails on the offer, not on the fixture.
		for role in _USERS.values():
			_ensure("Role", role, {"role_name": role, "desk_access": 0})

	def setUp(self) -> None:
		super().setUp()
		self.origin = _ensure("Branch", "REM-ACT-ORIGIN", {"branch": "REM-ACT-ORIGIN"})
		self.destination = _ensure("Branch", "REM-ACT-DEST", {"branch": "REM-ACT-DEST"})

		self.payable = self._transfer()
		self.locked = self._transfer(verification_status="Locked")
		self.requested = self._transfer(refund_status="Requested")
		self.unposted = self._corrupted_unposted()

		for email, role in _USERS.items():
			self._user(email, role)
		self.addCleanup(frappe.set_user, "Administrator")

	# --- fixtures ----------------------------------------------------------

	def _transfer(self, **overrides) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Remittance Transfer",
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
				"operational_status": "Registered",
				"accounting_status": "Posted",
				"verification_status": "Active",
				"refund_status": "None",
				"pickup_code_hash": "s1$0123456789abcdef$deadbeef",
				"registered_at": frappe.utils.now_datetime(),
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _corrupted_unposted(self) -> str:
		"""A Registered row whose obligation was never posted — built AROUND the controller.

		`RemittanceTransfer.validate` refuses this combination outright
		(`_assert_registered_is_posted`), which is why `_transfer(accounting_status=...)`
		cannot produce it: the first defence makes the fixture unbuildable. That is the
		correct behaviour and it is exactly why the queue filter is worth testing — a
		filter is defence in depth, and defence in depth is only meaningful against the
		state the earlier defence prevents. So the row is inserted valid and then moved
		with `db.set_value`, which runs no validation, the same way a bad migration or a
		hand-edited row would produce it in the field.
		"""
		name = self._transfer()
		frappe.db.set_value(
			"Remittance Transfer", name, "accounting_status", "Unposted", update_modified=False
		)
		return name

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
		else:
			user = frappe.get_doc("User", email)
			if role not in {r.role for r in user.roles}:
				user.append("roles", {"role": role})
				user.save(ignore_permissions=True)

	def _become(self, email: str, role: str) -> None:
		frappe.set_user(email)
		self.assertIn(
			role,
			frappe.get_roles(),
			f"{email} does not actually hold {role} — every assertion below would pass "
			"vacuously, because a roleless caller is offered nothing by construction",
		)

	def _queue(self) -> dict:
		"""The queue, keyed by transfer name, asserted non-empty."""
		rows = payout_queue(self.company, limit=200)
		self.assertTrue(rows, "the payout queue came back empty — nothing below is exercised")
		return {row["name"]: row for row in rows}

	# --- the offer ---------------------------------------------------------

	def test_a_real_cashier_can_read_the_transfers_at_all(self):
		"""The premise of every assertion below, proved through the permitted call.

		`get_list`, never `get_all`; `limit_page_length=0` so the row cannot be
		hidden by the default page of 20 and read as a permission result.
		"""
		self._become(CASHIER_EMAIL, actions.CASHIER)
		visible = frappe.get_list("Remittance Transfer", pluck="name", limit_page_length=0)
		self.assertIn(self.payable, visible)

	def test_a_real_cashier_is_offered_the_payout(self):
		self._become(CASHIER_EMAIL, actions.CASHIER)
		self.assertIn(actions.PAYOUT, self._queue()[self.payable]["allowed_actions"])

	def test_a_real_cashier_is_never_offered_approve_reject_or_unlock(self):
		"""The acceptance sentence of stabler-qzr9.10, against a real role row."""
		self._become(CASHIER_EMAIL, actions.CASHIER)
		rows = self._queue()
		for name in (self.payable, self.locked, self.requested):
			offered = rows[name]["allowed_actions"]
			self.assertNotIn(actions.APPROVE_REFUND, offered, name)
			self.assertNotIn(actions.REJECT_REFUND, offered, name)
			self.assertNotIn(actions.UNLOCK_PICKUP_CODE, offered, name)

	def test_a_real_finance_manager_is_offered_them_on_the_same_rows(self):
		"""The mirror. Without it the test above passes on an empty offer."""
		self._become(MANAGER_EMAIL, actions.FINANCE_MANAGER)
		rows = self._queue()
		self.assertIn(actions.UNLOCK_PICKUP_CODE, rows[self.locked]["allowed_actions"])
		self.assertIn(actions.APPROVE_REFUND, rows[self.requested]["allowed_actions"])
		self.assertIn(actions.REJECT_REFUND, rows[self.requested]["allowed_actions"])

	def test_a_real_viewer_is_offered_nothing_on_any_row(self):
		self._become(VIEWER_EMAIL, actions.VIEWER)
		for name, row in self._queue().items():
			self.assertEqual([], row["allowed_actions"], name)

	def test_a_locked_code_withdraws_the_payout_for_everyone(self):
		for email, role in ((CASHIER_EMAIL, actions.CASHIER), (MANAGER_EMAIL, actions.FINANCE_MANAGER)):
			self._become(email, role)
			self.assertNotIn(actions.PAYOUT, self._queue()[self.locked]["allowed_actions"], email)

	def test_a_registered_unposted_transfer_never_reaches_the_queue(self):
		"""Its obligation was never posted; paying it out debits nothing that exists."""
		self._become(CASHIER_EMAIL, actions.CASHIER)
		self.assertNotIn(self.unposted, self._queue())

	# --- the code ----------------------------------------------------------

	def test_no_row_of_the_queue_carries_the_pickup_code(self):
		"""Every transfer in the fixture has a digest on file, so an absent key
		here is the guard working and not an empty column."""
		self.assertTrue(
			frappe.db.get_value("Remittance Transfer", self.payable, "pickup_code_hash"),
			"the fixture stored no digest — the assertion below proves nothing",
		)
		self._become(CASHIER_EMAIL, actions.CASHIER)
		for name, row in self._queue().items():
			for field in actions.FORBIDDEN_READ_FIELDS:
				self.assertNotIn(field, row, f"{name} handed out {field}")
