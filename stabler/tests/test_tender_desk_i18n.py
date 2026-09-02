from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DESK = _ROOT / "public/js/pages/tender/OperationsDesk.vue"

# `t("...")` with a LITERAL argument -- which is the only kind that can be
# translated at all, because harvesting scans the source text. `(?<![\w.])`
# keeps identifiers that merely end in `t` (formatDate, parseInt, .at) out.
_LITERAL_KEY = re.compile(r'(?<![\w.])t\("([^"]+)"')


def _operations_desk_keys() -> tuple[str, ...]:
	"""Every literal `t()` key the Operations Desk renders, read off the screen.

	This was a hand-written tuple of 11 strings. The screen carries 84, and two
	of the eleven ("Due today", "7-day schedule") had not been rendered for some
	time -- so the test that exists to catch a missing catalogue entry for this
	screen was checking a seventh of it, and drifting further with every change.
	A list that has to be maintained by hand to stay honest is a list that stops
	being honest between the change and the next reader.

	The screen's day names are NOT here: they are `t(DOW[dow])`, a computed key,
	and this regex deliberately cannot see them -- neither can the harvester, so
	a computed key is a translation gap by construction rather than one this test
	could close.
	"""
	return tuple(sorted(set(_LITERAL_KEY.findall(_DESK.read_text(encoding="utf-8")))))


OPERATIONS_DESK_KEYS = _operations_desk_keys()


class TestTenderDeskTranslations(unittest.TestCase):
	def test_the_key_list_is_read_off_the_screen(self):
		# WHAT WOULD MAKE THIS FAIL: the derivation going blind -- a renamed file, a
		# regex that stops matching, an import that quietly returns (). The loop
		# below would then pass by not running, reporting five green locales while
		# checking nothing, which is exactly the failure the hand-written tuple had
		# in slow motion.
		self.assertGreater(len(OPERATIONS_DESK_KEYS), 50, "the desk's key list came back nearly empty")
		for sentinel in ("Daily work plan", "Decision box", "Team load"):
			self.assertIn(sentinel, OPERATIONS_DESK_KEYS, f"{sentinel} is no longer derived")

	def test_operations_desk_keys_in_all_locales(self):
		for language in ("en", "ru", "uz", "uzc", "tr"):
			with self.subTest(language=language):
				csv_path = _ROOT / "translations" / f"{language}.csv"
				with csv_path.open(encoding="utf-8", newline="") as source:
					translations = {row[0]: row[1] for row in csv.reader(source) if len(row) >= 2}
				missing = sorted(key for key in OPERATIONS_DESK_KEYS if not translations.get(key, "").strip())
				self.assertEqual(
					missing, [], f"{language}.csv is missing Operations Desk translations: {missing}"
				)


if __name__ == "__main__":
	unittest.main()
