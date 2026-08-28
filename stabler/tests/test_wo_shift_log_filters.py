"""The shift log's filters: what narrows a Work Order list, and what must not.

`WorkOrders.vue` is the screen a shift lead reads all day, and until 2026-08-28
it offered exactly two ways to narrow it: a text search and a status dropdown.
Measured on anjan the same day, that is not enough to find anything: 3 795 open
orders spanning 2026-03-10 to 2026-08-28, so "In Process" alone still returns
more rows than a screen holds, and the row you want is a date away.

The design package calls for three more — date, line, operator — and all three
are real dimensions in the data rather than wishes:

    line      `wip_warehouse`. anjan runs five named sections
              (`WIP.1-Bo'lim` … `WIP.5-Bo'lim`, 557 orders between them) beside
              a generic `Work In Progress - A` pool. There are **0 Workstation
              records**, so the warehouse is the only line dimension that exists;
              a filter keyed on Workstation would have been a filter on nothing.
    operator  `operator` / `packaging_operator`. Both, never just the first:
              the packer and the pourer work the same order, and a filter that
              knew only one role would hide half of a person's own day.
    date      `planned_start_date`, as a range.

Why the where-clause is built in a pure helper and tested here rather than
against a bench: the risk in a filter is not that SQL fails, it is that a filter
silently matches nothing or — far worse — that an added filter drops the tenant
guard or the operator's own-rows guard and widens the list. Those are questions
about which conditions are present, and they are answerable without a database.
`test_wo_role_scoping_integration` keeps proving the query runs against real
columns.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest \
        stabler.tests.test_wo_shift_log_filters -v
"""

from __future__ import annotations

import unittest

from stabler.api._wo_filters import build_work_order_filters


def _where(**kwargs) -> str:
	conds, _params = build_work_order_filters(company="ACME", **kwargs)
	return " AND ".join(conds)


def _params(**kwargs) -> dict:
	_conds, params = build_work_order_filters(company="ACME", **kwargs)
	return params


class TestTheGuardsSurviveEveryFilter(unittest.TestCase):
	"""The filters are the new code; the guards are what they could break.

	A where-clause built by string joining is exactly where a tenant boundary
	goes missing without anything failing — the screen still renders, it just
	renders somebody else's factory.
	"""

	def test_the_company_condition_is_always_present(self):
		for case in (
			{},
			{"status": "In Process"},
			{"line": "WIP.1-Bo'lim - A"},
			{"operator": "qwerty03@mail.com"},
			{"from_date": "2026-08-01", "to_date": "2026-08-28"},
		):
			with self.subTest(**case):
				self.assertIn("company = %(company)s", _where(**case))

	def test_an_operators_own_rows_condition_survives_a_line_filter(self):
		"""An operator sees only their own orders. Adding a line filter must
		narrow that set, never replace it: the two conditions are ANDed, so
		filtering by line cannot become a way to read the whole floor."""
		where = _where(assignee_user="qwerty03@mail.com", line="WIP.1-Bo'lim - A")
		self.assertIn("`operator` = %(assignee)s", where)
		self.assertIn("wip_warehouse = %(line)s", where)
		self.assertNotIn(" OR wip_warehouse", where, "hat filtresi kendi rows guard'ını OR'la deliyor")

	def test_a_manager_gets_no_assignee_condition(self):
		self.assertNotIn("%(assignee)s", _where())


class TestEachFilterNarrowsOnTheColumnItClaims(unittest.TestCase):
	def test_the_line_filter_reads_the_wip_warehouse(self):
		"""There are 0 Workstation rows on anjan; `wip_warehouse` is the only
		line dimension the data actually has."""
		self.assertIn("wip_warehouse = %(line)s", _where(line="WIP.4-Bo'lim - A"))
		self.assertEqual(_params(line="WIP.4-Bo'lim - A")["line"], "WIP.4-Bo'lim - A")

	def test_the_operator_filter_matches_either_role(self):
		"""The packer and the pourer work the same order. A filter that read
		only `operator` would tell a packaging operator they had no work."""
		where = _where(operator="qwerty03@mail.com")
		self.assertIn("`operator` = %(operator)s", where)
		self.assertIn("`packaging_operator` = %(operator)s", where)
		self.assertIn(" OR ", where, "iki rol AND'lenirse hiçbir kayıt eşleşmez")

	def test_the_date_range_is_inclusive_on_both_ends(self):
		"""A shift lead types one day in both boxes to mean "that day". An
		exclusive end silently returns nothing and reads as "no orders"."""
		where = _where(from_date="2026-08-28", to_date="2026-08-28")
		self.assertIn("planned_start_date >= %(from_date)s", where)
		self.assertIn("planned_start_date < %(to_date_end)s", where)
		self.assertEqual(_params(to_date="2026-08-28")["to_date_end"], "2026-08-29")

	def test_either_end_of_the_range_works_alone(self):
		self.assertIn("planned_start_date >= %(from_date)s", _where(from_date="2026-08-01"))
		self.assertNotIn("to_date_end", _where(from_date="2026-08-01"))
		self.assertIn("planned_start_date < %(to_date_end)s", _where(to_date="2026-08-31"))
		self.assertNotIn("from_date", _where(to_date="2026-08-31"))


class TestAnEmptyFilterIsNotAFilter(unittest.TestCase):
	"""The screen sends every box on every load. A blank box means "don't
	narrow", and a helper that turned `""` into `column = ''` would return an
	empty list the moment the page mounted."""

	def test_blank_values_add_no_condition(self):
		self.assertEqual(
			_where(line="", operator="", from_date="", to_date="", status=""), "company = %(company)s"
		)

	def test_none_values_add_no_condition(self):
		self.assertEqual(
			_where(line=None, operator=None, from_date=None, to_date=None, status=None),
			"company = %(company)s",
		)

	def test_an_unknown_status_is_ignored_rather_than_matched(self):
		"""Same rule the endpoint already applied: a status outside the known
		set narrows to nothing, so it is dropped instead."""
		self.assertNotIn("status", _where(status="Yarım"))


class TestTheSearchStillWorksBesideTheNewFilters(unittest.TestCase):
	def test_search_and_line_combine(self):
		where = _where(search="MUZ", line="WIP.2-Bo'lim - A")
		self.assertIn("name LIKE %(s)s", where)
		self.assertIn("wip_warehouse = %(line)s", where)

	def test_the_search_term_is_still_a_bound_parameter(self):
		"""Interpolating it would be an injection through a box on a shop-floor
		screen. Pinned because this helper is where someone would be tempted."""
		params = _params(search="MUZ")
		self.assertEqual(params["s"], "%MUZ%")
		self.assertNotIn("MUZ", _where(search="MUZ"))


if __name__ == "__main__":
	unittest.main()
