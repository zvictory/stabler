from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = (
	_ROOT / "public/js/pages/Dashboard.vue",
	_ROOT / "public/js/pages/tender/TenderFunnel.vue",
	_ROOT / "public/js/pages/sales/SalesOrderBoard.vue",
	_ROOT / "public/js/pages/tender/DirectorBoard.vue",
	_ROOT / "public/js/pages/tender/MyTenders.vue",
	_ROOT / "public/js/pages/tender/DeclarantQueue.vue",
	_ROOT / "public/js/pages/tender/LogistBoard.vue",
	_ROOT / "public/js/pages/tender/TenderDocumentChain.vue",
	_ROOT / "public/js/pages/tender/SourcingWorkspace.vue",
	_ROOT / "public/js/components/Sidebar.vue",
	_ROOT / "public/js/pages/tender/TenderNav.vue",
	_ROOT / "public/js/pages/tender/TenderWorkspaceTabs.vue",
	_ROOT / "public/js/pages/tender/PoControlBoard.vue",
)
_LITERAL_T = re.compile(r"\bt\(\s*(['\"])(?P<source>(?:\\.|(?!\1).)*?)\1")
REQUIRED_KEYS = (
	"Overview",
	"Current portfolio",
	"Last 90 days",
	"Active tenders",
	"Portfolio value",
	"Avg margin",
	"At risk",
	"Win rate",
	"Net remaining",
	"Sales funnel",
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
)
# NOT (2026-09-01): burada bir `COMPONENT_LABEL_KEYS` sözlüğü ve onu dolaşan
# `test_control_tower_component_labels_are_translation_calls` vardı. Sözlüğün TEK
# girdisi `TenderExecutionFlow.vue`'ydu; o dosya Aşama A §10.5 kararıyla silindi
# (hiçbir yerden import edilmiyordu, 0 çağrı).
#
# Girdiyi çıkarıp testi bırakmak sözlüğü boşaltırdı ve `for ... in .items()` sıfır
# kez dönerdi — test YEŞİL kalır, hiçbir şey doğrulamazdı. Konusu silinmiş bir
# testi sessizce yeşil bırakmak, silmekten daha pahalıdır. O yüzden ikisi de
# silindi ve bu not kaldı: kalıp geri gerekirse, canlı bir bileşenle yeniden
# yazılır.


class TestTenderDashboardTranslations(unittest.TestCase):
	def test_control_tower_keys_have_a_nonempty_translation_in_every_locale(self):
		for language in ("en", "ru", "uz", "uzc", "tr"):
			with self.subTest(language=language):
				with (_ROOT / "translations" / f"{language}.csv").open(
					encoding="utf-8", newline=""
				) as source:
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
				with (_ROOT / "translations" / f"{language}.csv").open(
					encoding="utf-8", newline=""
				) as source:
					translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
				missing = sorted(key for key in keys if not translations.get(key, "").strip())
				self.assertEqual(missing, [], f"{language} has untranslated tender dashboard copy")


if __name__ == "__main__":
	unittest.main()
