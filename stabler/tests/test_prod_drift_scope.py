"""D4: `make prod-drift` is the operator's only anchor, and it names its scope
in three places that can drift apart.

Prod is not a git repo and rsync runs without `--delete`, so a file that ever
landed there stays forever — a renamed or deleted `.vue` leaves its old copy
serving alongside the new one. `deploy_stabler.sh:312` tells the operator to run
`prod-drift` after every deploy, and until this test the check only looked at
`.py` and `.json`, so it answered "clean" for exactly that case.

The reason this needs a test rather than just a fix: the recipe hardcodes its
extension list THREE times — the `git ls-files` pathspecs, the `find -name`
predicates, and the success message the operator reads. Two of those decide the
answer and the third decides what the operator believes the answer covered. A
scope widened in one place and not the others is a check that quietly reports
less than it claims, which is the same failure D4 already caused once.

`.js` is deliberately out of scope, and that is asserted too. Prod carries build
output and locally gitignored js; `prod-drift` exits 1 on any extra, so pulling
those in would make the check noisily red every run and teach the operator to
skip the one thing they are told to run after every deploy. A test the team
learns to ignore is worse than a documented gap.

  PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_prod_drift_scope -v
"""

from __future__ import annotations

import pathlib
import re
import unittest

MAKEFILE = pathlib.Path(__file__).resolve().parents[2] / "Makefile"


def _recipe() -> str:
	"""The `prod-drift` target's recipe, up to the next target."""
	text = MAKEFILE.read_text(encoding="utf-8")
	start = text.index("\nprod-drift:")
	rest = text[start + 1 :]
	end = re.search(r"\n(?=[A-Za-z0-9_.-]+:)", rest)
	return rest[: end.start()] if end else rest


class TheThreeCopiesOfTheScopeAgree(unittest.TestCase):
	def setUp(self):
		recipe = _recipe()
		self.local = set(re.findall(r"'stabler/\*(\.[a-z]+)'", recipe))
		self.prod = set(re.findall(r"-name '\*(\.[a-z]+)'", recipe))
		message = re.search(r"no untracked (\S+) under", recipe)
		self.assertIsNotNone(message, "the success message no longer names a scope")
		self.reported = set(message.group(1).split("/"))

	def test_the_local_side_and_the_prod_side_look_for_the_same_extensions(self):
		"""`comm -13` between two differently-scoped lists reports everything the
		wider side has and the narrower one cannot, which reads as drift that is
		not there — or hides drift that is."""
		self.assertEqual(self.local, self.prod)

	def test_the_message_reports_the_scope_that_was_actually_searched(self):
		"""The operator reads "clean — no untracked X" and stops looking. If X is
		narrower than what ran, they are told less than was checked; if it is
		wider, they are told the check covered files it never opened."""
		self.assertEqual(self.reported, self.local)


class WhatIsInScopeAndWhatIsNot(unittest.TestCase):
	def setUp(self):
		self.recipe = _recipe()
		self.extensions = set(re.findall(r"'stabler/\*(\.[a-z]+)'", self.recipe))

	def test_vue_is_in_scope(self):
		"""The finding: an orphaned `.vue` on prod was invisible to the only
		check that looks for orphans."""
		self.assertIn(".vue", self.extensions)

	def test_python_and_json_stay_in_scope(self):
		"""A doctype IS a .json file — a drift check that reads only .py cannot
		see a stale doctype, which is the more dangerous of the two."""
		self.assertIn(".py", self.extensions)
		self.assertIn(".json", self.extensions)

	def test_js_is_out_of_scope(self):
		self.assertNotIn(".js", self.extensions)

	def test_the_build_output_stays_excluded(self):
		"""`stabler/public/dist/` is gitignored by design, so every file in it
		would report as drift — the noise that would swamp a real finding."""
		self.assertIn("stabler/public/dist/", self.recipe)


class TheEmptyListIsNotAResult(unittest.TestCase):
	"""A dropped ssh returns nothing, and nothing compares clean against
	anything. The recipe already refuses to read that as a pass; this pins it,
	because it is the one failure mode that looks exactly like success."""

	def test_an_empty_prod_listing_aborts_instead_of_reporting_clean(self):
		self.assertIn("ABORT", _recipe())


if __name__ == "__main__":
	unittest.main()
