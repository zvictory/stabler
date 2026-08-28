"""`uzc` is no longer offered, and its catalogue is deliberately still here.

Decided 2026-08-28 by Zafar: stop offering Uzbek Cyrillic to new users, keep the
5 219 translated rows. That is a half-retirement, and half-retired things are what
this repository keeps getting hurt by — a role that granted nothing but looked like
it did, an ADR marked invalid in one file and live in another, a UAT document that
outranked the code it described. Each was rediscovered later as a defect and cost a
session to re-measure.

So the state is pinned from both sides. Removing `uzc` from a picker is the decision;
deleting `uzc.csv`, or dropping `uzc` from `SUPPORTED_LANGUAGES`, is NOT — an account
that still carries the setting must keep rendering in Cyrillic, and the catalogue must
survive so the decision is reversible by re-adding three list entries.

There are three pickers and they drift: two Vue lists and one Python endpoint. A test
that only knew about the ones present in 2026-08 would pass while a fourth shipped
`uzc` again, so this reads the source rather than a hard-coded list of files.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SIDEBAR = (ROOT / "public/js/components/Sidebar.vue").read_text(encoding="utf-8")
PROFILE = (ROOT / "public/js/pages/Profile.vue").read_text(encoding="utf-8")
ONBOARDING = (ROOT / "api/onboarding.py").read_text(encoding="utf-8")
WWW = (ROOT / "www/stabler.py").read_text(encoding="utf-8")


def _picker_codes(source, pattern):
	"""The language codes a picker literal offers, in source order."""
	block = re.search(pattern, source, re.S)
	if not block:
		return None
	return re.findall(r"""["']?(?:code|value)["']?\s*:\s*["'](\w+)["']""", block.group(1))


class UzcRetiredFromPickers(unittest.TestCase):
	def test_no_picker_offers_uzc(self):
		# The three surfaces a person can pick a language from. If a fourth is
		# added and ships uzc, the sweep below is what catches it.
		for name, source, pattern in (
			("Sidebar.vue", SIDEBAR, r"const LANGUAGES = \[(.*?)\];"),
			("Profile.vue", PROFILE, r"const LANGUAGES = \[(.*?)\];"),
			("onboarding.py", ONBOARDING, r"return \[\s*(\{\"value\".*?)\]"),
		):
			codes = _picker_codes(source, pattern)
			self.assertIsNotNone(codes, "%s: dil listesi bulunamadı" % name)
			self.assertNotIn("uzc", codes, "%s hâlâ uzc sunuyor" % name)
			# Guard the guard: a pattern that silently matched nothing would
			# pass the assertion above for the wrong reason.
			self.assertIn("uz", codes, "%s: desen tutmuyor olabilir" % name)
			self.assertIn("en", codes, "%s: desen tutmuyor olabilir" % name)

	def test_the_catalogue_is_kept(self):
		# The other half of the decision. Deleting the CSV would strand any
		# account still set to uzc on untranslated English, and would throw away
		# 5 219 finished rows to save nothing.
		csv = ROOT / "translations/uzc.csv"
		self.assertTrue(csv.exists(), "uzc.csv silinmemeli — karar katalogu korumaktı")
		self.assertGreater(
			len(csv.read_text(encoding="utf-8").splitlines()),
			5000,
			"uzc.csv boşaltılmış görünüyor",
		)

	def test_uzc_still_renders_for_an_account_that_has_it(self):
		# `SUPPORTED_LANGUAGES` gates which catalogue the SPA will load. Dropping
		# uzc from it is the one edit that turns "no longer offered" into "breaks
		# the people who already chose it".
		langs = re.search(r"SUPPORTED_LANGUAGES\s*=\s*\((.*?)\)", WWW, re.S)
		self.assertIsNotNone(langs, "SUPPORTED_LANGUAGES bulunamadı")
		self.assertIn("uzc", langs.group(1), "uzc render edilebilir kalmalı")
