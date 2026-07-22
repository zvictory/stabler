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
)
_LITERAL_T = re.compile(r"\bt\(\s*(['\"])(?P<source>(?:\\.|(?!\1).)*?)\1")


class TestTenderDashboardTranslations(unittest.TestCase):
	def test_every_dashboard_copy_key_has_a_nonempty_translation(self):
		keys = {
			match.group("source").replace("\\'", "'").replace('\\"', '"')
			for path in _SOURCES
			for match in _LITERAL_T.finditer(path.read_text(encoding="utf-8"))
		}
		for language in ("en", "ru", "uz", "uzc"):
			with self.subTest(language=language):
				with (_ROOT / "translations" / f"{language}.csv").open(encoding="utf-8", newline="") as source:
					translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
				missing = sorted(key for key in keys if not translations.get(key, "").strip())
				self.assertEqual(missing, [], f"{language} has untranslated tender dashboard copy")


if __name__ == "__main__":
	unittest.main()
