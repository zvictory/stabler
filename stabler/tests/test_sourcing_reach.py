"""Pure unit tests for the RFQ send-side reach counter (_sourcing_reach.py).

PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_sourcing_reach -v

WHY THIS EXISTS. The 5-quotations/2-countries procurement rule is checked on the
way OUT of sourcing -- `Tender Sourcing Decision.validate` throws when the quote
set is short. Nothing checks it on the way IN. A sourcing officer can invite six
vendors from one country, collect six answers, and only discover at the award
that the set can never satisfy the rule, at the point where re-running the RFQs
costs the deadline.

The invited set is not a hard ceiling -- `attach_quotation_to_deal` can pull in a
quotation from a vendor nobody invited -- so this counter reports what the
invitation ALONE can reach, and the wording it feeds must say exactly that.
"""

from __future__ import annotations

import unittest

from stabler.api._sourcing_reach import reach_of

MIN_S = 5
MIN_C = 2


class TestReachCountsVendorsNotRows(unittest.TestCase):
	def test_a_vendor_invited_twice_counts_once(self):
		"""Two RFQ rounds to the same vendor is one vendor asked, not two.

		`_rfq_supplier_counts` counts child rows because it answers a different
		question -- how big was THIS RFQ. Reusing it per lot would report six
		vendors where three were asked twice, and the number that flatters is
		the number nobody checks."""
		invited = [
			{"supplier": "ACME", "country": "Uzbekistan"},
			{"supplier": "ACME", "country": "Uzbekistan"},
			{"supplier": "BETA", "country": "Turkey"},
		]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertEqual(out["suppliers"], 2)

	def test_an_empty_invitation_reaches_nothing(self):
		out = reach_of([], MIN_S, MIN_C)
		self.assertEqual(out["suppliers"], 0)
		self.assertEqual(out["countries"], 0)
		self.assertEqual(out["unknown_country"], 0)
		self.assertFalse(out["meets_suppliers"])
		self.assertFalse(out["meets_countries"])


class TestCountryCountMirrorsTheReceiveSide(unittest.TestCase):
	"""The receive side counts countries as `{r["country"] for r in rows if r["country"]}`
	(purchasing.py, tender_quotations). If this half counted blanks as a country,
	the invite badge would promise two countries and the award would refuse over
	one -- the same screen contradicting itself, which is the failure this repo
	has already paid for once in landed-cost ranking.

	One deliberate difference, on malformed data only. `"   "` is truthy, so the
	receive side counts a whitespace-only country AS a country; this half strips
	first and calls it unknown. On any real Supplier record the two agree. On a
	broken one they differ, and the stricter answer is the useful one here --
	surfacing the record that needs fixing is what this counter is for, and it is
	the conservative direction: it nags for another country rather than promising
	one that is not there. The receive-side truthiness is a separate finding, not
	something this module silently copies."""

	def test_a_blank_country_is_not_a_country(self):
		invited = [
			{"supplier": "ACME", "country": "Uzbekistan"},
			{"supplier": "BETA", "country": ""},
		]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertEqual(out["countries"], 1)

	def test_a_missing_country_key_is_not_a_country(self):
		out = reach_of([{"supplier": "ACME"}], MIN_S, MIN_C)
		self.assertEqual(out["countries"], 0)

	def test_whitespace_is_not_a_country(self):
		"""A country of "  " passes a truthiness test on the receive side too,
		so both halves must agree it is blank. Asserted rather than assumed."""
		out = reach_of([{"supplier": "ACME", "country": "	"}], MIN_S, MIN_C)
		self.assertEqual(out["countries"], 0)
		self.assertEqual(out["unknown_country"], 1)


class TestVendorsWithNoCountryAreNamedNotHidden(unittest.TestCase):
	"""A vendor with no country on file silently lowers what the invitation can
	reach. Counted separately because it is the one gap the officer can still
	close before sending -- fix the Supplier record, not the RFQ."""

	def test_a_countryless_vendor_is_counted_apart(self):
		invited = [
			{"supplier": "ACME", "country": "Uzbekistan"},
			{"supplier": "BETA", "country": ""},
			{"supplier": "GAMMA", "country": None},
		]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertEqual(out["suppliers"], 3)
		self.assertEqual(out["countries"], 1)
		self.assertEqual(out["unknown_country"], 2)

	def test_the_same_countryless_vendor_is_not_counted_twice(self):
		invited = [
			{"supplier": "BETA", "country": ""},
			{"supplier": "BETA", "country": None},
		]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertEqual(out["unknown_country"], 1)

	def test_a_vendor_with_a_country_anywhere_is_not_unknown(self):
		"""The same vendor can arrive twice, once before its country was filled
		in and once after. One known country settles it -- otherwise the badge
		nags about a record somebody already fixed."""
		invited = [
			{"supplier": "ACME", "country": ""},
			{"supplier": "ACME", "country": "Turkey"},
		]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertEqual(out["unknown_country"], 0)
		self.assertEqual(out["countries"], 1)


class TestWhatTheInvitationAloneCanReach(unittest.TestCase):
	def test_one_country_cannot_reach_two_however_many_vendors(self):
		"""The whole point. Nine vendors, one country: every answer that comes
		back lands in the same country, so the invitation alone cannot satisfy
		the two-country half. This is knowable at send time and is today only
		discovered at the award."""
		invited = [{"supplier": f"V{i}", "country": "Uzbekistan"} for i in range(9)]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertTrue(out["meets_suppliers"])
		self.assertFalse(out["meets_countries"])

	def test_enough_countries_but_too_few_vendors(self):
		invited = [
			{"supplier": "ACME", "country": "Uzbekistan"},
			{"supplier": "BETA", "country": "Turkey"},
		]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertFalse(out["meets_suppliers"])
		self.assertTrue(out["meets_countries"])

	def test_a_reaching_invitation_meets_both(self):
		invited = [
			{"supplier": "V1", "country": "Uzbekistan"},
			{"supplier": "V2", "country": "Uzbekistan"},
			{"supplier": "V3", "country": "Uzbekistan"},
			{"supplier": "V4", "country": "Turkey"},
			{"supplier": "V5", "country": "Turkey"},
		]
		out = reach_of(invited, MIN_S, MIN_C)
		self.assertTrue(out["meets_suppliers"])
		self.assertTrue(out["meets_countries"])


class TestTheThresholdsAreNotBakedIn(unittest.TestCase):
	"""The 5 and the 2 live on `Tender Sourcing Decision` (MIN_QUOTATIONS,
	MIN_COUNTRIES), whose docstring claims they are named once so the exception
	rule and the badge cannot drift. They are in fact spelled in four places
	already; this module refuses to be the fifth and takes them as arguments."""

	def test_the_module_defines_no_threshold_of_its_own(self):
		import stabler.api._sourcing_reach as mod

		baked = [n for n in dir(mod) if not n.startswith("__") and isinstance(getattr(mod, n), int)]
		self.assertEqual(baked, [], f"module baked in a threshold: {baked}")

	def test_a_different_threshold_is_honoured(self):
		invited = [{"supplier": "ACME", "country": "Uzbekistan"}]
		self.assertTrue(reach_of(invited, 1, 1)["meets_suppliers"])
		self.assertFalse(reach_of(invited, 2, 1)["meets_suppliers"])


if __name__ == "__main__":
	unittest.main()
