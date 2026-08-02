"""The director's chevron pipeline strip: pure maths + source contracts.

The strip answers one question the stage grid could not: *where is the pipeline
stuck right now, and can I see only those records without leaving the page.*
Two things make it honest, and both are guarded here — its counts come from the
same server pass as the rows it filters to, and its quote-set bar uses the whole
procurement rule rather than the half that is cheap to compute.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_pipeline_strip -v
"""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
FUNNEL_PY = _ROOT / "api" / "_funnel.py"
TENDER_PY = _ROOT / "api" / "tender.py"
FUNNEL_VUE = _ROOT / "public" / "js" / "pages" / "tender" / "TenderFunnel.vue"
BOARD_VUE = _ROOT / "public" / "js" / "pages" / "tender" / "DirectorBoard.vue"
OVERVIEW_VUE = _ROOT / "public" / "js" / "pages" / "tender" / "TenderOverview.vue"
FILTERS_JS = _ROOT / "public" / "js" / "composables" / "tenderBoardFilters.js"


def _load_funnel():
	spec = importlib.util.spec_from_file_location("_funnel_under_test", FUNNEL_PY)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def _read(path: Path) -> str:
	return path.read_text(encoding="utf-8")


class TestPipelineMaths(unittest.TestCase):
	def setUp(self):
		self.funnel = _load_funnel()

	def test_the_strip_walks_the_open_phases_only(self):
		"""`won` and `lost` are outcomes, not phases. On a strip that reads
		left-to-right as "how far did it get", a loss sitting at the end reads as
		the final step of progress."""
		self.assertEqual(self.funnel.PIPELINE_PHASES, ["seen", "go", "sourcing", "priced", "submitted"])
		self.assertNotIn("won", self.funnel.PIPELINE_PHASES)
		self.assertNotIn("lost", self.funnel.PIPELINE_PHASES)

	def test_every_phase_appears_even_when_empty(self):
		"""A phase that vanishes when it hits zero makes the strip change shape
		under the user, and hides the emptiest step — which is often the finding."""
		rows = self.funnel.pipeline({}, {})
		self.assertEqual([r["key"] for r in rows], self.funnel.PIPELINE_PHASES)
		self.assertTrue(all(r["n"] == 0 and r["full"] == 0 for r in rows))

	def test_the_ready_count_can_never_exceed_its_phase(self):
		"""The bar reads "2 of 4 quote sets complete" and its denominator is the
		phase count. An unclamped numerator draws a bar past 100% and states a
		fact that is arithmetically impossible."""
		rows = self.funnel.pipeline({"sourcing": 3}, {"sourcing": 9})
		by_key = {r["key"]: r for r in rows}
		self.assertEqual(by_key["sourcing"]["full"], 3)

	def test_counts_survive_missing_and_malformed_input(self):
		rows = self.funnel.pipeline({"seen": None, "go": "2"}, {"go": None})
		by_key = {r["key"]: r for r in rows}
		self.assertEqual(by_key["seen"]["n"], 0)
		self.assertEqual(by_key["go"]["n"], 2)
		self.assertEqual(by_key["go"]["full"], 0)


class TestTheServerBuildsItInOnePass(unittest.TestCase):
	def setUp(self):
		src = _read(TENDER_PY)
		start = src.index("def tender_funnel(")
		self.body = src[start : src.index("\ndef ", start + 1)]

	def test_the_strip_is_derived_from_the_same_stages_the_rows_came_from(self):
		"""A second query for the same numbers is how a board ends up saying 4 in
		the strip and listing 3 rows."""
		self.assertIn('out["pipeline"] = _funnel.pipeline(out["stages"], quote_ready)', self.body)

	def test_quote_set_completeness_uses_both_halves_of_the_rule(self):
		"""Five bids from one country is not a complete quote set — that is the
		precise case the 2-country rule exists to catch. A "complete" flag that
		only counts quotations would mark it green."""
		self.assertIn("def _quote_set_complete(", self.body)
		self.assertIn("< 5", self.body)
		self.assertIn(">= 2", self.body)
		self.assertIn("country_by_supplier", self.body)

	def test_supplier_countries_are_read_in_one_query_for_the_whole_board(self):
		"""One query per deal is how this endpoint got slow the last time."""
		self.assertIn('filters={"name": ["in", list(all_suppliers)]}', self.body)
		self.assertNotIn("for deal in", self.body.split("country_by_supplier")[0][-400:])


class TestTheStripIsAControlledComponent(unittest.TestCase):
	def setUp(self):
		self.src = _read(FUNNEL_VUE)

	def test_the_strip_is_off_by_default(self):
		"""It only belongs on a screen that has something below it to filter."""
		self.assertIn("pipelineStrip: { type: Boolean, default: false }", self.src)
		self.assertIn('v-if="pipelineStrip"', self.src)

	def test_the_selection_lives_on_the_host_not_in_the_component(self):
		"""Local state would drop the filter on refresh and make the URL a lie."""
		self.assertIn('selected: { type: String, default: "" }', self.src)

	def test_clicking_the_same_phase_clears_the_filter(self):
		self.assertIn('const next = props.selected === row.key ? "" : row.key;', self.src)

	def test_the_selection_is_re_emitted_once_the_data_arrives(self):
		"""A shared `?phase=` link loads the strip selected and the table
		unfiltered unless the component republishes after its fetch."""
		self.assertRegex(self.src, r"watch\(\[data, \(\) => props\.selected\]")

	def test_the_deal_list_ships_with_the_selection(self):
		"""The host filters by the very rows the count was built from."""
		self.assertIn("function dealsOf(key)", self.src)
		self.assertIn('emit("select", next, next ? dealsOf(next) : []', self.src)


class TestTheBoardFiltersInPlace(unittest.TestCase):
	def setUp(self):
		self.src = _read(BOARD_VUE)

	def test_the_phase_filter_does_not_collide_with_the_lifecycle_stage_filter(self):
		"""`tenderBoardFilters` already owns `stage`, and its values are lifecycle
		keys (identified/decided/…), not funnel phases. Reusing the key would send
		`matchesStage` looking up `row.lifecycle.sourcing` — always undefined, so
		the table would silently empty out."""
		self.assertIn('String(route.query.phase || "")', self.src)
		self.assertIn("stage", _read(FILTERS_JS))
		self.assertNotIn("phase", _read(FILTERS_JS))

	def test_the_table_is_narrowed_by_the_phase_deal_set(self):
		self.assertIn("phaseDeals.value.has(r.deal)", self.src)

	def test_the_filter_says_what_it_is_and_offers_a_way_out(self):
		"""A silently shortened table reads as missing data."""
		self.assertIn("board-phase", self.src)
		self.assertIn("Clear filter", self.src)

	def test_the_selection_is_written_to_the_url(self):
		"""So the director can send "look at pricing" as a link."""
		self.assertIn("router.replace({ query })", self.src)


class TestTheOverviewSendsYouWhereFilteringWorks(unittest.TestCase):
	def test_a_phase_click_opens_the_board_already_filtered(self):
		"""The overview has no document table under the strip. Filtering nothing
		in place would be a dead click; navigating with the phase preserved keeps
		one mental model across both screens."""
		src = _read(OVERVIEW_VUE)
		self.assertIn("pipeline-strip", src)
		self.assertIn('path: "/tender/portfolio", query: { phase: key }', src)


if __name__ == "__main__":
	unittest.main()
