"""The workflow mockup is out of the running product, and still in the record.

Zafar asked for it off live on 2026-08-28. It was a design-board drawing shown
inside the product's own chrome, behind the `director` gate — and a drawing
rendered in the product's frame reads as a description of the product no matter
how loud the truth strip is. That was the argument for keeping it; it is a
better argument for removing it now that slice 1 has landed and parts of the
drawing are wrong about what exists.

Removing it is two separate jobs, and only the first is obvious:

1.  The route, the nav link and the component go. That makes it unreachable
    from the app.
2.  The HTML itself has to leave `stabler/public/`, because that tree is
    symlinked to `sites/assets/stabler` and is served raw — the drawing would
    stay fetchable at its own URL with the app none the wiser. It moves back to
    `docs/plans/assets/`, which `.rsync-exclude` drops, next to the landed-cost
    mockup that already lives there. The record survives; the deployment does
    not.

And one thing no test can do: deploys here rsync WITHOUT `--delete`, so the copy
already sitting on prod is not removed by shipping this commit. It has to be
deleted on the server by hand. That is written down in the commit message and in
the deploy note, not here, because a test cannot observe prod.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_workflow_mockup_source -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = (ROOT / "public" / "js" / "router.js").read_text(encoding="utf-8")
NAV = (ROOT / "public" / "js" / "pages" / "tender" / "TenderNav.vue").read_text(encoding="utf-8")
_MOCKUP = "mikas-tender-workflow.html"


class TestTheMockupIsNotReachableFromTheApp(unittest.TestCase):
	def test_the_route_is_gone(self):
		self.assertNotIn('path: "/tender/mockup"', ROUTER)
		self.assertNotIn("tender-mockup", ROUTER)

	def test_the_component_is_not_imported_or_left_behind(self):
		"""An orphaned import is not harmless: it keeps the component in the
		bundle and gives the route an obvious way back."""
		self.assertNotIn("TenderWorkflowMockup", ROUTER)
		self.assertFalse(
			(ROOT / "public" / "js" / "pages" / "tender" / "TenderWorkflowMockup.vue").exists(),
			"bileşen hâlâ duruyor",
		)

	def test_the_nav_link_is_gone(self):
		self.assertNotIn("/tender/mockup", NAV)
		self.assertNotIn("Workflow mockup", NAV)


class TestTheDrawingCannotReachAServerAnyMore(unittest.TestCase):
	"""The half that is easy to forget. Deleting the route leaves the HTML
	served raw out of `sites/assets/stabler`, which is the same as leaving it
	up."""

	def test_it_is_not_under_the_served_asset_tree(self):
		served = ROOT / "public" / "mockups" / _MOCKUP
		self.assertFalse(served.exists(), f"{served} hâlâ servis edilen ağaçta")

	def test_no_file_under_public_still_points_at_it(self):
		"""Catches the shape where the file moves but a stylesheet, a redirect or
		a stray link keeps asking for the old URL."""
		hits = [
			p.relative_to(ROOT).as_posix()
			for p in (ROOT / "public").rglob("*")
			if p.is_file()
			and "dist" not in p.parts
			and _MOCKUP in p.read_text(encoding="utf-8", errors="ignore")
		]
		self.assertEqual(hits, [], f"hâlâ mockup'a işaret eden dosyalar: {hits}")


class TestTheRecordSurvives(unittest.TestCase):
	"""Removing it from the product is not the same as deleting the work. The
	design-board decision doc still cites this drawing, and a dead citation is
	how a decision loses its evidence."""

	def test_the_drawing_is_kept_where_it_cannot_ship(self):
		kept = ROOT.parent / "docs" / "plans" / "assets" / _MOCKUP
		self.assertTrue(kept.is_file(), f"tasarım kaydı kayboldu: {kept}")

	def test_that_location_is_excluded_from_every_deploy(self):
		excluded = (ROOT.parent / ".rsync-exclude").read_text(encoding="utf-8").splitlines()
		self.assertIn("docs", [ln.strip() for ln in excluded])
