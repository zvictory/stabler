from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = (
	_ROOT / "public/js/pages/Dashboard.vue",
	_ROOT / "public/js/pages/sales/SalesOrderBoard.vue",
	_ROOT / "public/js/pages/tender/DirectorBoard.vue",
	_ROOT / "public/js/pages/tender/MyTenders.vue",
	_ROOT / "public/js/pages/tender/DeclarantQueue.vue",
	_ROOT / "public/js/pages/tender/LogistBoard.vue",
	_ROOT / "public/js/pages/tender/TenderTrendChart.vue",
	_ROOT / "public/js/pages/tender/TenderExecutionFlow.vue",
	_ROOT / "public/js/pages/tender/TenderDocumentChain.vue",
	_ROOT / "public/js/pages/tender/TenderPortfolioPreview.vue",
	_ROOT / "public/js/components/Sidebar.vue",
	_ROOT / "public/js/pages/tender/TenderNav.vue",
	_ROOT / "public/js/pages/tender/TenderWorkspaceTabs.vue",
	_ROOT / "public/js/pages/tender/PoControlBoard.vue",
)
_LITERAL_T = re.compile(r"\bt\(\s*(['\"])(?P<source>(?:\\.|(?!\1).)*?)\1")
REQUIRED_KEYS = (
	"Control Tower",
	"Vendor & PO",
	"Three-month tender conversion",
	"Portfolio value",
	"Weighted margin",
	"Execution flow",
	"Purchase invoices",
	"Sales invoices",
	"Selected vendor",
	"Won",
	"SO",
	"PO",
	"PR",
	"PI",
	"SI",
	"DN",
	"PO receipt",
	"PO billing",
	"SO delivery",
	"SO billing",
)
COMPONENT_LABEL_KEYS = {
	"TenderExecutionFlow.vue": ("Won", "SO", "PO", "PR", "PI", "SI", "DN"),
	"TenderPortfolioPreview.vue": ("PO receipt", "PO billing", "SO delivery", "SO billing"),
}


class TestTenderDashboardTranslations(unittest.TestCase):
	def test_control_tower_keys_have_a_nonempty_translation_in_every_locale(self):
		for language in ("en", "ru", "uz", "uzc", "tr"):
			with self.subTest(language=language):
				with (_ROOT / "translations" / f"{language}.csv").open(encoding="utf-8", newline="") as source:
					translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
				missing = sorted(key for key in REQUIRED_KEYS if not translations.get(key, "").strip())
				self.assertEqual(missing, [], f"{language} has untranslated Control Tower copy")

	def test_every_dashboard_copy_key_has_a_nonempty_translation(self):
		keys = {
			match.group("source").replace("\\'", "'").replace('\\"', '"')
			for path in _SOURCES
			for match in _LITERAL_T.finditer(path.read_text(encoding="utf-8"))
		}
		for language in ("en", "ru", "uz", "uzc", "tr"):
			with self.subTest(language=language):
				with (_ROOT / "translations" / f"{language}.csv").open(encoding="utf-8", newline="") as source:
					translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
				missing = sorted(key for key in keys if not translations.get(key, "").strip())
				self.assertEqual(missing, [], f"{language} has untranslated tender dashboard copy")

	def test_control_tower_component_labels_are_translation_calls(self):
		for filename, keys in COMPONENT_LABEL_KEYS.items():
			with self.subTest(component=filename):
				content = (_ROOT / "public/js/pages/tender" / filename).read_text(encoding="utf-8")
				for key in keys:
					with self.subTest(key=key):
						self.assertRegex(content, rf"t\(\s*['\"]{re.escape(key)}['\"]\s*\)")


if __name__ == "__main__":
	unittest.main()
