"""A language you can pick must be a language the server will store.

`update_language` (`api/organization.py`) is the only endpoint the pickers write
through — Sidebar and Profile both go via `api/organization.js:updateLanguage`. It
validates against its own set and throws `Unsupported language: {0}` on a miss.

That set was `{"en", "ru", "uz", "uzc"}` while all three pickers offered Türkçe. So
picking Turkish threw, in every tenant, for as long as both lists existed — and the
comment above `SUPPORTED_LANGUAGES` in `www/stabler.py` had said the whole time that
the lists "birebir aynı olmalı". The instruction was there; the second copy drifted
anyway. Two hand-maintained copies of one list is the defect, not the missing entry.

So this pins the relationship rather than the contents. Adding a sixth language should
need no edit here; adding one to a picker without the server accepting it should fail.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ORG = (ROOT / "api/organization.py").read_text(encoding="utf-8")
WWW = (ROOT / "www/stabler.py").read_text(encoding="utf-8")
SIDEBAR = (ROOT / "public/js/components/Sidebar.vue").read_text(encoding="utf-8")
PROFILE = (ROOT / "public/js/pages/Profile.vue").read_text(encoding="utf-8")
ONBOARDING = (ROOT / "api/onboarding.py").read_text(encoding="utf-8")

PICKERS = (
	("Sidebar.vue", SIDEBAR, r"const LANGUAGES = \[(.*?)\];"),
	("Profile.vue", PROFILE, r"const LANGUAGES = \[(.*?)\];"),
	("onboarding.py", ONBOARDING, r"return \[\s*(\{\"value\".*?)\]"),
)


def _codes(source, pattern):
	block = re.search(pattern, source, re.S)
	if not block:
		return None
	return re.findall(r"""["']?(?:code|value)["']?\s*:\s*["'](\w+)["']""", block.group(1))


def _shell_languages():
	m = re.search(r"SUPPORTED_LANGUAGES\s*=\s*\((.*?)\)", WWW, re.S)
	return set(re.findall(r'"(\w+)"', m.group(1))) if m else None


def _gate_languages():
	"""What `update_language` will actually accept.

	Read from the gate, not from the shell. Comparing the pickers against
	`www/stabler.py` would have stayed green through the entire tr outage,
	because the shell list was right all along — it was the endpoint's copy
	that was missing tr. Handles both shapes: the literal set that shipped
	the bug, and the derived form that replaces it.
	"""
	m = re.search(r"_SUPPORTED_LANGUAGES\s*=\s*(.+)", ORG)
	if not m:
		return None
	rhs = m.group(1)
	if "SUPPORTED_LANGUAGES" in rhs.replace("_SUPPORTED_LANGUAGES", "", 1):
		return _shell_languages()
	return set(re.findall(r'"(\w+)"', rhs))


class LanguagePickerContract(unittest.TestCase):
	def test_every_offered_language_is_storable(self):
		gate = _gate_languages()
		self.assertIsNotNone(gate, "organization.py: kabul edilen dil kümesi çözülemedi")
		self.assertTrue(gate, "kabul edilen dil kümesi boş çözüldü")
		for name, source, pattern in PICKERS:
			codes = _codes(source, pattern)
			self.assertIsNotNone(codes, "%s: dil listesi bulunamadı" % name)
			self.assertTrue(codes, "%s: desen boş eşleşti" % name)
			missing = sorted(set(codes) - gate)
			self.assertFalse(
				missing,
				"%s şu dilleri sunuyor ama sunucu kabul etmiyor: %s" % (name, missing),
			)

	def test_the_endpoint_does_not_keep_a_second_copy_of_the_list(self):
		# The fix for the tr bug was not "add tr" — it was removing the copy that
		# could drift. A literal set of language codes reappearing in
		# organization.py means the same bug is one edit away from returning.
		gate = re.search(r"_SUPPORTED_LANGUAGES\s*=\s*(.+)", ORG)
		self.assertIsNotNone(gate, "organization.py: _SUPPORTED_LANGUAGES bulunamadı")
		rhs = gate.group(1)
		self.assertNotRegex(
			rhs,
			r"""["'](?:en|ru|tr|uz|uzc)["']""",
			"organization.py dil listesinin ikinci bir kopyasını tutuyor — "
			"www/stabler.py'deki SUPPORTED_LANGUAGES'ten türetilmeli",
		)
		self.assertIn(
			"SUPPORTED_LANGUAGES",
			rhs,
			"_SUPPORTED_LANGUAGES kabuktaki listeden türetilmeli",
		)
