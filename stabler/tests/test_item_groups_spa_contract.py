"""Source-level guardrails for the Item Group (category) SPA feature."""

import csv
import re
import unittest
from pathlib import Path

ITEM_GROUPS = Path(__file__).parents[1] / "public/js/pages/inventory/ItemGroups.vue"
ITEMS = Path(__file__).parents[1] / "public/js/pages/inventory/Items.vue"
ROUTER = Path(__file__).parents[1] / "public/js/router.js"
INVENTORY_HOME = Path(__file__).parents[1] / "public/js/pages/inventory/InventoryHome.vue"
INVENTORY_API = Path(__file__).parents[1] / "api/inventory.py"
TRANSLATIONS = Path(__file__).parents[1] / "translations"
LANGUAGES = ("en", "ru", "uz", "uzc", "tr")

ITEM_GROUP_ENDPOINTS = (
	"list_item_group_tree",
	"create_item_group",
	"update_item_group",
	"item_group_delete_impact",
	"delete_item_group",
)

# Strings the category filter added to Items.vue. Kept as a hand-maintained
# subset (not derived from the whole file) because Items.vue also renders
# pre-existing, unrelated t() calls — e.g. the price-list-rates modal — that
# already ship without translations; that is a separate, out-of-scope bug,
# not something this feature should fail its own test over.
ITEMS_CATEGORY_KEYS = (
	"Include subcategories",
	"Manage categories",
	"Category or parent",
	"All Groups",
)


class TestItemGroupsSpaContract(unittest.TestCase):
	def test_categories_route_and_tab_are_wired(self):
		router = ROUTER.read_text()
		home = INVENTORY_HOME.read_text()
		self.assertIn('import ItemGroups from "./pages/inventory/ItemGroups.vue"', router)
		self.assertIn('path: "categories", name: "inventory-item-groups", component: ItemGroups', router)
		self.assertIn('name: "inventory-item-groups", path: "/inventory/categories"', home)

	def test_item_groups_page_stays_inside_spa_and_follows_house_rules(self):
		source = ITEM_GROUPS.read_text()
		self.assertNotIn("/app/", source)
		self.assertNotIn("table-striped", source)
		self.assertNotIn("btn-success", source)
		self.assertIn("<ListToolbar", source)
		self.assertIn("<SkeletonRows", source)

	def test_items_page_stays_inside_spa_and_follows_house_rules(self):
		source = ITEMS.read_text()
		self.assertNotIn("/app/", source)
		self.assertNotIn("table-striped", source)
		self.assertNotIn("btn-success", source)
		self.assertIn("<ListToolbar", source)
		self.assertIn("<SkeletonRows", source)

	def test_items_page_wires_the_category_filter_to_the_manage_categories_link(self):
		source = ITEMS.read_text()
		self.assertIn("itemGroupOptions", source)
		self.assertIn("include_descendants", source)
		self.assertIn('to="/inventory/categories"', source)

	def test_delete_confirmation_uses_body_not_message(self):
		"""`useConfirm` renders `body`; passing `message` silently drops the text.

		Mirrors the regression class documented in the Tender CRM contract test —
		we are not re-introducing the bug the Accounts.vue delete dialog had.
		"""
		source = ITEM_GROUPS.read_text()
		confirm_call = source.split("await confirm({", 1)[1].split("});", 1)[0]
		self.assertIn("body:", confirm_call)
		self.assertNotIn("message:", confirm_call)

	@staticmethod
	def _catalog(language):
		with (TRANSLATIONS / f"{language}.csv").open(newline="", encoding="utf-8") as handle:
			return {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}

	def test_every_string_the_pages_render_has_a_translated_row_in_every_catalog(self):
		"""Derives i18n keys from the new ItemGroups.vue page (every `t()` call in
		that file belongs to this feature) plus the hand-picked subset this
		feature added to Items.vue, so a new `t("…")` in either cannot silently
		fall through to English.
		"""
		rendered = set(re.findall(r"""\bt\(\s*["']([^"']+)["']""", ITEM_GROUPS.read_text()))
		rendered |= set(ITEMS_CATEGORY_KEYS)
		self.assertIn("Item categories", rendered, "the extraction itself must still find keys")
		self.assertIn("New category", rendered)
		for language in LANGUAGES:
			catalog = self._catalog(language)
			missing = sorted(rendered - set(catalog))
			self.assertEqual(missing, [], f"{language}: no catalogue row for {missing}")
			untranslated = sorted(key for key in rendered if not catalog.get(key, "").strip())
			self.assertEqual(untranslated, [], f"{language}: empty translation for {untranslated}")

	def test_item_group_endpoints_enforce_the_module_access_gate(self):
		source = INVENTORY_API.read_text()
		for name in ITEM_GROUP_ENDPOINTS:
			match = re.search(rf"\ndef {name}\(.*?\n(?=\ndef |\Z)", source, re.DOTALL)
			self.assertIsNotNone(match, f"could not locate def {name}(...) in inventory.py")
			body = match.group(0)
			self.assertIn(
				"_assert_inventory_access(company)",
				body,
				f"{name} must call _assert_inventory_access(company)",
			)

	def test_update_item_group_renames_without_merging(self):
		source = INVENTORY_API.read_text()
		self.assertIn('frappe.rename_doc("Item Group"', source)
		rename_call = source.split('frappe.rename_doc("Item Group"', 1)[1].split(")", 1)[0]
		self.assertIn("merge=False", rename_call)
