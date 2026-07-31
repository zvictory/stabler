from __future__ import annotations

import csv
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

OPERATIONS_DESK_KEYS = (
    "Operations desk",
    "Daily work plan",
    "Decision box",
    "Due today",
    "Overdue",
    "Awaiting my approval",
    "Waiting others",
    "7-day schedule",
    "Team load",
    "No tasks scheduled for today",
    "No pending decisions",
)

class TestTenderDeskTranslations(unittest.TestCase):
    def test_operations_desk_keys_in_all_locales(self):
        for language in ("en", "ru", "uz", "uzc", "tr"):
            with self.subTest(language=language):
                csv_path = _ROOT / "translations" / f"{language}.csv"
                with csv_path.open(encoding="utf-8", newline="") as source:
                    translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
                missing = sorted(key for key in OPERATIONS_DESK_KEYS if not translations.get(key, "").strip())
                self.assertEqual(missing, [], f"{language}.csv is missing Operations Desk translations: {missing}")

if __name__ == "__main__":
    unittest.main()
