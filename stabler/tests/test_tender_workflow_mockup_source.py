"""The design mockup is reachable from inside the app, and says what it is.

`docs/plans/assets/…` was the mockup's home until this module existed, and it
could never have worked from the SPA: `.rsync-exclude` drops both `docs/` and
`stabler/docs/`, so the file reaches no server. It now lives under
`stabler/public/`, which bench symlinks to `sites/assets/stabler` — the same
path in dev and on prod.

That move is exactly the kind that rots quietly. The iframe holds a *string*;
renaming the file leaves the string valid-looking, the route still resolves, the
page still renders, and the only symptom is an empty frame nobody reports. The
first test below is the one that cannot be replaced by reading the code.

The second reason this module exists is honesty. A mockup opened inside the
product's own chrome reads as a *description of the product*. The truth strip
(`docs/uat/2026-08-24-wo-two-operators/mockup.html` set the convention) is what
keeps a drawing from coming back to us as a fact — and it has real work to do
here, because slice 1 has landed and parts of the mockup's own body are now
wrong about it.

    cd /path/to/stabler && PYTHONPATH=$PWD python3 -m unittest stabler.tests.test_tender_workflow_mockup_source -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "public/js/pages/tender/TenderWorkflowMockup.vue").read_text(encoding="utf-8")
ROUTER = (ROOT / "public/js/router.js").read_text(encoding="utf-8")
NAV = (ROOT / "public/js/pages/tender/TenderNav.vue").read_text(encoding="utf-8")

_ASSET_PREFIX = "/assets/stabler/"


class TestTheMockupIsActuallyThere(unittest.TestCase):
	def test_the_url_the_page_loads_resolves_to_a_file_on_disk(self):
		"""The whole point of the module. `/assets/stabler/<p>` is the symlink
		bench makes to `stabler/public/<p>`, so the served URL and the repo path
		are the same string with a different prefix — and that is checkable here,
		before a deploy turns a rename into an empty iframe."""
		match = re.search(r'const MOCKUP_URL = "([^"]+)"', PAGE)
		self.assertIsNotNone(match, "MOCKUP_URL bulunamadı")
		url = match.group(1)
		self.assertTrue(url.startswith(_ASSET_PREFIX), f"{url} servis edilen varlık ağacında değil")
		self.assertTrue((ROOT / "public" / url[len(_ASSET_PREFIX) :]).is_file(), f"{url} diskte yok")

	def test_the_mockup_is_not_parked_under_docs(self):
		"""`docs/` and `stabler/docs/` are both in `.rsync-exclude`. A mockup
		served from there works on this laptop and 404s on every tenant — the
		failure a developer is least likely to see and most likely to ship."""
		excluded = (ROOT.parent / ".rsync-exclude").read_text(encoding="utf-8").splitlines()
		self.assertIn("docs", [ln.strip() for ln in excluded])
		# The URL, not the file body: this component's header comment explains why
		# `docs/` cannot serve the mockup, so matching on the whole source would
		# fail against its own prose rather than against a real regression.
		self.assertNotIn("/docs/", re.search(r'const MOCKUP_URL = "([^"]+)"', PAGE).group(1))


class TestItIsReachableAndGated(unittest.TestCase):
	def test_the_route_is_wired_to_the_component(self):
		"""A component nothing routes to is dead code that still ships."""
		self.assertIn('import TenderWorkflowMockup from "./pages/tender/TenderWorkflowMockup.vue";', ROUTER)
		self.assertIn('path: "/tender/mockup"', ROUTER)
		self.assertIn("component: TenderWorkflowMockup", ROUTER)

	def test_the_nav_link_exists_and_is_director_gated(self):
		"""Both halves matter, and `TenderNav.vue`'s own header comment records
		why: a page that lives only at a URL disappears (the director board did).
		But a design that does not work must not sit in everyone's navigation, so
		it takes the same `director` gate the process-flow view already has."""
		link = re.search(r'<router-link([^>]*)to="/tender/mockup"', NAV)
		self.assertIsNotNone(link, "nav bağlantısı yok")
		self.assertIn("can('director')", link.group(1))


class TestItDoesNotPassItselfOffAsTheProduct(unittest.TestCase):
	def test_the_page_says_nothing_here_comes_from_a_record(self):
		"""Shown inside the product's own chrome — module bar, page head, the
		real fonts — the mockup looks like a working screen. The page header is
		the only place a reader is guaranteed to look."""
		self.assertIn("Nothing on this page is read from a record", PAGE)

	def test_the_mockup_carries_a_truth_strip(self):
		"""The convention, and the reason it exists: without the strip a mockup
		reads as a description of the system, and the invented half comes back to
		us as a measurement."""
		mockup = (ROOT / "public/mockups/mikas-tender-workflow.html").read_text(encoding="utf-8")
		self.assertIn('class="truth"', mockup)
		self.assertIn("t-real", mockup)
		self.assertIn("t-fake", mockup)

	def test_every_claim_slice_1_falsified_carries_an_inline_correction(self):
		"""The body is dated 2026-08-17 and is deliberately NOT rewritten -- it
		records what was measured that day, and a design record that gets edited
		to match today stops being evidence of anything.

		That only stays honest while each falsified line says so *where it is
		read*. The strip sits at the top of a five-tab document; a reader who
		scrolls into the body meets a red flag with nothing next to it and takes
		"`tender_files` is not saved" for today's measurement. So the contract
		pinned here is proximity, not mere presence: every one of the four claims
		the contract slice falsified is followed closely by its correction."""
		mockup = (ROOT / "public/mockups/mikas-tender-workflow.html").read_text(encoding="utf-8")
		# (the falsified claim, the last words of the note that carries it). Two
		# anchors because a note can run on past its claim -- the #3/#4 one does,
		# for two more sentences -- and the correction belongs at the end of the
		# note, not wedged into the middle of the measurement it dates.
		claims = (
			("o listede <b>yok</b> — sessizce düşüyorlar.", "<b>tarih hiçbir yere ulaşmıyor</b>."),
			(
				"<b>referans listesi</b> kaydedilmiyor",
				"dosya sunucuda kalıyor, ihaleye bağı kayboluyor.",
			),
			("çıktıyı <b>sıfırdan</b> kurar", "tam nesne PUT</b>"),
			(
				"<code>documents: []</code> gönderiyor",
				"Yüklenmiş dosyaya bağlı satırlar dahil <b>tümü</b> gider.",
			),
		)
		for claim, note_end in claims:
			with self.subTest(claim=claim[:40]):
				self.assertIn(claim, mockup, "iddia gövdede bulunamadı — çapa kaymış")
				at = mockup.find(note_end)
				self.assertNotEqual(at, -1, "not sonu bulunamadı — çapa kaymış")
				after = mockup[at + len(note_end) : at + len(note_end) + 300]
				self.assertIn('class="fixed"', after)
				self.assertIn("Düzeldi", after)

	def test_the_strip_says_the_body_was_kept_not_corrected(self):
		"""Without this line the reader cannot tell a preserved measurement from
		a stale one nobody noticed -- and the next person to find a wrong claim
		here will 'helpfully' edit the record instead of dating it."""
		mockup = (ROOT / "public/mockups/mikas-tender-workflow.html").read_text(encoding="utf-8")
		strip = mockup[mockup.index('<div class="truth">') : mockup.index('<div class="rail">')]
		self.assertIn("olduğu gibi duruyor", strip)
		self.assertIn("silinmedi", strip)


if __name__ == "__main__":
	unittest.main()
