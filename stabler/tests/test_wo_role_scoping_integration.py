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

import json
import unittest
from pathlib import Path

import frappe
from frappe.utils import add_days, flt, today

try:
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - older/newer frappe
	FrappeTestCase = unittest.TestCase

from stabler.api.manufacturing import (
	_assert_consumption_setting_still_holds,
	_assert_may_consume,
	_assert_sweep_is_acknowledged,
	_clear_finish_draft,
	_material_consumption_enabled,
	_unconsumed_material_rows,
	assign_work_order_operators_bulk,
	create_material_request_for_tomorrow_wo,
	discard_finish_draft,
	list_work_orders,
	reschedule_work_order,
	save_finish_draft,
	update_work_order_materials,
	wo_consumption_preview,
	work_order_detail,
	work_order_plan,
)

POURER = "stabler-pourer@test.local"
PACKER = "stabler-packer@test.local"
STRANGER = "stabler-stranger@test.local"

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
	"""A submitted WO carrying at least two required items, preferring one with
	production still to do.

	The preference is not cosmetic. ERPNext builds its consumption and Manufacture
	stubs off `fg_completed_qty`, which is zero once `produced_qty` reaches `qty` —
	on a finished order `make_stock_entry` raises "For Quantity (Manufactured Qty)
	is mandatory" and every "what is still unconsumed" question in this file
	answers empty. Measured on genesis-test 2026-08-26: the first submitted order
	on the site is `MFG-WO-2026-00001`, Completed at 100/100, and picking it
	self-skipped the sweep-guard tests and hollowed out the preview one — green,
	proving nothing, in the file whose entire job is to run against real columns.
	Thirteen orders with room left were sitting behind it.

	Falls back to any submitted order so a site with only finished ones still runs
	the checks that do not need pending material.
	"""
	fallback = None
	for row in frappe.get_all(
		"Work Order", filters={"docstatus": 1}, fields=["name", "qty", "produced_qty"], order_by="name"
	):
		if frappe.db.count("Work Order Item", {"parent": row["name"]}) < 2:
			continue
		if flt(row["produced_qty"]) < flt(row["qty"]):
			return row["name"]
		if fallback is None:
			fallback = row["name"]
	return fallback


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

	def test_a_scoped_payload_says_so_instead_of_looking_like_an_empty_order(self):
		"""The filtering is invisible to whoever receives it, and that is the bug.

		The lines are cut down to the viewer's own role; the two operator names
		are not cut with them. So the detail page sees the other role as somebody
		assigned to a stage that has no work on it — which is precisely the
		mis-set-BOM shape its one high-signal warning exists to shout about. It
		then shouts on every order every operator opens, and a warning that is
		wrong most of the time is a warning nobody reads the one time it is right.

		The flag is the only thing that lets the screen tell "this stage is empty"
		apart from "this stage is not yours to see", so it has to travel with the
		filtering, not beside it.
		"""
		frappe.set_user(POURER)
		out = work_order_detail(self.wo)
		self.assertEqual(out["items_scoped_to_role"], "Production")

	def test_a_full_payload_carries_no_scope_flag_to_explain_away_a_real_gap(self):
		"""A manager sees every line, so an empty stage really is an empty stage —
		and they are the one who can go and fix the BOM."""
		frappe.set_user("Administrator")
		out = work_order_detail(self.wo)
		self.assertNotIn("items_scoped_to_role", out)

	def test_the_board_gives_the_pourer_only_their_own_material(self):
		"""`list_work_orders` is the only endpoint the kiosk board calls to fill its
		rows. Until now it never sent a `required_items` key at all, so the
		Required Materials block on every card rendered its empty state no matter
		who was looking or what the order actually needed."""
		frappe.set_user(POURER)
		company = frappe.db.get_value("Work Order", self.wo, "company")
		row = next(r for r in list_work_orders(company=company, limit=100) if r["name"] == self.wo)
		self.assertEqual([r["item_code"] for r in row["required_items"]], [self.codes[1]])

	def test_the_board_gives_the_packer_only_their_own_material(self):
		frappe.set_user(PACKER)
		company = frappe.db.get_value("Work Order", self.wo, "company")
		row = next(r for r in list_work_orders(company=company, limit=100) if r["name"] == self.wo)
		self.assertEqual([r["item_code"] for r in row["required_items"]], [self.codes[0]])

	def test_the_board_never_shows_an_operator_a_price(self):
		"""Same reason `work_order_detail` withholds it: the rows are the operator's,
		the BOM cost behind them is the manager's."""
		frappe.set_user(POURER)
		company = frappe.db.get_value("Work Order", self.wo, "company")
		row = next(r for r in list_work_orders(company=company, limit=100) if r["name"] == self.wo)
		self.assertTrue(row["required_items"], "fixture produced no rows to check")
		for item in row["required_items"]:
			self.assertNotIn("rate", item, "an operator was shown BOM cost on the board")
			self.assertNotIn("amount", item, "an operator was shown BOM cost on the board")

	def test_the_manager_sees_every_material_line_on_the_board(self):
		"""Managers stage the whole transfer, so they keep the whole list — same
		rule `work_order_detail` applies, now proven on the list endpoint too."""
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Work Order", self.wo, "company")
		row = next(r for r in list_work_orders(company=company, limit=100) if r["name"] == self.wo)
		self.assertEqual(sorted(r["item_code"] for r in row["required_items"]), sorted(self.codes))

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
		self._set_consumption(1)

	def _set_consumption(self, value):
		"""Either way round — D2 needs the off state written just as literally as
		the on state, and reading it back is the only thing that proves the single
		and its cache actually moved."""
		frappe.db.set_single_value("Manufacturing Settings", "material_consumption", value)
		frappe.clear_document_cache("Manufacturing Settings", "Manufacturing Settings")
		self.addCleanup(frappe.clear_document_cache, "Manufacturing Settings", "Manufacturing Settings")
		self.assertEqual(_material_consumption_enabled(), bool(value), "the setting did not take")

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
		roles read from the Item column.

		BOTH lines are forced pending, and both directions are asserted. With only
		the pourer's line pending the `assertNotIn` passes without proving
		anything — the packer's material was never in ERPNext's list to be scoped
		out of it, so a preview with no role filter at all would be just as green.
		"""
		self._enable_consumption()
		self._force_pending(self.codes[0])  # the packer's line
		self._force_pending(self.codes[1])  # the pourer's own
		frappe.set_user(POURER)
		out = wo_consumption_preview(self.wo)
		if not out["items"]:
			# Said out loud rather than passing quietly. ERPNext refuses the stub
			# outright once an order is fully produced (fg_completed_qty falls to 0)
			# no matter what consumed_qty says — a green tick here would claim
			# coverage this run did not have.
			self.skipTest(f"{self.wo} has nothing pending to consume, so no list was built to scope")
		offered = [r["item_code"] for r in out["items"]]
		self.assertIn(self.codes[1], offered, "the pourer was not offered their own material")
		self.assertNotIn(self.codes[0], offered, "the pourer was offered the packer's material")

	def test_the_preview_reports_the_sites_actual_consumption_setting(self):
		"""Reads the real Manufacturing Settings single. With it off the preview must
		offer nothing — measured 2026-08-25, ERPNext would otherwise build the list
		from the whole BOM rather than from what is left in WIP."""
		frappe.set_user(POURER)
		out = wo_consumption_preview(self.wo)
		self.assertEqual(out["enabled"], _material_consumption_enabled())
		if not out["enabled"]:
			self.assertEqual(out["items"], [])

	def _required(self, item_code):
		return flt(
			frappe.db.get_value(
				"Work Order Item", {"parent": self.wo, "item_code": item_code}, "required_qty"
			)
		)

	def _save_materials(self, item_code, qty):
		"""Restores what it wrote. `FrappeTestCase` rolls this file back once per
		CLASS, not per test — measured 2026-08-26, when a status forced to
		Completed by one test was still Completed two tests later and refused a
		manager who should have been let through. Every test below writes real
		rows, so each puts its own back and none of them depends on the order the
		loader happens to pick."""
		before = self._required(item_code)
		self.addCleanup(
			frappe.db.set_value,
			"Work Order Item",
			{"parent": self.wo, "item_code": item_code},
			"required_qty",
			before,
		)
		return update_work_order_materials(
			self.wo, json.dumps([{"item_code": item_code, "required_qty": qty}])
		)

	def _force_status(self, status):
		before = frappe.db.get_value("Work Order", self.wo, "status")
		self.addCleanup(frappe.db.set_value, "Work Order", self.wo, "status", before)
		frappe.db.set_value("Work Order", self.wo, "status", status)

	def test_the_pourer_cannot_rewrite_the_packers_planned_quantity(self):
		"""D7 (P0). `required_qty` is the denominator the deviation panel scores
		people against, and this endpoint writes it with raw SQL that deliberately
		bypasses the docstatus lock. Unscoped, one operator can move the other
		one's bar: raise the packer's plan and the packer looks efficient, lower
		it and the packer looks wasteful, and the packer is never told.

		The kiosk only ever sends the caller's own lines — `list_work_orders` has
		been role-scoped since 238592a — so this closes the hand-made request, not
		the screen. Which is the point: the screen was never the guard."""
		before = self._required(self.codes[0])  # the packer's line
		frappe.set_user(POURER)
		with self.assertRaises(frappe.ValidationError):
			self._save_materials(self.codes[0], before + 99)
		frappe.set_user("Administrator")
		self.assertEqual(self._required(self.codes[0]), before, "the packer's plan moved")

	def test_the_pourer_can_still_correct_their_own_line(self):
		"""The other half, and the one that proves the guard is scoping rather
		than simply refusing everything — a test suite where the endpoint had been
		disabled outright would pass the test above just as well."""
		frappe.set_user(POURER)
		self._save_materials(self.codes[1], 77)
		frappe.set_user("Administrator")
		self.assertEqual(self._required(self.codes[1]), 77)

	def test_the_manager_may_still_plan_both_roles(self):
		frappe.set_user("Administrator")
		self._save_materials(self.codes[0], 55)
		self.assertEqual(self._required(self.codes[0]), 55)

	def test_a_finished_order_no_longer_accepts_a_new_plan(self):
		"""Rewriting the plan for a shift that has already been scored rewrites
		the score. The raw SQL goes through docstatus on purpose, so nothing else
		stops this."""
		before = self._required(self.codes[1])
		self._force_status("Completed")
		frappe.set_user(POURER)
		with self.assertRaises(frappe.ValidationError):
			self._save_materials(self.codes[1], before + 5)
		frappe.set_user("Administrator")
		self.assertEqual(self._required(self.codes[1]), before)

	def test_the_change_is_recorded_with_the_number_it_replaced(self):
		"""An adjustment nobody can reconstruct is indistinguishable from the
		fraud it enables. "Raw materials manually adjusted by X" — the whole audit
		trail before this — says a number moved without saying which, from what,
		or to what, so a plan quietly raised 20% reads exactly like a typo
		corrected back."""
		before = self._required(self.codes[1])
		frappe.set_user(POURER)
		self._save_materials(self.codes[1], before + 3)
		frappe.set_user("Administrator")
		note = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Order", "reference_name": self.wo},
			fields=["content"],
			order_by="creation desc",
			limit=1,
		)
		self.assertTrue(note, "no event was logged at all")
		content = note[0]["content"]
		self.assertIn(self.codes[1], content)
		self.assertIn(str(before), content)
		self.assertIn(str(before + 3), content)

	def _force_pending(self, item_code):
		"""Zero this line's consumed_qty so ERPNext's own stub still lists it as
		unconsumed regardless of whatever this real Work Order already had —
		FrappeTestCase rolls the write back with everything else."""
		frappe.db.set_value("Work Order Item", {"parent": self.wo, "item_code": item_code}, "consumed_qty", 0)

	def test_a_role_is_refused_finish_while_the_other_has_unwritten_off_material(self):
		"""Failure B, end to end on the real columns: measured live on genesis-test
		2026-08-25 against a fully assigned order where the packer never wrote off
		his material — the pourer pressed Finish and it succeeded onto his own
		document (MAT-STE-2026-00037, PROBE-LABEL consumed_qty 0.0 -> 10.0).
		`_assert_sweep_is_acknowledged` is asked the same question ERPNext itself
		answers when it builds the Manufacture stub, off the real child table.
		"""
		self._enable_consumption()
		self._force_pending(self.codes[0])  # the packer's (Packaging) line
		frappe.set_user(POURER)
		if not any(r["item_code"] == self.codes[0] for r in _unconsumed_material_rows(self.wo) or []):
			# ERPNext refuses the stub once the order is fully produced regardless
			# of consumed_qty (fg_completed_qty falls to 0) — said out loud rather
			# than passing quietly, the same escape hatch this file already uses
			# for the preview above.
			self.skipTest(f"{self.wo} has nothing pending even after clearing consumed_qty")
		item_name = frappe.db.get_value("Item", self.codes[0], "item_name") or self.codes[0]
		with self.assertRaises(frappe.ValidationError) as cm:
			_assert_sweep_is_acknowledged(self.wo, "Production", False)
		self.assertIn(item_name, str(cm.exception))

	def test_a_written_off_order_is_refused_while_the_setting_is_off(self):
		"""D2 against the real Stock Entry table, which is the half mocks cannot
		reach: the guard's whole decision rests on a filter over `work_order`,
		`purpose` and `docstatus`, and a mocked `frappe.db.exists` proves those
		field names spelled right exactly as well as it proves them spelled wrong.

		Picks a real order that genuinely carries submitted per-role write-offs
		rather than manufacturing one, so what is asserted is the state the shop
		floor actually leaves behind."""
		wo = frappe.db.get_value(
			"Stock Entry",
			{"purpose": "Material Consumption for Manufacture", "docstatus": 1},
			"work_order",
		)
		if not wo:
			self.skipTest("no submitted per-role consumption entry on this site to guard against")
		self._set_consumption(0)
		with self.assertRaises(frappe.ValidationError) as cm:
			_assert_consumption_setting_still_holds(wo)
		self.assertIn("Manufacturing Settings", str(cm.exception))
		self._set_consumption(1)
		_assert_consumption_setting_still_holds(wo)  # must not raise

	def test_acknowledging_the_sweep_lets_the_real_finish_through(self):
		"""The other half of the same guard, against the same real state — proving
		`acknowledge_sweep` genuinely reaches and overrides it, not just that the
		refusal fires."""
		self._enable_consumption()
		self._force_pending(self.codes[0])
		frappe.set_user(POURER)
		if not any(r["item_code"] == self.codes[0] for r in _unconsumed_material_rows(self.wo) or []):
			self.skipTest(f"{self.wo} has nothing pending even after clearing consumed_qty")
		_assert_sweep_is_acknowledged(self.wo, "Production", True)  # must not raise


@unittest.skipUnless(frappe.db.table_exists("Work Order"), "no Work Order table on this site")
class TestErpnextAcceptsTheShapeWeBuildForRejects(FrappeTestCase):
	"""D4 (P0), against ERPNext's own validation rather than a mock of it.

	`validate_fg_completed_qty` (stock_entry.py:747) requires
	`fg_completed_qty == fg row qty + process_loss_qty`. Setting process_loss_qty
	and leaving the finished-goods row whole therefore does not miscount — it
	throws, in front of an operator who typed a reject count on a tablet, and the
	only way through was to lie about the rejects.

	Both shapes are built and INSERTED AS DRAFTS. Validation is what is being
	tested and it runs on insert; submitting would move real stock and rewrite
	`produced_qty` on a real order for nothing. The mocked tests in
	test_manufacturing_kiosk.py hold our side of the arithmetic; this holds
	ERPNext's, which is the half that can change under us on an upgrade.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.wo = None
		for row in frappe.get_all(
			"Work Order", filters={"docstatus": 1}, fields=["name", "qty", "produced_qty"], order_by="name"
		):
			if flt(row["qty"]) - flt(row["produced_qty"]) >= 2:
				cls.wo = row["name"]
				break

	def setUp(self):
		if not self.wo:
			self.skipTest("no submitted Work Order with at least 2 units left to produce")
		frappe.set_user("Administrator")

	def _draft(self, attempted, fg_qty, loss):
		from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

		stub = make_stock_entry(self.wo, "Manufacture", qty=attempted)
		se = frappe.get_doc(stub if isinstance(stub, dict) else stub.as_dict())
		se.process_loss_qty = loss
		for r in se.items:
			r.allow_zero_valuation_rate = 1
			if r.is_finished_item:
				r.qty = fg_qty
		se.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Stock Entry", se.name, force=True)
		return se

	def test_the_old_shape_is_refused_by_erpnext_itself(self):
		"""One good unit, one rejected, and the finished-goods row left whole —
		exactly what the endpoint built before. If this ever stops raising, the
		arithmetic we now do is no longer needed and should go."""
		with self.assertRaises(frappe.ValidationError) as cm:
			self._draft(attempted=1, fg_qty=1, loss=1)
		self.assertIn("process loss", str(cm.exception).lower())

	def test_the_shape_we_build_now_validates(self):
		se = self._draft(attempted=2, fg_qty=1, loss=1)
		self.assertEqual(flt(se.fg_completed_qty), 2.0)
		self.assertEqual([flt(r.qty) for r in se.items if r.is_finished_item], [1.0])


@unittest.skipUnless(frappe.db.table_exists("Work Order"), "no Work Order table on this site")
class TestAForwardDatedOrderCanActuallyBeSubmitted(FrappeTestCase):
	"""D8 (P0) — nothing to do with the two-operator split, but on the ground it
	was built on: `create_material_request_for_tomorrow_wo` is wired to Work Order
	`on_submit` in hooks.py, and it set `material_request_type = "Transfer"`,
	which is not one of the six values the doctype offers. Measured
	genesis-test 2026-08-26:

	    Purpose cannot be "Transfer". It should be one of "Purchase",
	    "Material Transfer", "Material Issue", "Manufacture", "Subcontracting",
	    "Customer Provided"

	So the module did not support ordinary planning. The manager hits the wall on
	SUBMIT, not on save — the cost is the whole form they filled in, not a click.

	The hook has a `if not doc.wip_warehouse: return` branch that looks like an
	escape, and is unreachable: ERPNext calls `validate_warehouse()` from
	`on_submit` and makes `wip_warehouse` mandatory (work_order.py:786-793) unless
	`skip_transfer` or `track_semi_finished_goods`, and Stabler sets neither
	anywhere. That branch is dead by our configuration, not by ERPNext's design.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.wo = _a_submitted_work_order()

	def setUp(self):
		if not self.wo:
			self.skipTest("no submitted Work Order on this site")
		frappe.set_user("Administrator")

	def test_the_type_is_one_the_doctype_actually_offers(self):
		"""The cheap forever-guard. Read off the live meta rather than hardcoded,
		so it keeps holding when ERPNext changes the list — and it is the check
		whose absence let a value that matches nothing sit in two places for
		months, on a path no test ever reached."""
		import re

		from stabler.api import manufacturing

		options = (
			frappe.get_meta("Material Request").get_field("material_request_type").options or ""
		).split("\n")

		# Scoped to a local function so the 2000-line source never becomes a frame
		# variable — unittest prints every local on failure, and the whole module
		# in the traceback buries the one line that matters.
		def _literals():
			return set(
				re.findall(
					r'material_request_type = "([^"]+)"',
					Path(manufacturing.__file__).read_text(encoding="utf-8"),
				)
			)

		used = _literals()
		self.assertTrue(used, "no material_request_type literal found to check")
		for value in used:
			self.assertIn(value, options, f'"{value}" is not a Material Request purpose')

	def test_a_forward_dated_order_produces_a_request_the_warehouse_can_act_on(self):
		"""End to end through the hook itself, on a real order, with a shortage
		forced so the request is guaranteed to have a line. Before the fix this
		raised on `insert` and the Work Order could not be submitted at all."""
		doc = frappe.get_doc("Work Order", self.wo)
		if frappe.db.exists("Material Request", {"work_order": doc.name, "docstatus": ["!=", 2]}):
			self.skipTest(f"{doc.name} already carries a Material Request; the hook returns early")

		before_date = doc.planned_start_date
		self.addCleanup(frappe.db.set_value, "Work Order", doc.name, "planned_start_date", before_date)
		doc.planned_start_date = add_days(today(), 3)

		# A shortage no warehouse can already hold, so `mr.items` is never empty and
		# the test cannot pass by quietly creating nothing.
		item = doc.required_items[0]
		before_qty = flt(item.required_qty)
		self.addCleanup(
			frappe.db.set_value,
			"Work Order Item",
			{"parent": doc.name, "item_code": item.item_code},
			"required_qty",
			before_qty,
		)
		item.required_qty = before_qty + 999_999

		create_material_request_for_tomorrow_wo(doc)

		mr = frappe.db.get_value(
			"Material Request",
			{"work_order": doc.name, "docstatus": 1},
			["name", "material_request_type"],
			as_dict=True,
		)
		self.assertTrue(mr, "the hook created no submitted Material Request")
		self.addCleanup(self._drop_mr, mr["name"])
		self.assertEqual(mr["material_request_type"], "Material Transfer")

	def _drop_mr(self, name):
		frappe.set_user("Administrator")
		doc = frappe.get_doc("Material Request", name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc("Material Request", name, force=True, ignore_permissions=True)


@unittest.skipUnless(
	frappe.db.table_exists("Work Order") and frappe.db.has_column("Work Order", "custom_finish_draft"),
	"v99 has not run on this site — nothing can hold a draft",
)
class TestTheDraftSurvivesTheOperator(FrappeTestCase):
	"""Written to the real columns and read back through the real endpoints.

	The whole promise of this feature is "it is still there when you come back",
	and the unit tests prove the encoding round-trips in memory. What they cannot
	prove is that it reaches the database and comes back out — which is the only
	part the operator experiences.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_user(POURER)
		cls.wo = _a_submitted_work_order()

	def setUp(self):
		if not self.wo:
			self.skipTest("no submitted Work Order on this site")
		frappe.db.set_value("Work Order", self.wo, "operator", POURER)
		frappe.db.set_value("Work Order", self.wo, "packaging_operator", PACKER)
		self.addCleanup(frappe.set_user, "Administrator")

	def _detail_as(self, user):
		frappe.set_user(user)
		return work_order_detail(self.wo)

	def test_a_parked_count_comes_back_after_the_operator_leaves(self):
		frappe.set_user(POURER)
		save_finish_draft(self.wo, produced_qty=182, scrap_qty=6, batch_no="ICE-20260825")
		# Badge out, badge back in: a fresh session reads it off the order.
		frappe.set_user("Administrator")
		draft = self._detail_as(POURER)["finish_draft"]
		self.assertEqual(draft["produced_qty"], 182.0)
		self.assertEqual(draft["scrap_qty"], 6.0)
		self.assertEqual(draft["batch_no"], "ICE-20260825")

	def test_the_other_operator_on_the_same_order_sees_whose_it_is(self):
		"""The reason the author is a column. Two people share this order, and the
		one who opens it next is deciding whether to confirm somebody else's count
		or walk the pallet again."""
		frappe.set_user(POURER)
		save_finish_draft(self.wo, produced_qty=182, scrap_qty=6)
		draft = self._detail_as(PACKER)["finish_draft"]
		self.assertEqual(draft["saved_by"], POURER)
		self.assertTrue(draft["saved_at"])

	def test_a_zero_count_survives_the_round_trip_too(self):
		"""The unit test proves the decoder keeps it. This proves the column does —
		an empty-ish value is exactly what a database layer likes to normalise away.
		"""
		frappe.set_user(POURER)
		save_finish_draft(self.wo, produced_qty=0, scrap_qty=40)
		draft = self._detail_as(POURER)["finish_draft"]
		self.assertIsNotNone(draft)
		self.assertEqual(draft["produced_qty"], 0.0)
		self.assertEqual(draft["scrap_qty"], 40.0)

	def test_discarding_leaves_no_draft_behind(self):
		frappe.set_user(POURER)
		save_finish_draft(self.wo, produced_qty=182, scrap_qty=6)
		discard_finish_draft(self.wo)
		self.assertIsNone(self._detail_as(POURER)["finish_draft"])

	def test_a_stranger_cannot_park_a_count_on_someone_elses_order(self):
		"""`_require_own_work_order` is the gate. Without it any operator could write
		a finish count onto an order they have never seen, and the person who does
		own it would find it waiting and confirm it."""
		_ensure_user(STRANGER)
		frappe.set_user(STRANGER)
		with self.assertRaises(frappe.PermissionError):
			save_finish_draft(self.wo, produced_qty=1)

	def test_the_board_carries_the_draft_without_leaking_the_raw_columns(self):
		"""The kiosk reads its whole board from `list_work_orders`, so the banner has
		to arrive with the rows. The raw columns do not: they are storage, and a row
		carrying both shapes invites the client to pick the wrong one."""
		frappe.set_user(POURER)
		save_finish_draft(self.wo, produced_qty=182, scrap_qty=6)
		company = frappe.db.get_value("Work Order", self.wo, "company")
		row = next(r for r in list_work_orders(company=company, limit=100) if r["name"] == self.wo)
		self.assertEqual(row["finish_draft"]["produced_qty"], 182.0)
		self.assertNotIn("custom_finish_draft", row)

	def test_the_draft_is_gone_once_the_order_is_finished(self):
		"""Posting the Manufacture entry is out of reach here — it moves real stock —
		so this drives the same helper that path calls, against the real columns."""
		frappe.set_user(POURER)
		save_finish_draft(self.wo, produced_qty=182, scrap_qty=6)
		frappe.set_user("Administrator")
		_clear_finish_draft(self.wo)
		self.assertIsNone(self._detail_as(POURER)["finish_draft"])


@unittest.skipUnless(
	frappe.db.table_exists("Work Order") and frappe.db.has_column("Work Order", "packaging_operator"),
	"v97 has not run on this site — nothing to assign",
)
class TestTheShiftLogFiltersNarrowRealRows(FrappeTestCase):
	"""`build_work_order_filters` is proved pure in `test_wo_shift_log_filters`;
	what that cannot see is whether the columns it names exist and hold what the
	screen thinks. `wip_warehouse` is the whole line dimension — there are 0
	Workstation records on anjan — so a typo in that column name would leave a
	filter that silently returns nothing, and an empty shift log reads as a quiet
	day rather than as a bug.

	Each test asserts both directions against one real order: the filter that
	should find it does, and the filter that should exclude it does.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wo = _a_submitted_work_order()

	def setUp(self):
		if not self.wo:
			self.skipTest("no submitted Work Order on this site")
		frappe.set_user("Administrator")
		self.row = frappe.db.get_value(
			"Work Order", self.wo, ["company", "wip_warehouse", "planned_start_date"], as_dict=True
		)

	def _names(self, **kwargs):
		return [r["name"] for r in list_work_orders(company=self.row.company, limit=100, **kwargs)]

	def test_the_line_filter_reads_a_column_that_exists_and_matches(self):
		if not self.row.wip_warehouse:
			self.skipTest("order carries no wip_warehouse")
		self.assertIn(self.wo, self._names(line=self.row.wip_warehouse))
		self.assertNotIn(self.wo, self._names(line="Hicbir Yerde - ZZ"))

	def test_the_date_range_includes_the_day_the_order_is_planned_for(self):
		"""The inclusive-end rule, against a real datetime column. An order
		planned at 09:00 must fall inside a range whose end is that same day —
		the case a `<=` comparison against midnight silently drops."""
		if not self.row.planned_start_date:
			self.skipTest("order carries no planned_start_date")
		day = str(self.row.planned_start_date)[:10]
		self.assertIn(self.wo, self._names(from_date=day, to_date=day))

	def test_a_range_that_ends_before_the_order_excludes_it(self):
		if not self.row.planned_start_date:
			self.skipTest("order carries no planned_start_date")
		day = frappe.utils.add_days(str(self.row.planned_start_date)[:10], -1)
		self.assertNotIn(self.wo, self._names(to_date=day))

	def test_an_operator_filter_finds_the_order_under_either_role(self):
		"""Both roles, because the packer and the pourer share the order. Written
		against the real columns: `packaging_operator` arrived in v97 and a site
		that has not migrated would fail here rather than quietly return nothing."""
		before = frappe.db.get_value("Work Order", self.wo, ["operator", "packaging_operator"], as_dict=True)
		try:
			frappe.db.set_value("Work Order", self.wo, "operator", POURER)
			frappe.db.set_value("Work Order", self.wo, "packaging_operator", None)
			self.assertIn(self.wo, self._names(operator=POURER))

			frappe.db.set_value("Work Order", self.wo, "operator", None)
			frappe.db.set_value("Work Order", self.wo, "packaging_operator", PACKER)
			self.assertIn(self.wo, self._names(operator=PACKER), "paketleme rolü filtreden düşüyor")
			self.assertNotIn(self.wo, self._names(operator=STRANGER))
		finally:
			for field, value in (before or {}).items():
				frappe.db.set_value("Work Order", self.wo, field, value)


class TestBulkAssignAgainstRealOrders(FrappeTestCase):
	"""The partition is proved pure elsewhere; this proves the endpoint writes what
	the partition decided and does not go on to write what it refused.

	The order's `status` is forced open for the duration of each test and put back
	afterwards. Every Work Order on a fresh test site is Completed, and the endpoint
	is right to refuse those — so without this the whole class would only ever prove
	that a finished order is left alone, which the pure tests already say. The write
	is to the status field the partition actually reads, at docstatus 1, restored in
	`tearDown` together with the operator pair.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_ensure_user(POURER)
		_ensure_user(PACKER)
		_ensure_user(STRANGER)
		cls.wo = _a_submitted_work_order()

	def setUp(self):
		if not self.wo:
			self.skipTest("no submitted Work Order on this site")
		frappe.set_user("Administrator")
		self.company = frappe.db.get_value("Work Order", self.wo, "company")
		self._before = frappe.db.get_value(
			"Work Order", self.wo, ["operator", "packaging_operator", "status"], as_dict=True
		)
		frappe.db.set_value("Work Order", self.wo, "status", "In Process")

	def tearDown(self):
		for field, value in (self._before or {}).items():
			frappe.db.set_value("Work Order", self.wo, field, value)
		frappe.db.commit()

	def _pair(self):
		return frappe.db.get_value("Work Order", self.wo, ["operator", "packaging_operator"], as_dict=True)

	def test_both_roles_land_on_the_order(self):
		out = assign_work_order_operators_bulk(
			self.company, [self.wo], operator=POURER, packaging_operator=PACKER
		)
		self.assertEqual(out["assigned"], [self.wo])
		self.assertEqual(out["skipped"], [])
		self.assertEqual(self._pair(), {"operator": POURER, "packaging_operator": PACKER})

	def test_filling_one_box_does_not_wipe_the_other_role(self):
		"""The whole reason bulk needs its own write rule. If this regresses, a shift
		lead assigning pourers to a day's orders removes every packer on them, and
		nothing in the response says so."""
		assign_work_order_operators_bulk(self.company, [self.wo], operator=POURER, packaging_operator=PACKER)
		assign_work_order_operators_bulk(self.company, [self.wo], operator=STRANGER)
		self.assertEqual(self._pair(), {"operator": STRANGER, "packaging_operator": PACKER})

	def test_the_same_person_in_both_roles_is_refused_per_order_not_thrown(self):
		"""One clashing order must not cost the manager the other fourteen writes,
		so this comes back as a refusal in the payload and not as an exception."""
		assign_work_order_operators_bulk(self.company, [self.wo], operator=POURER, packaging_operator=PACKER)
		out = assign_work_order_operators_bulk(self.company, [self.wo], operator=PACKER)
		self.assertEqual(out["assigned"], [])
		self.assertIn(PACKER, out["skipped"][0]["reason"])
		self.assertEqual(self._pair(), {"operator": POURER, "packaging_operator": PACKER})

	def test_a_finished_order_is_left_alone(self):
		"""The refusal the class otherwise forces open, tested on purpose.

		"Left alone" is asserted as UNCHANGED, not as empty. Empty was true only
		of the one order this file used to pick — a fresh Work Order nobody had
		assigned — and a bulk assign that wiped an existing pair while reporting
		`assigned: []` would have passed it. That is the exact failure the bulk
		write rule exists to prevent, and the shift lead sees no sign of it."""
		before = self._pair()
		frappe.db.set_value("Work Order", self.wo, "status", "Completed")
		out = assign_work_order_operators_bulk(self.company, [self.wo], operator=POURER)
		self.assertEqual(out["assigned"], [])
		self.assertIn("Completed", out["skipped"][0]["reason"])
		self.assertEqual(self._pair(), before)

	def test_a_company_that_is_not_the_orders_company_writes_nothing(self):
		"""Tenant isolation, checked at the endpoint rather than in the partition.
		Either the company guard throws before the query or the partition refuses
		the id — both are correct, and the invariant either way is that the order
		is not written. Unchanged rather than empty, for the reason above."""
		before = self._pair()
		try:
			out = assign_work_order_operators_bulk("Not A Real Company", [self.wo], operator=POURER)
		except Exception:
			pass
		else:
			self.assertEqual(out["assigned"], [])
		self.assertEqual(self._pair(), before)

	def test_an_empty_selection_is_refused_rather_than_reported_as_success(self):
		with self.assertRaises(frappe.ValidationError):
			assign_work_order_operators_bulk(self.company, [], operator=POURER)

	def test_choosing_nobody_is_refused_rather_than_clearing_the_selection(self):
		with self.assertRaises(frappe.ValidationError):
			assign_work_order_operators_bulk(self.company, [self.wo])


class TestThePlanBoardAgainstRealOrders(FrappeTestCase):
	"""`build_plan_grid` is proved pure in `test_wo_plan_board`; what that cannot
	see is whether the board's one write actually lands, and whether the columns
	it reads exist.

	The write is the reason this class exists. `planned_start_date` is writable
	after submit and `wip_warehouse` is not — the whole screen is built on that
	asymmetry, and it is a property of this site's doctype meta, not of our code.
	If a future ERPNext or a customisation flipped `allow_on_submit` on
	`planned_start_date`, the board would keep rendering, keep accepting drags,
	and keep writing nothing. `db.set_value` does not raise on a non-writable
	field; it just does not appear on the next read, which is the failure mode
	this class is here to catch.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.wo = _a_submitted_work_order()

	def setUp(self):
		if not self.wo:
			self.skipTest("no submitted Work Order on this site")
		frappe.set_user("Administrator")
		self.row = frappe.db.get_value(
			"Work Order", self.wo, ["company", "status", "planned_start_date"], as_dict=True
		)
		self.addCleanup(
			frappe.db.set_value,
			"Work Order",
			self.wo,
			"planned_start_date",
			self.row.planned_start_date,
		)
		self.addCleanup(frappe.db.set_value, "Work Order", self.wo, "status", self.row.status)

	def _planned(self):
		return str(frappe.db.get_value("Work Order", self.wo, "planned_start_date"))

	def test_the_move_reaches_the_database(self):
		"""The assertion is a read-back, not the endpoint's return value. A write
		to a field ERPNext refuses after submit fails silently here."""
		target = add_days(str(self.row.planned_start_date or today())[:10], 3)
		reschedule_work_order(self.wo, target)
		self.assertEqual(self._planned()[:10], target)

	def test_the_hour_the_order_starts_at_survives_the_move(self):
		"""Proved against the real column because this is where it would be lost:
		a Datetime field written with a bare date stores midnight, and every
		screen compares the date half, so nothing would report it."""
		frappe.db.set_value("Work Order", self.wo, "planned_start_date", f"{today()} 09:30:00")
		reschedule_work_order(self.wo, add_days(today(), 2))
		self.assertEqual(self._planned()[11:16], "09:30")

	def test_a_completed_order_is_refused_and_left_where_it_was(self):
		"""Unchanged, not merely refused. Rewriting the planned date of finished
		work edits the only record of when it ran."""
		frappe.db.set_value("Work Order", self.wo, "status", "Completed")
		before = self._planned()
		with self.assertRaises(frappe.ValidationError):
			reschedule_work_order(self.wo, add_days(today(), 4))
		self.assertEqual(self._planned(), before)

	def test_a_day_that_is_not_a_day_is_refused(self):
		before = self._planned()
		with self.assertRaises(frappe.ValidationError):
			reschedule_work_order(self.wo, "yarin")
		self.assertEqual(self._planned(), before)

	def test_the_order_appears_in_the_square_it_was_moved_to(self):
		"""End to end on real columns: move it, then find it on the board. This
		is what proves `wip_warehouse` and `planned_start_date` are the columns
		the grid is actually keyed on."""
		target = add_days(today(), 5)
		reschedule_work_order(self.wo, target)
		grid = work_order_plan(self.row.company, target, target)
		placed = [cell for cell in grid["cells"] if any(o["name"] == self.wo for o in cell["orders"])]
		unscheduled = [o["name"] for o in grid["unscheduled"]]
		line = frappe.db.get_value("Work Order", self.wo, "wip_warehouse")
		if not line:
			self.assertIn(self.wo, unscheduled, "hatsız emir sessizce düşmüş")
			return
		self.assertEqual(len(placed), 1, f"emir {len(placed)} karede; unscheduled={unscheduled}")
		self.assertEqual(placed[0]["day"], target)
		self.assertEqual(placed[0]["line"], line)

	def test_the_board_never_returns_a_load_figure(self):
		"""The same refusal `test_wo_plan_board` pins, asserted on what the
		endpoint actually serialises — a capacity number added downstream would
		pass the pure test and still reach the screen."""
		grid = work_order_plan(self.row.company, today(), today())
		for cell in grid["cells"]:
			for invented in ("load", "capacity", "utilisation", "utilization", "hours"):
				self.assertNotIn(invented, cell, f"uydurulmus alan: {invented}")

	def test_a_window_wider_than_the_cap_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			work_order_plan(self.row.company, today(), add_days(today(), 60))

	def test_a_backwards_window_is_refused_rather_than_returning_nothing(self):
		"""An empty board reads as "no work planned". A window that ends before it
		starts is a bug in the caller and has to say so."""
		with self.assertRaises(frappe.ValidationError):
			work_order_plan(self.row.company, today(), add_days(today(), -3))

	def test_a_foreign_company_is_refused(self):
		before = self._planned()
		with self.assertRaises(Exception):
			work_order_plan("Not A Real Company", today(), today())
		self.assertEqual(self._planned(), before)
