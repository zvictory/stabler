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
	_clear_finish_draft,
	_material_consumption_enabled,
	assign_work_order_operators_bulk,
	discard_finish_draft,
	list_work_orders,
	save_finish_draft,
	wo_consumption_preview,
	work_order_detail,
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
		"""The refusal the class otherwise forces open, tested on purpose."""
		frappe.db.set_value("Work Order", self.wo, "status", "Completed")
		out = assign_work_order_operators_bulk(self.company, [self.wo], operator=POURER)
		self.assertEqual(out["assigned"], [])
		self.assertIn("Completed", out["skipped"][0]["reason"])
		self.assertIsNone(self._pair()["operator"])

	def test_a_company_that_is_not_the_orders_company_writes_nothing(self):
		"""Tenant isolation, checked at the endpoint rather than in the partition.
		Either the company guard throws before the query or the partition refuses
		the id — both are correct, and the invariant either way is that the order
		is not written."""
		try:
			out = assign_work_order_operators_bulk("Not A Real Company", [self.wo], operator=POURER)
		except Exception:
			pass
		else:
			self.assertEqual(out["assigned"], [])
		self.assertIsNone(self._pair()["operator"])

	def test_an_empty_selection_is_refused_rather_than_reported_as_success(self):
		with self.assertRaises(frappe.ValidationError):
			assign_work_order_operators_bulk(self.company, [], operator=POURER)

	def test_choosing_nobody_is_refused_rather_than_clearing_the_selection(self):
		with self.assertRaises(frappe.ValidationError):
			assign_work_order_operators_bulk(self.company, [self.wo])
