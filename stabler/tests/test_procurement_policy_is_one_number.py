"""The procurement policy is one number, in one place.

WHY this matters, and why a source-grep alone would not encode it: the same
threshold is reported to the user by four different subsystems — the desk's
daily work plan, the CRM board badge, the sourcing workspace meter, and the
award gate that actually refuses a decision. A sourcing user reads "collect 5"
on the desk and is refused at the award for having 5. That is not a cosmetic
inconsistency; it is the system telling someone to do the wrong amount of work
and then punishing them for doing it.

The canonical numbers used to live on the `Tender Sourcing Decision` doctype,
whose docstring claimed they were "named here so the exception rule and the
badge can never drift apart". They had drifted apart anyway, in twenty places,
because that module imports frappe and the pure derivation engines
(`_desk_rules`) therefore cannot read it at all. The home has to be a module
everybody can import — which means a frappe-free one.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from stabler.api import _desk_rules, _procurement_policy

_API = Path(__file__).resolve().parent.parent / "api"
_DOCTYPE = (
	Path(__file__).resolve().parent.parent
	/ "stabler"
	/ "doctype"
	/ "tender_sourcing_decision"
	/ "tender_sourcing_decision.py"
)


class TestThePolicyHasOneHome(unittest.TestCase):
	def test_the_home_is_frappe_free(self):
		"""A home the pure modules cannot import is not a home.

		`_desk_rules` is in `.github/frappe-free-tests.txt` and runs under
		`make check` with no bench. If the constants module reaches for frappe,
		importing it from there takes the whole gate down.
		"""
		src = (_API / "_procurement_policy.py").read_text(encoding="utf-8")
		self.assertNotRegex(src, r"(?m)^\s*(import|from)\s+frappe")

	def test_the_doctype_borrows_the_numbers_rather_than_restating_them(self):
		"""`sourcing.py` imports MIN_QUOTATIONS from the doctype, so the name has
		to keep working there — but as a re-export, not a second definition."""
		src = _DOCTYPE.read_text(encoding="utf-8")
		self.assertTrue("_procurement_policy import" in src, "the doctype defines its own copy")
		self.assertNotRegex(src, r"(?m)^MIN_QUOTATIONS\s*=\s*\d")
		self.assertNotRegex(src, r"(?m)^MIN_COUNTRIES\s*=\s*\d")


class TestTheDeskReportsThePolicyItIsGiven(unittest.TestCase):
	"""The behavioural half. Everything else here reads source; this one moves
	the number and checks the desk moved with it."""

	def _plan_for(self, sq_count: int) -> list[dict]:
		facts = {
			"lots": [
				{
					"deal": "CRM-DEAL-X",
					"bid_deadline": "2026-09-30",
					"label": "Lot X",
					"stage": "sourcing",
					"sq_count": sq_count,
					"assigned_to": "buyer@x.uz",
				}
			]
		}
		return _desk_rules.build_plan(facts, "2026-08-31")["items"]

	def _policy_gap(self, sq_count: int):
		return [i for i in self._plan_for(sq_count) if i["kind"] == "policy_gap"]

	def test_a_lot_one_short_of_the_policy_is_flagged(self):
		with _patched(_procurement_policy, MIN_QUOTATIONS=6):
			self.assertTrue(self._policy_gap(5), "5 quotes under a 6-quote policy is a gap")

	def test_a_lot_that_meets_the_policy_is_not_flagged(self):
		with _patched(_procurement_policy, MIN_QUOTATIONS=6):
			self.assertFalse(self._policy_gap(6), "6 quotes under a 6-quote policy is not a gap")

	def test_the_number_the_user_is_told_to_collect_is_the_number_enforced(self):
		"""The failure this whole file exists for: the desk saying "minimum 5"
		while the award gate demands 6."""
		with _patched(_procurement_policy, MIN_QUOTATIONS=6):
			(item,) = self._policy_gap(2)
			# Every number in the sentence, not just the first one. A half-done
			# fix reads "2/6 quotes collected (minimum 5 required)" — which
			# contains a 6 and no "/5", and so satisfied the weaker assertion
			# this replaces while telling the user two different thresholds in
			# one sentence.
			self.assertEqual(
				re.findall(r"\d+", item["why"]),
				["2", "6", "6"],
				f"a stale threshold survives in: {item['why']!r}",
			)


class TestNoSubsystemRestatesTheThreshold(unittest.TestCase):
	"""Source guard for the frappe-bound reporters, which `make check` cannot
	execute. Every policy comparison must name the constant, never an integer."""

	#: (file, regexes whose every match is a policy site that must not carry a
	#: bare number). Kept as patterns rather than line numbers so the guard
	#: survives the code moving.
	SITES = (
		(
			"tender.py",
			(
				r"sq_counts\.get\([^)]*\)\s*[<>]=?\s*\d",
				r"country_counts\.get\([^)]*\)\s*[<>]=?\s*\d",
				r"len\(countries[^)]*\)\s*[<>]=?\s*\d",
			),
		),
		("purchasing.py", (r"len\(rows\)\s*[<>]=?\s*\d", r"len\(countries\)\s*[<>]=?\s*\d")),
		("_desk_rules.py", (r"sq_count\s*[<>]=?\s*\d", r"/\d+ quotes", r"minimum \d+ required")),
		("tender_master.py", (r"(?m)^_MIN_SUPPLIER_BIDS\s*=\s*\d", r"sq_count\s*[<>]=?\s*\d")),
	)

	def test_no_policy_comparison_spells_a_number(self):
		for filename, patterns in self.SITES:
			src = (_API / filename).read_text(encoding="utf-8")
			for pattern in patterns:
				with self.subTest(file=filename, pattern=pattern):
					self.assertEqual(
						re.findall(pattern, src),
						[],
						f"{filename} restates the procurement threshold instead of "
						f"importing it from _procurement_policy",
					)

	def test_every_reporter_imports_the_constant(self):
		"""Guards the other direction: a file could satisfy the test above by
		deleting its policy check entirely."""
		for filename, _ in self.SITES:
			with self.subTest(file=filename):
				src = (_API / filename).read_text(encoding="utf-8")
				self.assertTrue("_procurement_policy" in src, f"{filename} no longer reads the policy at all")


class _patched:
	"""Minimal attribute patcher — the frappe-free suite has no mock helper."""

	def __init__(self, module, **values):
		self.module, self.values, self.previous = module, values, {}

	def __enter__(self):
		for key, value in self.values.items():
			self.previous[key] = getattr(self.module, key)
			setattr(self.module, key, value)
		return self.module

	def __exit__(self, *exc):
		for key, value in self.previous.items():
			setattr(self.module, key, value)
		return False


if __name__ == "__main__":
	unittest.main()
