"""What an RFQ invitation alone can reach, counted before the answers arrive.

Frappe-free and site-free on purpose, the same shape as `_landed.py`, so the
counting rule can be tested without a bench.

The procurement rule -- at least N quotations from at least M countries -- is
enforced on the way OUT of sourcing: `Tender Sourcing Decision.validate` refuses
a short quote set unless a written exception is filed. Nothing looks at the way
IN. Invite six vendors from one country and the two-country half is already lost
before a single answer arrives; today that is discovered at the award, when
re-running the RFQs costs the submission deadline.

This module answers the narrower question the invitation can actually settle:
given who was asked, what can come back. It is NOT a hard ceiling -- a quotation
from a vendor nobody invited can still be attached to the lot later
(`attach_quotation_to_deal`) -- so the wording it feeds must say "this invitation
alone", never "impossible".

The thresholds are arguments. They already exist in four spellings elsewhere
(`MIN_QUOTATIONS`/`MIN_COUNTRIES` on the decision doctype, `_MIN_SUPPLIER_BIDS`
in tender_master, an inline `< 5` in the funnel, `has_min_5` in purchasing);
this module declines to become the fifth.
"""

from __future__ import annotations


def _country(row: dict) -> str:
	"""The country on an invitation row, or "" when there isn't one.

	Stripped, unlike the receive side's plain truthiness test -- see the note in
	`test_sourcing_reach.py`. A whitespace-only country is a broken Supplier
	record, and naming it is this module's job.
	"""
	return str(row.get("country") or "").strip()


def reach_of(invited: list[dict], min_suppliers: int, min_countries: int) -> dict:
	"""Count what one lot's invitations reach.

	`invited` is one row per (RFQ, supplier) pair, so the same vendor appears
	once per round it was asked in. Vendors are counted, not rows: asking ACME
	twice is one vendor asked, and a count that says two is the kind of number
	that flatters the officer into stopping early.

	Returns `suppliers`, `countries`, `unknown_country` (vendors with no country
	on file, which lower the reach silently and are the one gap still fixable
	before sending), and the two `meets_*` verdicts.

	No `country_ceiling` key: it would be `countries` under a second name. The
	ceiling is what the number MEANS, and that belongs in the sentence shown to
	the officer, not in a duplicated integer that can drift from its twin.
	"""
	countries_by_supplier: dict[str, set[str]] = {}
	for row in invited or []:
		supplier = str(row.get("supplier") or "").strip()
		if not supplier:
			continue
		known = countries_by_supplier.setdefault(supplier, set())
		country = _country(row)
		if country:
			known.add(country)

	countries = {c for known in countries_by_supplier.values() for c in known}
	unknown = sum(1 for known in countries_by_supplier.values() if not known)

	return {
		"suppliers": len(countries_by_supplier),
		"countries": len(countries),
		"unknown_country": unknown,
		"meets_suppliers": len(countries_by_supplier) >= min_suppliers,
		"meets_countries": len(countries) >= min_countries,
	}
