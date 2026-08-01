"""Demo tohumlayıcının güvenlik ve dürüstlük sözleşmesi.

Bu betik CANLI bir siteye yazıyor. İki şeyi yanlış yapması hâlinde zarar
geri alınamaz: işaretsiz kayda dokunmak, ya da demo'yu gerçekten ayırt
edilemez hâle getirmek. Üçüncü bir risk daha var ve o sessiz: demo veriyi
"güzel" kurmak — her adımı eşiğin içinde, her damgayı dolu — ki o zaman
ekranların dürüstlüğü hiç sınanmamış olur.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = (ROOT / "maintenance/seed_tender_demo.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
	block = SEED[SEED.index(f"def {name}("):]
	nxt = re.search(r"\n(?:def |\Z)", block[1:])
	return block[: nxt.start() + 1] if nxt else block


class TestItCannotTouchRealData(unittest.TestCase):
	def test_every_record_carries_the_marker(self):
		self.assertIn('DEMO_SUFFIX = " [DEMO]"', SEED)
		self.assertIn('f"{name}{DEMO_SUFFIX}"', SEED)   # kurum
		self.assertIn('f"{lot_no}{DEMO_SUFFIX}"', SEED)  # lot

	def test_unseed_filters_on_the_marker_everywhere(self):
		"""İşaretsiz bir kaydı silen tek bir sorgu, geri alınamaz veri kaybı."""
		unseed = _fn("unseed")
		deletes = re.findall(r"frappe\.get_all\(\s*\"(\w[\w ]*)\",\s*filters=\{([^}]*)\}", unseed)
		self.assertTrue(deletes, "unseed hiçbir şey listelemiyor")
		for doctype, filters in deletes:
			with self.subTest(doctype=doctype):
				self.assertIn("DEMO_SUFFIX", filters, f"{doctype} filtresi işarete bakmıyor")

	def test_the_raw_delete_is_scoped_to_one_deal(self):
		"""Olay kayıtları doğrudan SQL ile siliniyor (doctype değişmez);
		WHERE olmadan bu, sitenin tüm aşama geçmişini silerdi."""
		unseed = _fn("unseed")
		self.assertRegex(unseed, r"DELETE FROM `tabCRM Stage Event` WHERE deal = %\(deal\)s")

	def test_seeding_twice_does_nothing(self):
		seed = _fn("seed")
		self.assertIn("if _demo_exists():", seed)
		self.assertRegex(seed, r"if _demo_exists\(\):[\s\S]{0,200}return")

	def test_it_fails_loudly_on_a_missing_prerequisite(self):
		"""Eksik alanla yarım veri bırakmak, hiç veri bırakmamaktan kötü."""
		guard = _fn("_guard")
		self.assertIn("frappe.throw", guard)
		self.assertIn("custom_tender_intake", guard)
		self.assertIn('frappe.db.exists("Company", company)', guard)


class TestTheDataExercisesEveryScreenState(unittest.TestCase):
	"""Demo'nun işi ekranı doldurmak değil, ekranın gösterdiği AYRIMLARI
	üretmek. Hepsi yeşil bir demo, hiçbir şeyi kanıtlamaz."""

	LOTS = [
		line for line in SEED[SEED.index("DEMO_LOTS = ["):SEED.index("#: Son tarihler")].splitlines()
		if line.strip().startswith("(")
	]

	def test_every_pipeline_stage_has_a_deal(self):
		from stabler.api._funnel import STAGES

		staged = {re.search(r'"(\w+)", -?\d|"(\w+)", None', line) for line in self.LOTS}
		present = set(re.findall(r'",\s*"(\w+)",\s*(?:None|\d+),', "\n".join(self.LOTS)))
		self.assertEqual(STAGES - present, set(), f"aşamasız kalan: {STAGES - present}")

	def test_some_deals_deliberately_have_no_stage_stamp(self):
		"""Süreç akışının "ölçülemiyor" satırı gerçek sitede de olacak (v66
		öncesi her kayıt). Demo onu saklarsa ekranın en dürüst parçası hiç
		görülmez."""
		self.assertGreaterEqual(sum(1 for line in self.LOTS if ", None," in line), 2)

	def test_the_thresholds_are_crossed_in_both_directions(self):
		"""Eşik içinde, sınırda ve aşmış adımlar birlikte olmalı; hepsi yeşil
		bir demo SLA renklerini hiç göstermez."""
		from stabler.api._tender_sla import DEFAULT_STAGE_SLA_DAYS

		ages: dict[str, list[int]] = {}
		for line in self.LOTS:
			m = re.search(r'",\s*"(\w+)",\s*(\d+),', line)
			if m:
				ages.setdefault(m.group(1), []).append(int(m.group(2)))
		over = [s for s, days in ages.items() if s in DEFAULT_STAGE_SLA_DAYS
		        and sum(days) / len(days) > DEFAULT_STAGE_SLA_DAYS[s]]
		inside = [s for s, days in ages.items() if s in DEFAULT_STAGE_SLA_DAYS
		          and sum(days) / len(days) < DEFAULT_STAGE_SLA_DAYS[s]]
		self.assertTrue(over, "hiçbir adım eşiği aşmıyor — 'SLA dışı' hiç görünmez")
		self.assertTrue(inside, "hiçbir adım eşiğin içinde değil — 'içinde' hiç görünmez")

	def test_deadlines_cover_past_today_and_soon(self):
		"""Operasyon masasının severity dili bunlardan çıkıyor."""
		offsets = set(int(v) for v in re.findall(r':\s*(-?\d+),', SEED[SEED.index("DEADLINE_OFFSETS"):SEED.index("def _guard")]))
		self.assertTrue(any(o < 0 for o in offsets), "geçmiş son tarih yok")
		self.assertIn(0, offsets, "bugün biten yok")
		self.assertTrue(any(0 < o <= 2 for o in offsets), "48 saat içinde biten yok")

	def test_finished_deals_exist_on_both_sides(self):
		"""Direktör panosunun kazanma oranı tek taraflı veriyle anlamsız."""
		joined = "\n".join(self.LOTS)
		self.assertIn('"won"', joined)
		self.assertIn('"lost"', joined)


class TestTheEvidenceMatchesTheStage(unittest.TestCase):
	"""`_funnel.classify` aşamayı OLGULARDAN türetiyor. Damgalı aşama ile
	türetilen aşama ayrışırsa iki ekran aynı anlaşmayı farklı kulvarda
	gösterir — demo'nun yaratacağı en sinsi hata bu."""

	def test_submission_writes_both_audit_fields(self):
		"""`_has_submission_evidence` sonucu değil KATILIMI kanıt sayıyor:
		ikisi birden olmalı."""
		intake = _fn("_intake")
		self.assertIn('intake["submitted_at"]', intake)
		self.assertIn('intake["submitted_by"]', intake)

	def test_a_result_is_only_set_for_finished_deals(self):
		intake = _fn("_intake")
		self.assertRegex(intake, r'if stage in \("won", "lost"\):[\s\S]{0,120}intake\["result"\] = stage')

	def test_go_evidence_is_written_for_every_stage_past_intake(self):
		intake = _fn("_intake")
		self.assertRegex(intake, r'if stage != "seen":[\s\S]{0,160}intake\["go_no_go"\] = "go"')

	def test_history_walks_the_pipeline_instead_of_jumping(self):
		"""Yalnız son damgayı yazmak, her anlaşmayı bugünkü kulvarına doğmuş
		gösterir; süreç akışı "nerede oyalandık"ı geçmişten okuyor."""
		hist = _fn("_stage_history")
		self.assertIn("ORDER[: ORDER.index(stage) + 1]", hist)
		self.assertIn('"axis": "tender_stage"', hist)
		self.assertIn('"from_tender_stage": previous', hist)


if __name__ == "__main__":
	unittest.main()
