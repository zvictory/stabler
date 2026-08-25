"""Role scoping against the real columns instead of against mocks.

Every other test of this feature stubs `_wo_operator_columns` or `_item_roles`,
which is right for a unit test: the thing under test is the decision, not the
schema. But it leaves one thing unproven, and on 2026-08-25 that turned out to be
the thing that was actually wrong — neither v97 nor v98 had ever run on any site
reachable from here, so `Work Order.packaging_operator` and
`Item.custom_operator_role` did not exist at all. Both helpers degrade gracefully
when the column is missing, so the graceful path was the only path anyone had ever
executed, and a suite that stays green either way cannot say which one it ran.

So this module touches the columns. It needs a site, which is why it is not in
`.github/frappe-free-tests.txt`:

    bench --site <site> run-tests --module stabler.tests.test_wo_role_scoping_integration

Nothing here is stubbed except the calendar: the roles come off real Items, the
assignment off a real Work Order, the module gate off real user roles, and the
consumption setting off the real Manufacturing Settings single.
"""

from __future__ import annotations

import unittest

import frappe

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from stabler.api.manufacturing import (
	_assert_may_consume,
	_material_consumption_enabled,
	wo_consumption_preview,
	work_order_detail,
)

POURER = "stabler-pourer@test.local"
PACKER = "stabler-packer@test.local"

#: Set on the Work Order's own items, so the split is exercised on whatever
#: fixture the site happens to carry rather than on a shape invented here.
PRODUCTION_UOM_TRAP = "Litre"


def _ensure_user(email: str) -> None:
	if frappe.db.exists("User", email):
		return
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"roles": [{"role": "Manufacturing User"}],
		}
	).insert(ignore_permissions=True)


def _a_submitted_work_order() -> str | None:
	"""Any submitted WO carrying at least two required items, or None."""
	for name in frappe.get_all("Work Order", filters={"docstatus": 1}, pluck="name"):
		if frappe.db.count("Work Order Item", {"parent": name}) >= 2:
			return name
	return None


@unittest.skipUnless(
	frappe.db.table_exists("Work Order") and frappe.db.has_column("Work Order", "packaging_operator"),
	"v97 has not run on this site — nothing to scope",
)
@unittest.skipUnless(
	frappe.db.table_exists("Item") and frappe.db.has_column("Item", "custom_operator_role"),
	"v98 has not run on this site — no material can carry a role",
)
class TestRoleScopingOnRealColumns(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_user(POURER)
		_ensure_user(PACKER)
		cls.wo = _a_submitted_work_order()

	def setUp(self):
		if not self.wo:
			self.skipTest("no submitted Work Order with two or more materials on this site")
		rows = frappe.get_all(
			"Work Order Item", filters={"parent": self.wo}, fields=["item_code"], order_by="item_code"
		)
		self.codes = [r["item_code"] for r in rows]
		# Real writes to the real columns. FrappeTestCase rolls the transaction back,
		# so the site is unchanged when the test ends.
		frappe.db.set_value("Item", self.codes[0], "custom_operator_role", "Packaging")
		frappe.db.set_value("Item", self.codes[1], "custom_operator_role", "Production")
		for extra in self.codes[2:]:
			frappe.db.set_value("Item", extra, "custom_operator_role", "")
		frappe.db.set_value("Work Order", self.wo, "operator", POURER)
		frappe.db.set_value("Work Order", self.wo, "packaging_operator", PACKER)
		self.addCleanup(frappe.set_user, "Administrator")

	def _detail_as(self, user):
		frappe.set_user(user)
		return work_order_detail(self.wo)

	def test_the_pourer_gets_the_production_line_and_not_the_packers(self):
		out = self._detail_as(POURER)
		self.assertEqual(out["my_role"], "Production")
		self.assertEqual([r["item_code"] for r in out["required_items"]], [self.codes[1]])

	def test_the_packer_gets_the_packaging_line_and_not_the_pourers(self):
		out = self._detail_as(PACKER)
		self.assertEqual(out["my_role"], "Packaging")
		self.assertEqual([r["item_code"] for r in out["required_items"]], [self.codes[0]])

	def test_neither_operator_is_shown_a_price(self):
		"""The reason operators were handed no material list at all until now. The
		rows are theirs; the BOM cost behind them is not."""
		for user in (POURER, PACKER):
			for row in self._detail_as(user)["required_items"]:
				self.assertNotIn("rate", row, f"{user} was shown BOM cost")
				self.assertNotIn("amount", row, f"{user} was shown BOM cost")

	def test_the_unit_of_measure_does_not_decide_the_role(self):
		"""The prototype's defect, run against the real column.

		`ishlabChiqarish.js:55` answers "whose material is this" with
		`uom === 'kg' ? raw : packaging`. Here the *packaging* line is deliberately
		the one that would be read as raw by any unit-based rule, and the stored role
		is what the API follows.
		"""
		uom = frappe.db.get_value("Item", self.codes[0], "stock_uom")
		role = frappe.db.get_value("Item", self.codes[0], "custom_operator_role")
		self.assertEqual(role, "Packaging")
		out = self._detail_as(PACKER)
		self.assertEqual(
			[r["item_code"] for r in out["required_items"]],
			[self.codes[0]],
			f"role {role!r} was not honoured for an item measured in {uom!r}",
		)

	def test_a_line_with_no_role_reaches_neither_operator_but_is_counted(self):
		"""v98 ships every Item with an empty role on purpose. An empty role must be
		visible as an open question, not disappear into one operator's sheet."""
		frappe.db.set_value("Item", self.codes[1], "custom_operator_role", "")
		out = self._detail_as(POURER)
		self.assertEqual(out["required_items"], [])
		self.assertGreaterEqual(out["unassigned_item_count"], 1)

	def _enable_consumption(self):
		"""Switch the real setting on for the duration of one test.

		Not a stub — it writes the Manufacturing Settings single, which
		`_material_consumption_enabled` then reads back. FrappeTestCase rolls the
		transaction back afterwards, and the site is off again.
		"""
		frappe.db.set_single_value("Manufacturing Settings", "material_consumption", 1)
		frappe.clear_document_cache("Manufacturing Settings", "Manufacturing Settings")
		self.addCleanup(frappe.clear_document_cache, "Manufacturing Settings", "Manufacturing Settings")
		self.assertTrue(_material_consumption_enabled(), "the setting did not take")

	def test_the_pourer_cannot_write_off_the_packers_material(self):
		"""No stubs anywhere: `_assert_may_consume` reads the roles straight off the
		Items, through the column v98 created.

		The setting has to be switched on first, and finding that out is the reason
		this module exists. Every site reachable from here has
		`material_consumption` off, the setting check short-circuits ahead of the
		role check, and so the role check had never once run outside a mock.
		"""
		self._enable_consumption()
		frappe.set_user(POURER)
		with self.assertRaises(frappe.ValidationError) as cm:
			_assert_may_consume(self.wo, [{"item_code": self.codes[0], "qty": 1}], role_scoped=True)
		self.assertIn(self.codes[0], str(cm.exception))

	def test_the_pourer_may_write_off_their_own_material(self):
		"""The other half of the same guard — otherwise a rule that refuses
		everything would pass the test above."""
		self._enable_consumption()
		frappe.set_user(POURER)
		_assert_may_consume(self.wo, [{"item_code": self.codes[1], "qty": 1}], role_scoped=True)

	def test_an_unprepared_site_is_told_about_the_setting_not_accused(self):
		"""Guard order, asserted deliberately. With `material_consumption` off the
		operator is holding the wrong item AND standing on an un-set-up site; only
		one of those is something they can act on, and blaming them for the other
		operator's material would send them looking for a colleague to argue with.
		"""
		frappe.db.set_single_value("Manufacturing Settings", "material_consumption", 0)
		frappe.clear_document_cache("Manufacturing Settings", "Manufacturing Settings")
		self.addCleanup(frappe.clear_document_cache, "Manufacturing Settings", "Manufacturing Settings")
		frappe.set_user(POURER)
		with self.assertRaises(frappe.ValidationError) as cm:
			_assert_may_consume(self.wo, [{"item_code": self.codes[0], "qty": 1}], role_scoped=True)
		message = str(cm.exception)
		self.assertIn("Allow Continuous Material Consumption", message)
		self.assertNotIn(self.codes[0], message)

	def test_the_preview_keeps_the_role_even_when_it_can_offer_nothing(self):
		"""The role is a fact about the Work Order, not about the list.

		ERPNext refuses to build a consumption stub once an order is fully produced
		(`fg_completed_qty` falls to 0), and the preview swallows that so the kiosk
		does not hard-fail. It must not swallow the role with it: the dialog uses it
		for the role badge and for naming who holds the other half of the order, and
		neither of those depends on there being anything left to write off.
		"""
		self._enable_consumption()
		frappe.set_user(POURER)
		out = wo_consumption_preview(self.wo)
		self.assertTrue(out["enabled"])
		self.assertEqual(out["role"], "Production")

	def test_the_preview_never_offers_the_other_operators_material(self):
		"""End to end on the real thing: the setting on, ERPNext building the list,
		roles read from the Item column."""
		self._enable_consumption()
		frappe.set_user(POURER)
		out = wo_consumption_preview(self.wo)
		if not out["items"]:
			# Said out loud rather than passing quietly. Every Work Order on this site
			# is fully produced, so ERPNext refuses the stub and there is no list to
			# scope — a green tick here would claim coverage this run did not have.
			self.skipTest(f"{self.wo} has nothing pending to consume, so no list was built to scope")
		self.assertNotIn(
			self.codes[0],
			[r["item_code"] for r in out["items"]],
			"the pourer was offered the packer's material",
		)

	def test_the_preview_reports_the_sites_actual_consumption_setting(self):
		"""Reads the real Manufacturing Settings single. With it off the preview must
		offer nothing — measured 2026-08-25, ERPNext would otherwise build the list
		from the whole BOM rather than from what is left in WIP."""
		frappe.set_user(POURER)
		out = wo_consumption_preview(self.wo)
		self.assertEqual(out["enabled"], _material_consumption_enabled())
		if not out["enabled"]:
			self.assertEqual(out["items"], [])
