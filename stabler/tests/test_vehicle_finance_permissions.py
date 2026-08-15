"""Capability matrix, module/engine gates and DocType invariants.

Bench-free: fake frappe + fake organization/settings modules are installed via
ModuleSandbox, then the real controllers are imported against them.
"""

from __future__ import annotations

import calendar
import importlib
import sys
import types
import unittest
from datetime import date
from types import SimpleNamespace

from stabler.tests.module_sandbox import ModuleSandbox

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


# --- fakes -------------------------------------------------------------------


class _ValidationError(Exception):
	pass


class _PermissionError(Exception):
	pass


def _throw(msg, exc=None):
	raise (exc or _ValidationError)(msg)


def _flt(value, precision=None):
	result = float(value or 0)
	if precision is not None:
		result = round(result, int(precision))
	return result


def _getdate(value):
	if isinstance(value, date):
		return value
	return date.fromisoformat(str(value)[:10])


def _add_months(start, months):
	year, month = divmod(start.month - 1 + months, 12)
	year += start.year
	month += 1
	last = calendar.monthrange(year, month)[1]
	return date(year, month, min(start.day, last))


class _DB:
	def __init__(self):
		self.rows: dict[tuple[str, str], dict] = {}
		self.exists_default = True
		self.count_result = 0

	def _lookup(self, doctype, ident):
		if isinstance(ident, dict):
			for (dt, _name), fields in self.rows.items():
				if dt == doctype and all(fields.get(k) == v for k, v in ident.items()):
					return fields
			return {}
		return self.rows.get((doctype, ident), {})

	def exists(self, doctype, ident):
		if isinstance(ident, dict):
			return bool(self._lookup(doctype, ident))
		return (doctype, ident) in self.rows or self.exists_default

	def get_value(self, doctype, ident, field=None, **_kwargs):
		fields = self._lookup(doctype, ident)
		if isinstance(field, (list, tuple)):
			return SimpleNamespace(**{f: fields.get(f) for f in field})
		return fields.get(field)

	def count(self, doctype, filters=None):
		return self.count_result

	def get_default(self, key, default=None):
		return 2 if key == "currency_precision" else default


_ROLES: list[str] = []
_DOCS: dict[tuple[str, str], object] = {}
_MODULE_ACCESS = True
_MODULE_MAP: dict[str, bool] = {"installment": True}


def _can_access_module(user, key):
	return _MODULE_ACCESS


def _module_map_for(company):
	return _MODULE_MAP


def _install_fakes() -> None:
	frappe_mod = types.ModuleType("frappe")
	frappe_mod.throw = _throw
	frappe_mod.ValidationError = _ValidationError
	frappe_mod.PermissionError = _PermissionError
	frappe_mod._ = lambda s: s
	frappe_mod.get_roles = lambda user=None: list(_ROLES)
	frappe_mod.session = SimpleNamespace(user="tester@example.com")
	frappe_mod.db = _DB()
	frappe_mod.get_doc = lambda doctype, name: _DOCS[(doctype, name)]
	utils = types.ModuleType("frappe.utils")
	utils.flt = _flt
	utils.getdate = _getdate
	utils.add_months = _add_months
	utils.now = lambda: "2026-08-15 12:00:00"
	utils.nowdate = lambda: "2026-08-15"
	utils.cint = lambda v: int(v or 0)
	frappe_mod.utils = utils
	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")

	class _DocumentBase:
		def __getattr__(self, key):
			# Real Frappe documents return None for unset fields; the double
			# must not raise AttributeError where production code reads one.
			return None

		def get(self, key, default=None):
			value = getattr(self, key, None)
			return default if value is None else value

		def is_new(self):
			return not getattr(self, "creation", None)

		def has_value_changed(self, fieldname):
			return True  # Frappe returns True when there is no doc_before_save

	document.Document = _DocumentBase
	model.document = document
	frappe_mod.model = model

	organization = types.ModuleType("stabler.api.organization")
	organization._can_access_module = _can_access_module
	stabler_settings = types.ModuleType("stabler.stabler.doctype.stabler_settings.stabler_settings")
	stabler_settings.module_map_for = _module_map_for

	_SANDBOX.evict(
		"frappe",
		"frappe.utils",
		"frappe.model",
		"frappe.model.document",
		"stabler.api.organization",
		"stabler.stabler.doctype.stabler_settings.stabler_settings",
		"stabler.api.vehicle_finance.permissions",
		"stabler.stabler.doctype.vehicle_finance_settings.vehicle_finance_settings",
		"stabler.stabler.doctype.vehicle_agreement.vehicle_agreement",
		"stabler.stabler.doctype.vehicle_finance_schedule_version.vehicle_finance_schedule_version",
		"stabler.stabler.doctype.vehicle_finance_payment_application.vehicle_finance_payment_application",
		"stabler.stabler.doctype.vehicle_finance_follow_up_log.vehicle_finance_follow_up_log",
		"stabler.stabler.doctype.vehicle_unit.vehicle_unit",
	)
	_SANDBOX.install(
		{
			"frappe": frappe_mod,
			"frappe.utils": utils,
			"frappe.model": model,
			"frappe.model.document": document,
			"stabler.api.organization": organization,
			"stabler.stabler.doctype.stabler_settings.stabler_settings": stabler_settings,
		}
	)
	global FRAPPE
	FRAPPE = frappe_mod


def setUpModule():
	"""Install fakes only when the tests actually run.

	Frappe's bench test runner imports every test module up front just to
	categorise it; an import-time install would poison that process's
	sys.modules with the fakes (tearDownModule never runs there)."""
	global permissions, settings_mod, agreement_mod, version_mod
	global application_mod, follow_up_mod, unit_mod
	_install_fakes()
	permissions = importlib.import_module("stabler.api.vehicle_finance.permissions")
	settings_mod = importlib.import_module(
		"stabler.stabler.doctype.vehicle_finance_settings.vehicle_finance_settings"
	)
	agreement_mod = importlib.import_module("stabler.stabler.doctype.vehicle_agreement.vehicle_agreement")
	version_mod = importlib.import_module(
		"stabler.stabler.doctype.vehicle_finance_schedule_version.vehicle_finance_schedule_version"
	)
	application_mod = importlib.import_module(
		"stabler.stabler.doctype.vehicle_finance_payment_application.vehicle_finance_payment_application"
	)
	follow_up_mod = importlib.import_module(
		"stabler.stabler.doctype.vehicle_finance_follow_up_log.vehicle_finance_follow_up_log"
	)
	unit_mod = importlib.import_module("stabler.stabler.doctype.vehicle_unit.vehicle_unit")


class _FakeDoc(dict):
	def __getattr__(self, key):
		try:
			return self[key]
		except KeyError as exc:
			raise AttributeError(key) from exc

	def __setattr__(self, key, value):
		self[key] = value

	def is_new(self):
		return not self.get("creation")

	def has_value_changed(self, fieldname):
		return True  # Frappe returns True when there is no doc_before_save

	def as_dict(self):
		return dict(self)


def _instance(cls, **fields):
	doc = cls.__new__(cls)
	doc.__dict__.update(fields)
	doc.flags = SimpleNamespace()
	doc.meta = SimpleNamespace(get_label=lambda fieldname: fieldname)
	return doc


ALL_ROLES = {
	"Vehicle Finance Viewer",
	"Vehicle Finance Contract Clerk",
	"Vehicle Finance Collector",
	"Vehicle Finance Payables Clerk",
	"Vehicle Finance Reviewer",
	"Vehicle Finance Cashier",
	"Vehicle Finance Manager",
}

EXPECTED_MATRIX = {
	"view": ALL_ROLES,
	"view_cost_margin": {"Vehicle Finance Manager", "Vehicle Finance Reviewer"},
	"draft_write": {"Vehicle Finance Contract Clerk", "Vehicle Finance Manager"},
	"approve": {"Vehicle Finance Reviewer", "Vehicle Finance Manager"},
	"activate": {"Vehicle Finance Reviewer", "Vehicle Finance Manager"},
	"collect": {"Vehicle Finance Cashier", "Vehicle Finance Collector", "Vehicle Finance Manager"},
	"pay_supplier": {"Vehicle Finance Payables Clerk", "Vehicle Finance Manager"},
	"fifo_override": {"Vehicle Finance Manager"},
	"cancel_same_day": {"Vehicle Finance Manager"},
	"reschedule": {"Vehicle Finance Manager"},
	"title_override": {"Vehicle Finance Manager"},
	"settlement_writeoff": {"Vehicle Finance Manager"},
}


class TestCapabilityMatrix(unittest.TestCase):
	def test_matrix_matches_the_frozen_contract(self):
		self.assertEqual(
			set(permissions.CAPABILITY_ROLES),
			set(EXPECTED_MATRIX),
		)
		for capability, roles in EXPECTED_MATRIX.items():
			self.assertEqual(
				set(permissions.CAPABILITY_ROLES[capability]),
				roles,
				f"capability {capability} has the wrong role set",
			)

	def test_every_capability_allows_exactly_the_matrix_roles(self):
		for capability, roles in EXPECTED_MATRIX.items():
			for role in roles:
				with self.subTest(capability=capability, role=role):
					_ROLES.clear()
					_ROLES.append(role)
					permissions._assert_capability(role, "ACME", capability)
			for role in sorted(ALL_ROLES - roles):
				with self.subTest(capability=capability, denied=role):
					_ROLES.clear()
					_ROLES.append(role)
					with self.assertRaises(_PermissionError):
						permissions._assert_capability(role, "ACME", capability)

	def test_admins_pass_every_capability(self):
		for admin in ("System Manager", "Stabler Admin"):
			for capability in EXPECTED_MATRIX:
				with self.subTest(admin=admin, capability=capability):
					_ROLES.clear()
					_ROLES.append(admin)
					permissions._assert_capability(admin, "ACME", capability)

	def test_unknown_capability_rejected(self):
		_ROLES.clear()
		_ROLES.append("System Manager")
		with self.assertRaises(_PermissionError):
			permissions._assert_capability("x", "ACME", "not_a_capability")


class TestModuleAndEngineGates(unittest.TestCase):
	def setUp(self):
		_ROLES.clear()
		_ROLES.append("Vehicle Finance Manager")
		global _MODULE_ACCESS, _MODULE_MAP
		_MODULE_ACCESS = True
		_MODULE_MAP = {"installment": True}
		FRAPPE.db.rows.clear()

	def test_module_role_gate_denies_without_access(self):
		global _MODULE_ACCESS
		_MODULE_ACCESS = False
		with self.assertRaises(_PermissionError):
			permissions._require_vehicle_finance_module("ACME")

	def test_module_company_flag_denies_when_disabled(self):
		global _MODULE_MAP
		_MODULE_MAP = {"installment": False}
		with self.assertRaises(_PermissionError):
			permissions._require_vehicle_finance_module("ACME")

	def test_module_enabled_passes(self):
		permissions._require_vehicle_finance_module("ACME")

	def test_engine_defaults_to_legacy_when_no_settings_row(self):
		with self.assertRaises(_ValidationError) as ctx:
			permissions._require_agreement_v1("ACME")
		self.assertIn("Agreement V1 is not enabled", str(ctx.exception))

	def test_legacy_engine_clear_error_not_permission_error(self):
		FRAPPE.db.rows[("Vehicle Finance Settings", "VF-ACME")] = {
			"company": "ACME",
			"installment_engine": "Legacy",
		}
		with self.assertRaises(_ValidationError) as ctx:
			permissions._require_agreement_v1("ACME")
		self.assertIn("Agreement V1 is not enabled", str(ctx.exception))

	def test_agreement_v1_engine_passes(self):
		FRAPPE.db.rows[("Vehicle Finance Settings", "VF-ACME")] = {
			"company": "ACME",
			"installment_engine": "Agreement V1",
		}
		permissions._require_agreement_v1("ACME")

	def test_get_engine_real_module_defaults_to_legacy(self):
		self.assertEqual(settings_mod.get_engine("ACME"), "Legacy")


class TestAgreementInvariants(unittest.TestCase):
	def setUp(self):
		FRAPPE.db.rows.clear()
		FRAPPE.db.count_result = 0
		FRAPPE.db.rows[("Customer", "Cust A")] = {"customer_name": "Customer A"}
		FRAPPE.db.rows[("Supplier", "Supp A")] = {"supplier_name": "Supplier A"}

	def _agreement(self, **overrides):
		fields = dict(
			company="ACME",
			direction="Disposition",
			party="Cust A",
			currency="USD",
			cash_price=800,
			disclosed_markup=150,
			approved_fees=30,
			tax_amount=20,
			down_payment=100,
			vehicle_unit="VEH-00001",
			name="VFA-2026-00001",
		)
		fields.update(overrides)
		return _instance(agreement_mod.VehicleAgreement, **fields)

	def test_components_total_and_party_derived(self):
		doc = self._agreement()
		doc.validate()
		self.assertEqual(doc.party_type, "Customer")
		self.assertEqual(doc.total_contract_price, 1000.0)
		self.assertEqual(doc.financed_amount, 900.0)
		self.assertEqual(doc.party_name, "Customer A")

	def test_down_payment_above_total_throws(self):
		doc = self._agreement(down_payment=1001)
		with self.assertRaises(_ValidationError):
			doc.validate()

	def test_one_direction_per_vehicle_on_submit(self):
		doc = self._agreement()
		doc.on_submit()
		FRAPPE.db.count_result = 1
		with self.assertRaises(_ValidationError):
			doc.on_submit()

	def test_acquisition_direction_maps_to_supplier(self):
		doc = self._agreement(direction="Acquisition", party="Supp A")
		doc.validate()
		self.assertEqual(doc.party_type, "Supplier")


class TestScheduleVersionInvariants(unittest.TestCase):
	def setUp(self):
		FRAPPE.db.rows.clear()
		FRAPPE.db.count_result = 0
		FRAPPE.db.rows[("Currency", "USD")] = {"fraction": 2}
		_DOCS.clear()
		_DOCS[("Vehicle Agreement", "VFA-2026-00001")] = _FakeDoc(
			company="ACME",
			currency="USD",
			total_contract_price=1000.0,
			settlement_mode="Installment",
		)

	def _rows(self):
		return [
			_FakeDoc(sequence=0, due_date="2026-01-15", amount=100.0, row_type="Down Payment"),
			_FakeDoc(sequence=1, due_date="2026-02-15", amount=450.0, row_type="Installment"),
			_FakeDoc(sequence=2, due_date="2026-03-15", amount=450.0, row_type="Installment"),
		]

	def _version(self, **overrides):
		fields = dict(
			agreement="VFA-2026-00001",
			version_number=1,
			status="Draft",
			plan_type="Equal Monthly",
			effective_date="2026-01-15",
			rows=self._rows(),
			name="VFS-2026-00001",
		)
		fields.update(overrides)
		return _instance(version_mod.VehicleFinanceScheduleVersion, **fields)

	def test_balanced_rows_set_total_and_company(self):
		doc = self._version()
		doc.validate()
		self.assertEqual(doc.total_amount, 1000.0)
		self.assertEqual(doc.company, "ACME")
		self.assertEqual(doc.currency, "USD")

	def test_row_sum_mismatch_states_both_numbers(self):
		rows = self._rows()
		rows[2]["amount"] = 400.0
		doc = self._version(rows=rows)
		with self.assertRaises(_ValidationError) as ctx:
			doc.validate()
		self.assertIn("950", str(ctx.exception))
		self.assertIn("1000", str(ctx.exception))

	def test_cash_agreement_single_row_only(self):
		_DOCS[("Vehicle Agreement", "VFA-2026-00001")]["settlement_mode"] = "Cash"
		doc = self._version()
		with self.assertRaises(_ValidationError):
			doc.validate()

	def test_reschedule_reason_mandatory_from_version_2(self):
		doc = self._version(version_number=2)
		with self.assertRaises(_ValidationError):
			doc.validate()
		doc2 = self._version(version_number=2, reschedule_reason="Customer hardship")
		doc2.validate()

	def test_only_one_active_version_per_agreement(self):
		doc = self._version(status="Active")
		doc.validate()
		FRAPPE.db.count_result = 1
		with self.assertRaises(_ValidationError):
			self._version(status="Active").validate()


class TestPaymentApplicationInvariants(unittest.TestCase):
	def setUp(self):
		FRAPPE.db.rows.clear()
		FRAPPE.db.rows[("Vehicle Agreement", "VFA-2026-00001")] = {"company": "ACME"}
		FRAPPE.db.rows[("Payment Entry", "PE-00001")] = {}
		FRAPPE.db.rows[("Vehicle Finance Payment Application", "VFP-00001")] = {
			"agreement": "VFA-2026-00001",
			"is_reversal": 0,
		}

	def _application(self, **overrides):
		fields = dict(
			company="ACME",
			agreement="VFA-2026-00001",
			schedule_version="VFS-2026-00001",
			schedule_row="row-abc",
			row_sequence=1,
			payment_entry="PE-00001",
			allocated_amount=100.0,
			currency="USD",
			is_reversal=0,
			is_fifo_override=0,
		)
		fields.update(overrides)
		return _instance(application_mod.VehicleFinancePaymentApplication, **fields)

	def test_valid_application_passes_and_stamps_user(self):
		doc = self._application()
		doc.validate()
		self.assertEqual(doc.applied_by, "tester@example.com")

	def test_fifo_override_requires_reason(self):
		doc = self._application(is_fifo_override=1)
		with self.assertRaises(_ValidationError):
			doc.validate()
		self._application(is_fifo_override=1, override_reason="Customer instruction").validate()

	def test_company_must_match_agreement(self):
		doc = self._application(company="OTHER")
		with self.assertRaises(_ValidationError):
			doc.validate()

	def test_reversal_rules(self):
		self._application(is_reversal=1, reverses="VFP-00001", allocated_amount=-100.0).validate()
		with self.assertRaises(_ValidationError):
			# positive reversal
			self._application(is_reversal=1, reverses="VFP-00001", allocated_amount=100.0).validate()
		FRAPPE.db.rows[("Vehicle Finance Payment Application", "VFP-00001")]["is_reversal"] = 1
		with self.assertRaises(_ValidationError):
			# a reversal cannot reverse another reversal
			self._application(is_reversal=1, reverses="VFP-00001", allocated_amount=-100.0).validate()

	def test_cancel_is_forbidden(self):
		doc = self._application()
		with self.assertRaises(_ValidationError):
			doc.on_cancel()

	def test_trash_is_forbidden(self):
		doc = self._application()
		with self.assertRaises(_ValidationError):
			doc.on_trash()


class TestFollowUpLogAppendOnly(unittest.TestCase):
	def _log(self, **overrides):
		fields = dict(
			company="ACME", agreement="VFA-2026-00001", contact_type="Call", contact_result="Promise"
		)
		fields.update(overrides)
		return _instance(follow_up_mod.VehicleFinanceFollowUpLog, **fields)

	def test_new_entry_passes_and_stamps_user(self):
		doc = self._log()
		doc.validate()
		self.assertEqual(doc.logged_by, "tester@example.com")

	def test_editing_existing_entry_throws(self):
		doc = self._log(creation="2026-08-01 10:00:00")
		with self.assertRaises(_ValidationError):
			doc.validate()

	def test_trash_is_forbidden(self):
		doc = self._log()
		with self.assertRaises(_ValidationError):
			doc.on_trash()


class TestSettings(unittest.TestCase):
	def _settings(self, **overrides):
		fields = dict(
			company="ACME",
			installment_engine="Legacy",
			accounting_policy_approved=0,
		)
		fields.update(overrides)
		return _instance(settings_mod.VehicleFinanceSettings, **fields)

	def test_legacy_default_is_valid(self):
		self._settings().validate()

	def test_v1_engine_requires_policy_approval(self):
		with self.assertRaises(_ValidationError):
			self._settings(installment_engine="Agreement V1").validate()
		self._settings(
			installment_engine="Agreement V1",
			accounting_policy_approved=1,
		).validate()

	def test_policy_approval_stamps_user_and_time(self):
		doc = self._settings(accounting_policy_approved=1)
		doc.validate()
		self.assertEqual(doc.accounting_policy_approved_by, "tester@example.com")
		self.assertTrue(doc.accounting_policy_approved_on)


class TestVehicleUnitGuards(unittest.TestCase):
	def setUp(self):
		FRAPPE.db.rows.clear()
		FRAPPE.db.rows[("Serial No", "VIN-001")] = {"company": "ACME"}

	def _unit(self, **overrides):
		fields = dict(company="ACME", serial_no="VIN-001", name="VEH-00001")
		fields.update(overrides)
		return _instance(unit_mod.VehicleUnit, **fields)

	def test_matching_serial_passes(self):
		self._unit().validate()

	def test_unknown_serial_throws(self):
		FRAPPE.db.exists_default = False
		try:
			with self.assertRaises(_ValidationError):
				self._unit(serial_no="VIN-XXX").validate()
		finally:
			FRAPPE.db.exists_default = True

	def test_foreign_company_serial_throws(self):
		FRAPPE.db.rows[("Serial No", "VIN-002")] = {"company": "OTHER"}
		with self.assertRaises(_ValidationError):
			self._unit(serial_no="VIN-002").validate()

	def test_agreement_links_locked_without_internal_flag(self):
		with self.assertRaises(_ValidationError):
			self._unit(acquisition_agreement="VFA-2026-00001").validate()
		unit = self._unit(acquisition_agreement="VFA-2026-00001")
		unit.flags.vf_internal = True
		unit.validate()


if __name__ == "__main__":
	unittest.main()
