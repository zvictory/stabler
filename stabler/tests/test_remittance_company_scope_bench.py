"""Company isolation for remittance, proved on a real site instead of a fragment.

`test_remittance_company_scope.py` runs bench-free and proves three things: the
two doctypes are registered in both record-level maps in `hooks.py`, every
registered path resolves to a function that exists, and the emitted WHERE
fragments select the right rows when executed against SQLite. What it cannot
prove is the only claim that matters to a Remittance Viewer: that Frappe
actually splices those fragments into the query behind `/api/resource` and the
other company's rows never come back. A fragment can be perfect and still never
be called — that is precisely the state this bead found, with the fragments
missing entirely.

So this file makes the call the way a restricted user does: it becomes a real
non-admin user holding Remittance Viewer with an Allowed Companies list of one,
and reads the list. Two companies, one transfer and one event each.

`Remittance Event` is the interesting half: it has no `company` column, so its
scope is a subquery through the parent transfer. A join that is right in SQLite
and wrong in MariaDB fails only here.

Bench-only, by derivation: it is not in `.github/frappe-free-tests.txt`, so the
Makefile's BENCH_TESTS picks it up automatically.

    cd ~/frappe-bench-local && bench --site <test-site> run-tests \\
        --module stabler.tests.test_remittance_company_scope_bench
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

VIEWER_EMAIL = "rem-scope-viewer@example.com"
VIEWER_ROLE = "Remittance Viewer"
SECOND_COMPANY = "REM Scope Test Co"


def _ensure(doctype: str, name: str, values: dict) -> str:
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
	return doc.name


class RemittanceCompanyScopeBenchTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		companies = frappe.get_all("Company", pluck="name", order_by="creation asc", limit=2)
		if not companies:
			raise AssertionError("No Company on this site — company isolation cannot be tested.")
		cls.company_a = companies[0]
		if len(companies) > 1:
			cls.company_b = companies[1]
		else:
			# One-company site: make the second one. Creating a Company builds a
			# chart of accounts, which is slow but is the only way to have two
			# real Link targets for the Allowed Companies rows.
			cls.company_b = _ensure(
				"Company",
				SECOND_COMPANY,
				{
					"company_name": SECOND_COMPANY,
					"abbr": "RSTC",
					"default_currency": frappe.db.get_value("Company", cls.company_a, "default_currency"),
					"country": frappe.db.get_value("Company", cls.company_a, "country") or "Uzbekistan",
				},
			)
		# The role comes from v87_remittance_roles; ensure it so a site that has
		# not migrated fails on the isolation claim rather than on setup.
		_ensure("Role", VIEWER_ROLE, {"role_name": VIEWER_ROLE, "desk_access": 1})

	def setUp(self) -> None:
		super().setUp()
		self.origin = _ensure("Branch", "REM-SCOPE-ORIGIN", {"branch": "REM-SCOPE-ORIGIN"})
		self.destination = _ensure("Branch", "REM-SCOPE-DEST", {"branch": "REM-SCOPE-DEST"})

		self.transfer_a = self._transfer(self.company_a)
		self.transfer_b = self._transfer(self.company_b)
		self.event_a = self._event(self.transfer_a)
		self.event_b = self._event(self.transfer_b)

		self._viewer_restricted_to(self.company_a)
		self.addCleanup(frappe.set_user, "Administrator")

	# --- fixtures ----------------------------------------------------------

	def _transfer(self, company: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Remittance Transfer",
				"company": company,
				"sender_name": f"Sender {company}",
				"receiver_name": f"Receiver {company}",
				"origin_branch": self.origin,
				"destination_branch": self.destination,
				"send_currency": frappe.db.get_value("Company", company, "default_currency"),
				"receive_currency": frappe.db.get_value("Company", company, "default_currency"),
				"commission_mode": "Inclusive",
				"commission_pct": 1,
				"principal": 990.10,
				"commission": 9.90,
				"tendered": 1000.00,
				"receiver_amount": 990.10,
				"exchange_rate": 1,
				"operational_status": "Draft",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _event(self, transfer: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Remittance Event",
				"transfer": transfer,
				"event_type": "Register",
				"occurred_at": now_datetime(),
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _viewer_restricted_to(self, company: str) -> None:
		"""A real non-admin Viewer whose Allowed Companies list holds one company.

		The rows are written straight into `Stabler User Company` rather than
		through the User form: that child table is what
		`organization._user_allowed_companies` queries, and going direct keeps the
		fixture working on a site where the Custom Field on User is absent.
		"""
		if not frappe.db.exists("User", VIEWER_EMAIL):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": VIEWER_EMAIL,
					"first_name": "Remittance Scope Viewer",
					"send_welcome_email": 0,
					"roles": [{"role": VIEWER_ROLE}],
				}
			)
			user.insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", VIEWER_EMAIL)
			if VIEWER_ROLE not in {r.role for r in user.roles}:
				user.append("roles", {"role": VIEWER_ROLE})
				user.save(ignore_permissions=True)

		frappe.db.delete(
			"Stabler User Company",
			{"parent": VIEWER_EMAIL, "parenttype": "User", "parentfield": "allowed_companies"},
		)
		frappe.get_doc(
			{
				"doctype": "Stabler User Company",
				"parent": VIEWER_EMAIL,
				"parenttype": "User",
				"parentfield": "allowed_companies",
				"company": company,
			}
		).insert(ignore_permissions=True)

		self.assertEqual(
			frappe.get_all(
				"Stabler User Company",
				filters={"parent": VIEWER_EMAIL, "parentfield": "allowed_companies"},
				pluck="company",
			),
			[company],
			"the Allowed Companies fixture did not land — every assertion below would "
			"pass vacuously, because an empty list means unrestricted",
		)

	# --- the isolation -----------------------------------------------------

	def test_the_viewer_lists_only_its_own_company_transfers(self):
		frappe.set_user(VIEWER_EMAIL)
		# `get_list`, never `get_all`. frappe/__init__.py:1365 says get_all "will
		# **not** check for permissions" — it sets ignore_permissions, so
		# `permission_query_conditions` is never spliced in and this assertion would
		# fail against correct scoping. `/api/resource` reaches the list through
		# `frappe.client.get_list`, so get_list is also the call the attacker makes.
		# limit_page_length=0 defeats the default page of 20, which would otherwise
		# hide the other company's row behind pagination rather than behind the guard.
		visible = frappe.get_list("Remittance Transfer", pluck="name", limit_page_length=0)
		self.assertIn(self.transfer_a, visible)
		self.assertNotIn(
			self.transfer_b,
			visible,
			"a Viewer restricted to one company read another company's transfer — "
			"sender and receiver names, amounts, corridor and the Journal Entry links",
		)

	def test_the_viewer_lists_only_its_own_company_events(self):
		frappe.set_user(VIEWER_EMAIL)
		# `get_list`, never `get_all`. frappe/__init__.py:1365 says get_all "will
		# **not** check for permissions" — it sets ignore_permissions, so
		# `permission_query_conditions` is never spliced in and this assertion would
		# fail against correct scoping. `/api/resource` reaches the list through
		# `frappe.client.get_list`, so get_list is also the call the attacker makes.
		# limit_page_length=0 defeats the default page of 20, which would otherwise
		# hide the other company's row behind pagination rather than behind the guard.
		visible = frappe.get_list("Remittance Event", pluck="name", limit_page_length=0)
		self.assertIn(self.event_a, visible)
		self.assertNotIn(
			self.event_b,
			visible,
			"the event trail leaked the other company's transfer; the parent-join "
			"condition is the only thing scoping this doctype",
		)

	def test_the_viewer_cannot_read_the_other_company_transfer_directly(self):
		frappe.set_user(VIEWER_EMAIL)
		self.assertFalse(
			frappe.has_permission(
				"Remittance Transfer", "read", doc=frappe.get_doc("Remittance Transfer", self.transfer_b)
			)
		)
		self.assertTrue(
			frappe.has_permission(
				"Remittance Transfer", "read", doc=frappe.get_doc("Remittance Transfer", self.transfer_a)
			)
		)

	def test_the_viewer_cannot_read_the_other_company_event_directly(self):
		frappe.set_user(VIEWER_EMAIL)
		self.assertFalse(
			frappe.has_permission(
				"Remittance Event", "read", doc=frappe.get_doc("Remittance Event", self.event_b)
			)
		)
		self.assertTrue(
			frappe.has_permission(
				"Remittance Event", "read", doc=frappe.get_doc("Remittance Event", self.event_a)
			)
		)

	def test_an_administrator_still_sees_both_companies(self):
		# Isolation that also hides rows from admins would break every back-office
		# screen; the exemption is deliberate and is asserted, not assumed.
		transfers = frappe.get_all("Remittance Transfer", pluck="name")
		self.assertIn(self.transfer_a, transfers)
		self.assertIn(self.transfer_b, transfers)
		events = frappe.get_all("Remittance Event", pluck="name")
		self.assertIn(self.event_a, events)
		self.assertIn(self.event_b, events)


if __name__ == "__main__":
	import unittest

	unittest.main()
