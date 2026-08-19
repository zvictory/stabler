"""The Payment Plan Entry contract — what a plan row is, and what it must never do.

The payment calendar exists so that each user records what they *intend* to pay
or collect, and an authorised reader sees the totals. Three decisions from Zafar
(2026-08-19) shape the schema, and each of them is the kind of thing that quietly
erodes unless a test holds it:

1. **Authority is a role, not a name check.** Reading across everyone's plans is
   ``Payment Plan Manager``; owning your own rows is ``Payment Plan User``. The
   roles must actually be created by a patch — a DocPerm naming a Role that no
   patch inserts resolves to nobody, which is exactly the defect
   ``v87_remittance_roles`` was written to repair. So the JSON and the patch are
   asserted against each other, never against a hand-copied list.

2. **A plan row points at the document it intends to settle.** The link is a
   pair of fields, and the doctype it may point at is a closed set — an
   unconstrained Dynamic Link lets a plan row claim to settle a User or a File.

3. **No automatic Payment Entry, ever.** A plan is a forecast. Money leaves
   through Payments / Kassa / Journal, and a row is closed by hand. The moment
   this module posts anything, every forecast becomes a ledger write and the
   feature turns into an accounting liability. Asserted as an absence, because
   absences are what regress silently.

Beyond those, two derived fields carry invariants the calendar depends on:
``direction`` (every total splits in from out) and ``base_amount`` (a month's
total is one GROUP BY, not N conversions). Both are read-only and both must be
computed on validate, or a UI that forgets to send them writes zeros into the
totals a director reads.

Bench-free on purpose: ``make check`` does not run the bench set, so a test that
needed a bench would not gate a push.
"""

from __future__ import annotations

import ast
import json
import types
import unittest
from pathlib import Path

from stabler.tests.module_sandbox import ModuleSandbox

_ROOT = Path(__file__).resolve().parent.parent
_DIR = _ROOT / "stabler" / "doctype" / "payment_plan_entry"
DOCTYPE_JSON = _DIR / "payment_plan_entry.json"
CONTROLLER = _DIR / "payment_plan_entry.py"
PATCH = _ROOT / "patches" / "v95_payment_plan_roles.py"
PATCHES_TXT = _ROOT / "patches.txt"
MODULES_JSON = _ROOT / "stabler" / "doctype" / "stabler_company_modules" / "stabler_company_modules.json"

PATCH_MODULE = "stabler.patches.v95_payment_plan_roles"

# The contract, duplicated on purpose: the patch is checked against this, so
# widening the module's authority set has to be a deliberate edit in two places.
PLANNED_ROLES = {"Payment Plan User", "Payment Plan Manager"}

# A plan row may only claim to settle a commercial document. Kept here rather
# than read off the controller so that loosening it is visible in a diff.
ALLOWED_REFERENCE_DOCTYPES = {
	"Sales Invoice",
	"Sales Order",
	"Purchase Invoice",
	"Purchase Order",
	"Proforma Invoice",
}

_SANDBOX = ModuleSandbox()


def tearDownModule():
	_SANDBOX.restore()


def _doctype() -> dict:
	return json.loads(DOCTYPE_JSON.read_text(encoding="utf-8"))


def _fields() -> dict:
	return {f["fieldname"]: f for f in _doctype()["fields"]}


class _Document:
	def __init__(self, **values):
		self.__dict__.update(values)

	def get(self, key, default=None):
		return self.__dict__.get(key, default)


def _load_controller():
	"""Import the controller against a fake ``frappe`` so no bench is needed."""
	_SANDBOX.evict(
		"stabler.stabler.doctype.payment_plan_entry.payment_plan_entry",
		"frappe",
		"frappe.model",
		"frappe.model.document",
		"frappe.utils",
	)

	thrown: list[str] = []

	def _throw(message, *args, **kwargs):
		thrown.append(str(message))
		raise ValueError(str(message))

	frappe = types.ModuleType("frappe")
	frappe._ = lambda value: value
	frappe.throw = _throw
	frappe.db = types.SimpleNamespace(get_value=lambda *a, **k: None)
	frappe.session = types.SimpleNamespace(user="tester@example.com")

	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")
	document.Document = _Document
	model.document = document
	frappe.model = model

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda value, precision=None: (
		0.0
		if value in (None, "")
		else (round(float(value), precision) if precision is not None else float(value))
	)
	utils.getdate = lambda value=None: value
	frappe.utils = utils

	_SANDBOX.install(
		{
			"frappe": frappe,
			"frappe.model": model,
			"frappe.model.document": document,
			"frappe.utils": utils,
		}
	)

	import importlib

	module = importlib.import_module("stabler.stabler.doctype.payment_plan_entry.payment_plan_entry")
	return module, thrown


class PaymentPlanEntryRolesTest(unittest.TestCase):
	def test_every_role_the_doctype_names_is_created_by_the_patch(self):
		"""A DocPerm naming a Role nothing inserts grants the right to nobody.

		This is the v87 defect exactly: remittance shipped doctypes whose
		permission rows named roles no patch created, so the whole module was
		System-Manager-only in practice while reading as multi-role in the JSON.
		"""
		named = {p["role"] for p in _doctype()["permissions"]}
		created = set(_patch_roles())
		# System Manager is a Frappe core role; everything else is ours to create.
		self.assertEqual(named - {"System Manager"}, created)

	def test_the_patch_creates_exactly_the_planned_roles(self):
		self.assertEqual(set(_patch_roles()), PLANNED_ROLES)

	def test_a_role_the_model_sync_already_created_is_still_made_desk_less(self):
		"""Insert-if-missing never reaches its own ``desk_access = 0``.

		Measured on genesis-test.local, 2026-08-19: ``Payment Plan Manager`` was
		created at 20:26:23.753 and this patch's Patch Log row is stamped
		20:26:24.033. Frappe's model sync creates any Role a doctype's
		``permissions`` rows name, and every patch from v81 on runs under
		``[post_model_sync]`` — so the sync wins the race every time and the
		patch takes the skip branch. Every role v84 and v87 "created" reads
		``desk_access = 1`` on a migrated site for exactly this reason.

		The role here is the one the sync made: it exists, and it has Desk
		access. The patch must correct it rather than skip it.
		"""
		module, state = _load_patch(existing={"Payment Plan User": 1, "Payment Plan Manager": 1})
		module.execute()
		self.assertEqual(state["saved"], {"Payment Plan User": 0, "Payment Plan Manager": 0})
		self.assertEqual(state["inserted"], [], "the roles already existed; nothing should be inserted")

	def test_a_role_that_is_already_desk_less_is_left_alone(self):
		"""A replayed migrate is normal. Re-saving an unchanged Role would
		re-evaluate the user type of everyone holding it for no reason."""
		module, state = _load_patch(existing={"Payment Plan User": 0, "Payment Plan Manager": 0})
		module.execute()
		self.assertEqual(state["saved"], {})
		self.assertEqual(state["inserted"], [])

	def test_a_missing_role_is_created_without_desk_access(self):
		module, state = _load_patch(existing={})
		module.execute()
		self.assertEqual(sorted(state["inserted"]), sorted(PLANNED_ROLES))
		self.assertEqual(state["insert_desk_access"], {r: 0 for r in PLANNED_ROLES})

	def test_the_patch_is_registered(self):
		registered = [
			line.strip() for line in PATCHES_TXT.read_text(encoding="utf-8").splitlines() if line.strip()
		]
		self.assertIn(PATCH_MODULE, registered)

	def test_the_patch_is_idempotent(self):
		"""Re-running a patch is normal (every migrate replays unapplied ones,
		and a failed migrate replays applied ones); inserting a duplicate Role
		would abort the migrate for every tenant."""
		source = PATCH.read_text(encoding="utf-8")
		self.assertIn('frappe.db.exists("Role"', source)


def _load_patch(existing: dict):
	"""Import the patch against a fake ``frappe`` whose Role table is ``existing``."""
	_SANDBOX.evict(PATCH_MODULE, "frappe")
	state = {"inserted": [], "insert_desk_access": {}, "saved": {}}

	class _Role:
		def __init__(self, name=None):
			self.name = name
			self.role_name = name
			self.desk_access = 1

		def insert(self, **kwargs):
			state["inserted"].append(self.role_name)
			state["insert_desk_access"][self.role_name] = self.desk_access

		def save(self, **kwargs):
			state["saved"][self.name] = self.desk_access

	frappe = types.ModuleType("frappe")
	frappe.new_doc = lambda _doctype: _Role()
	frappe.get_doc = lambda _doctype, name: _Role(name)
	frappe.db = types.SimpleNamespace(
		exists=lambda _doctype, name: name in existing,
		get_value=lambda _doctype, name, field: existing.get(name),
	)
	_SANDBOX.install({"frappe": frappe})

	import importlib

	return importlib.import_module(PATCH_MODULE), state


def _patch_roles() -> tuple[str, ...]:
	"""Read the role names out of the patch's own module-level tuple."""
	tree = ast.parse(PATCH.read_text(encoding="utf-8"))
	for node in tree.body:
		if isinstance(node, ast.Assign) and any(
			isinstance(t, ast.Name) and t.id == "_ROLES" for t in node.targets
		):
			return tuple(ast.literal_eval(node.value))
	raise AssertionError("v95_payment_plan_roles defines no _ROLES tuple")


class PaymentPlanEntrySchemaTest(unittest.TestCase):
	def test_the_module_is_gated_by_its_own_flag(self):
		"""Branching on tenant name is CI-banned (``make guards``); a module
		reaches one tenant through a Check on Stabler Company Modules or it
		reaches all seven."""
		fields = {f["fieldname"]: f for f in json.loads(MODULES_JSON.read_text(encoding="utf-8"))["fields"]}
		flag = fields.get("enable_payment_calendar")
		self.assertIsNotNone(flag, "Stabler Company Modules carries no enable_payment_calendar")
		self.assertEqual(flag["fieldtype"], "Check")
		# Off everywhere until a tenant asks for it. The default is the go-live
		# state (.claude/rules/20-backend-migrations.md) — no backfill patch.
		self.assertEqual(flag.get("default"), "0")

	def test_the_derived_fields_are_read_only(self):
		"""``direction`` and ``base_amount`` are computed on validate. Writable,
		they become two numbers a client can disagree with the ledger about."""
		fields = _fields()
		for name in ("direction", "base_amount", "party_name"):
			self.assertEqual(fields[name].get("read_only"), 1, f"{name} must be read-only")

	def test_every_kind_has_a_direction(self):
		"""Totals split in from out. A kind the direction map does not cover
		would land in neither column and silently vanish from the calendar."""
		module, _ = _load_controller()
		kinds = set(_fields()["kind"]["options"].split("\n"))
		self.assertEqual(set(module.DIRECTION_BY_KIND), kinds)
		self.assertTrue(set(module.DIRECTION_BY_KIND.values()) <= {"In", "Out"})

	def test_the_status_set_is_planned_realized_cancelled(self):
		"""Closed by hand, in three states. Anything richer belongs to the
		document being settled, not to the forecast row."""
		self.assertEqual(_fields()["status"]["options"].split("\n"), ["Planned", "Realized", "Cancelled"])

	def test_confidence_is_a_required_axis(self):
		"""A forecast that sums a hope and a signed commitment alike is not a
		forecast — the calendar totals each level separately."""
		confidence = _fields()["confidence"]
		self.assertEqual(confidence["options"].split("\n"), ["Committed", "Expected", "Tentative"])
		self.assertEqual(confidence.get("reqd"), 1)

	def test_the_plan_never_posts_a_payment_entry(self):
		"""Zafar, 2026-08-19: "otomatik payment entry olmasin".

		A plan row is a forecast. If this module ever inserts or submits a
		Payment Entry, every intention a user records becomes a ledger write,
		and the calendar stops being a place people are willing to be wrong in.
		Asserted as an absence because absences regress without anyone noticing.
		"""
		source = CONTROLLER.read_text(encoding="utf-8")
		tree = ast.parse(source)
		for node in ast.walk(tree):
			if isinstance(node, ast.Attribute) and node.attr in {"new_doc", "get_doc", "insert", "submit"}:
				value = getattr(node.value, "id", None) or getattr(node.value, "attr", None)
				self.assertNotEqual(
					value,
					"frappe",
					"the Payment Plan Entry controller must not create documents",
				)
		self.assertNotIn("Payment Entry", source)


class PaymentPlanEntryValidationTest(unittest.TestCase):
	def _entry(self, **overrides):
		module, thrown = _load_controller()
		values = {
			"kind": "Vendor Payment",
			"amount": 1200.0,
			"exchange_rate": 12500.0,
			"currency": "USD",
			"due_date": "2026-09-01",
			"status": "Planned",
			"confidence": "Expected",
			"realized_on": None,
			"reference_doctype": None,
			"reference_name": None,
			"direction": None,
			"base_amount": None,
		}
		values.update(overrides)
		doc = module.PaymentPlanEntry(**values)
		return module, doc, thrown

	def test_direction_is_derived_not_trusted(self):
		"""A client that sends the wrong direction would move money to the wrong
		side of a director's total; the field is overwritten on every validate."""
		_, doc, _ = self._entry(kind="Customer Receipt", direction="Out")
		doc.validate()
		self.assertEqual(doc.direction, "In")

	def test_base_amount_is_the_amount_at_the_row_rate(self):
		"""Every calendar total sums this column. Computed once here so a month
		is one GROUP BY rather than N conversions at read time."""
		_, doc, _ = self._entry(amount=1200.0, exchange_rate=12500.0)
		doc.validate()
		self.assertEqual(doc.base_amount, 15_000_000.0)

	def test_a_missing_rate_means_one_not_zero(self):
		"""A base-currency row carries no rate. Treating that as 0 would drop it
		out of every total while still showing on the calendar."""
		_, doc, _ = self._entry(amount=900.0, exchange_rate=None)
		doc.validate()
		self.assertEqual(doc.base_amount, 900.0)

	def test_a_non_positive_amount_is_rejected(self):
		"""Direction carries the sign. A negative amount would double-negate and
		land on the wrong side of the total."""
		_, doc, _ = self._entry(amount=0)
		with self.assertRaises(ValueError):
			doc.validate()

	def test_realized_requires_the_date_it_was_realized(self):
		"""Marking a row done without saying when leaves the calendar unable to
		tell a plan that landed on time from one that landed two months late."""
		_, doc, _ = self._entry(status="Realized", realized_on=None)
		with self.assertRaises(ValueError):
			doc.validate()

	def test_reopening_a_row_clears_the_realized_date(self):
		"""Otherwise a row put back to Planned keeps a date saying it already
		happened, and shows as both pending and settled."""
		_, doc, _ = self._entry(status="Planned", realized_on="2026-08-01")
		doc.validate()
		self.assertIsNone(doc.realized_on)

	def test_a_plan_row_can_only_point_at_a_commercial_document(self):
		"""An unconstrained Dynamic Link lets a plan row claim to settle a User
		or a File, and the form would then read an amount off a record that has
		none."""
		_, doc, _ = self._entry(reference_doctype="User", reference_name="tester@example.com")
		with self.assertRaises(ValueError):
			doc.validate()

	def test_the_allowed_reference_doctypes_are_the_documented_set(self):
		module, _ = _load_controller()
		self.assertEqual(set(module.ALLOWED_REFERENCE_DOCTYPES), ALLOWED_REFERENCE_DOCTYPES)

	def test_a_reference_needs_both_halves(self):
		"""Half a Dynamic Link points at a doctype and no row; the form would
		render a document chip that opens nothing."""
		_, doc, _ = self._entry(reference_doctype="Sales Invoice", reference_name=None)
		with self.assertRaises(ValueError):
			doc.validate()


if __name__ == "__main__":
	unittest.main()
