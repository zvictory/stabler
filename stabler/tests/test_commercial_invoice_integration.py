"""Integration tests for the Commercial Invoice module-gating no-op behavior.

These need a real site + database, so they run under `bench run-tests --app
stabler --module stabler.tests.test_commercial_invoice_integration` (and in
CI), not under plain `python -m unittest`. They exercise the guard in
stabler/stabler/doctype/commercial_invoice/commercial_invoice.py: it must
silently no-op (never frappe.throw) when the `imports` module is disabled for
the company, or when frappe.flags.in_msaerp_migration is set — and it must
enforce the status pipeline otherwise.

If the test fixtures (a Company, a Supplier) are not present the relevant
tests skip rather than fail, so the suite stays green on a bare site.
"""

from __future__ import annotations

import unittest

import frappe

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase


def _first_company():
	return frappe.db.get_value("Company", {}, "name")


def _first_supplier():
	return frappe.db.get_value("Supplier", {}, "name")


class CommercialInvoiceModuleGateIntegrationTest(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company = _first_company()
		cls.supplier = _first_supplier()

	def setUp(self):
		if not (self.company and self.supplier):
			self.skipTest("no Company / Supplier fixtures available")
		if not frappe.db.exists("DocType", "Stabler Settings"):
			self.skipTest("Stabler Settings doctype not present")

	def tearDown(self):
		frappe.flags.in_msaerp_migration = False
		frappe.db.rollback()

	def _set_imports_enabled(self, enabled: bool) -> None:
		settings = frappe.get_single("Stabler Settings")
		row = None
		for r in settings.company_modules or []:
			if r.company == self.company:
				row = r
				break
		if row is None:
			row = settings.append("company_modules", {"company": self.company})
		row.enable_imports = 1 if enabled else 0
		settings.save(ignore_permissions=True)

	def _new_ci(self):
		ci = frappe.new_doc("Commercial Invoice")
		ci.company = self.company
		ci.supplier = self.supplier
		ci.ci_number = frappe.generate_hash(length=8)
		ci.ci_date = frappe.utils.today()
		ci.insert(ignore_permissions=True)
		return ci

	def test_invalid_transition_blocked_when_imports_enabled(self):
		self._set_imports_enabled(True)
		ci = self._new_ci()
		self.assertEqual(ci.status, "Draft")
		ci.status = "Declaration Filed"  # skips Pending Documents / Submitted to Broker
		with self.assertRaises(frappe.ValidationError):
			ci.save(ignore_permissions=True)

	def test_valid_transition_allowed_when_imports_enabled(self):
		self._set_imports_enabled(True)
		ci = self._new_ci()
		ci.status = "Pending Documents"
		ci.save(ignore_permissions=True)  # should not raise
		ci.reload()
		self.assertEqual(ci.status, "Pending Documents")

	def test_invalid_transition_is_noop_when_imports_disabled(self):
		self._set_imports_enabled(False)
		ci = self._new_ci()
		ci.status = "Declaration Filed"  # would be invalid if imports were on
		ci.save(ignore_permissions=True)  # must not raise: module is off
		ci.reload()
		self.assertEqual(ci.status, "Declaration Filed")

	def test_invalid_transition_is_noop_during_msaerp_migration(self):
		self._set_imports_enabled(True)
		ci = self._new_ci()
		frappe.flags.in_msaerp_migration = True
		ci.status = "Declaration Filed"  # would be invalid outside migration
		ci.save(ignore_permissions=True)  # must not raise: migration bypass
		ci.reload()
		self.assertEqual(ci.status, "Declaration Filed")


if __name__ == "__main__":
	unittest.main()
