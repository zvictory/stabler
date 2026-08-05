"""Guards for truthful, desktop-only row ordinals on operational lists."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PAGES = _ROOT / "public" / "js" / "pages"


class TestTenderPortfolioOrdinal(unittest.TestCase):
	def setUp(self):
		self.source = (_PAGES / "tender" / "DirectorBoard.vue").read_text(encoding="utf-8")

	def test_ordinal_tracks_the_filtered_view_and_stays_off_mobile(self):
		self.assertIn('v-for="(r, index) in filteredRows"', self.source)
		self.assertIn("{{ index + 1 }}", self.source)
		self.assertGreaterEqual(self.source.count("d-none d-md-table-cell"), 2)
		self.assertIn('{{ t("Row") }}', self.source)

	def test_skeleton_matches_the_extra_column(self):
		self.assertIn(':cols="9"', self.source)
		self.assertIn("hide-first-on-mobile", self.source)


class TestCommercialInvoiceOrdinal(unittest.TestCase):
	def setUp(self):
		self.source = (_PAGES / "imports" / "CommercialInvoices.vue").read_text(encoding="utf-8")

	def test_ordinal_continues_across_server_pages_and_stays_off_mobile(self):
		self.assertIn('v-for="(r, index) in rows"', self.source)
		self.assertIn("{{ limitStart + index + 1 }}", self.source)
		self.assertGreaterEqual(self.source.count("d-none d-md-table-cell"), 3)
		self.assertIn('{{ t("Row") }}', self.source)

	def test_document_identity_remains_separate(self):
		self.assertIn("{{ r.ci_number || r.name }}", self.source)

	def test_skeleton_matches_the_extra_column(self):
		self.assertIn(':cols="10"', self.source)
		self.assertIn("hide-first-on-mobile", self.source)


class TestResponsiveSkeletonOrdinal(unittest.TestCase):
	def test_first_placeholder_cell_can_follow_the_hidden_ordinal_column(self):
		source = (_ROOT / "public" / "js" / "components" / "SkeletonRows.vue").read_text(encoding="utf-8")
		self.assertIn("hideFirstOnMobile", source)
		self.assertIn("'d-none d-md-table-cell': hideFirstOnMobile && c === 1", source)


if __name__ == "__main__":
	unittest.main()
