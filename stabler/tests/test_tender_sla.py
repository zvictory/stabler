"""Tender aşama süreleri: eşikler, gecikme ve önem.

Süreç akışı ekranının tek işi "nerede takıldık" sorusuna cevap vermek, ve o
cevabın iki yönlü yalan söyleme imkânı var: bilmediğini biliyormuş gibi
göstermek, ya da bilebileceğini görmezden gelmek. Bu dosya ikisini de kapatıyor.

Matematik Frappe'siz bir modülde (`api/_tender_sla.py`) yaşıyor; burada site
olmadan tüketilerek test ediliyor.
"""

import unittest
from datetime import date, datetime

from stabler.api import _tender_sla as sla


class TestDaysInStage(unittest.TestCase):
	def test_counts_whole_days(self):
		self.assertEqual(sla.days_in_stage("2026-07-27", "2026-08-01"), 5)

	def test_same_day_is_zero_not_one(self):
		self.assertEqual(sla.days_in_stage("2026-08-01", "2026-08-01"), 0)

	def test_a_missing_stamp_is_unknown_not_zero(self):
		""" "Bilmiyoruz" ile "sıfır gündür" aynı şey değil. Sıfır döndürmek,
		damgası olmayan her eski anlaşmayı bugün taşınmış gibi gösterir ve
		ekran taptaze bir hat uydururdu."""
		for empty in (None, "", "   "):
			with self.subTest(value=repr(empty)):
				self.assertIsNone(sla.days_in_stage(empty, "2026-08-01"))

	def test_an_unparseable_stamp_is_unknown(self):
		self.assertIsNone(sla.days_in_stage("bir ara", "2026-08-01"))

	def test_a_future_stamp_does_not_go_negative(self):
		"""Saat kayması ya da elle düzeltme; -3 gün beklemiş bir anlaşma yok."""
		self.assertEqual(sla.days_in_stage("2026-08-05", "2026-08-01"), 0)

	def test_datetime_and_date_and_text_agree(self):
		expected = 5
		for value in (
			"2026-07-27",
			"2026-07-27 09:41:00",
			datetime(2026, 7, 27, 9, 41),
			date(2026, 7, 27),
		):
			with self.subTest(value=repr(value)):
				self.assertEqual(sla.days_in_stage(value, "2026-08-01"), expected)


class TestTerminalStagesHaveNoThreshold(unittest.TestCase):
	"""Sonuçlanmış bir anlaşma beklemiyor. Ona "45 gündür bu aşamada" demek
	doğru ama anlamsız; "geç" demek yanlış."""

	def test_won_and_lost_carry_no_default(self):
		for stage in ("won", "lost"):
			with self.subTest(stage=stage):
				self.assertNotIn(stage, sla.DEFAULT_STAGE_SLA_DAYS)
				self.assertIsNone(sla.sla_for(stage))

	def test_a_stage_without_a_threshold_is_never_overdue(self):
		self.assertEqual(sla.overdue_by("won", "2026-01-01", "2026-08-01"), 0)
		self.assertEqual(sla.severity("won", "2026-01-01", "2026-08-01"), "info")

	def test_every_non_terminal_stage_has_one(self):
		"""Eşiksiz bir çalışma aşaması, o kulvarda takılan işi görünmez yapar."""
		from stabler.api import _funnel

		working = set(_funnel.ORDER) - {"won"}
		self.assertEqual(working - set(sla.DEFAULT_STAGE_SLA_DAYS), set())


class TestTenantOverrides(unittest.TestCase):
	def test_an_override_replaces_the_default(self):
		self.assertEqual(sla.sla_for("sourcing"), 14)
		self.assertEqual(sla.sla_for("sourcing", {"sourcing": 21}), 21)

	def test_zero_switches_the_stage_off_rather_than_meaning_no_patience(self):
		"""Sıfır sabır her anlaşmayı anında gecikmiş yapardı. Yönetici bir
		aşamayı takipten çıkarmak istediğinde alanı sıfırlıyor."""
		self.assertIsNone(sla.sla_for("seen", {"seen": 0}))
		self.assertEqual(sla.overdue_by("seen", "2020-01-01", "2026-08-01", {"seen": 0}), 0)

	def test_a_negative_or_unreadable_value_switches_it_off_too(self):
		for value in (-5, None, "", "çok"):
			with self.subTest(value=repr(value)):
				self.assertIsNone(sla.sla_for("seen", {"seen": value}))

	def test_an_override_for_one_stage_leaves_the_others_alone(self):
		overrides = {"seen": 1}
		self.assertEqual(sla.sla_for("seen", overrides), 1)
		self.assertEqual(sla.sla_for("sourcing", overrides), 14)


class TestOverdueMath(unittest.TestCase):
	def test_on_the_limit_is_not_yet_late(self):
		self.assertEqual(sla.overdue_by("seen", "2026-07-29", "2026-08-01"), 0)

	def test_one_day_past_the_limit(self):
		self.assertEqual(sla.overdue_by("seen", "2026-07-28", "2026-08-01"), 1)

	def test_an_unknown_stamp_reports_no_delay(self):
		"""Ölçemediğimiz şeye geç diyemeyiz."""
		self.assertEqual(sla.overdue_by("seen", None, "2026-08-01"), 0)


class TestSeverityLanguage(unittest.TestCase):
	"""Katmanın dört seviyesi. Sınırlar tam gün: bir gün kayarsa ekran yanlış
	rengi gösterir ve renk bu tasarımda tek başına bilgi taşıyor."""

	def test_past_the_limit_is_critical(self):
		self.assertEqual(sla.severity("seen", "2026-07-28", "2026-08-01"), "crit")

	def test_exactly_on_the_limit_is_today(self):
		self.assertEqual(sla.severity("seen", "2026-07-29", "2026-08-01"), "today")

	def test_the_last_quarter_warns_early(self):
		"""14 günlük eşikte 11. günden itibaren — en az bir gün önce uyarmak
		için taban alınıyor."""
		self.assertEqual(sla.severity("sourcing", "2026-07-21", "2026-08-01"), "soon")
		self.assertEqual(sla.severity("sourcing", "2026-07-22", "2026-08-01"), "info")

	def test_a_short_threshold_still_warns_one_day_ahead(self):
		"""3 günlük eşikte tam çeyrek 0 gün ederdi; taban en az 1'e sabitli,
		yoksa kısa aşamalar hiç uyarmadan kırmızıya atlardı."""
		self.assertEqual(sla.severity("priced", "2026-07-30", "2026-08-01"), "soon")

	def test_unknown_stays_quiet(self):
		"""Bilmediğimizi uyarıya çevirmek ekranı gürültüye boğar."""
		self.assertEqual(sla.severity("seen", None, "2026-08-01"), "info")

	def test_every_level_is_one_the_design_layer_knows(self):
		from pathlib import Path

		css = (Path(__file__).resolve().parents[1] / "public/css/stabler-modernist.css").read_text(
			encoding="utf-8"
		)
		for level in ("crit", "today", "soon", "info"):
			with self.subTest(level=level):
				self.assertIn(f'data-sev="{level}"', css)


class TestTheTenantReaderMatchesTheDefaults(unittest.TestCase):
	def test_the_child_table_covers_exactly_the_stages_with_thresholds(self):
		"""Sütun ile varsayılan ayrışırsa, yönetici ekranda olmayan bir aşamayı
		ayarlayamaz ya da var olmayan bir sütuna ayar yazar."""
		import json
		from pathlib import Path

		root = Path(__file__).resolve().parents[1]
		doc = json.loads(
			(root / "stabler/doctype/stabler_tender_stage_sla/stabler_tender_stage_sla.json").read_text(
				encoding="utf-8"
			)
		)
		columns = {
			f["fieldname"][len("sla_") : -len("_days")]
			for f in doc["fields"]
			if f["fieldname"].startswith("sla_")
		}
		self.assertEqual(columns, set(sla.DEFAULT_STAGE_SLA_DAYS))

	def test_it_is_a_child_table_hung_off_settings(self):
		import json
		from pathlib import Path

		root = Path(__file__).resolve().parents[1]
		doc = json.loads(
			(root / "stabler/doctype/stabler_tender_stage_sla/stabler_tender_stage_sla.json").read_text(
				encoding="utf-8"
			)
		)
		self.assertEqual(doc.get("istable"), 1)
		settings = (root / "stabler/doctype/stabler_settings/stabler_settings.json").read_text(
			encoding="utf-8"
		)
		self.assertIn('"options": "Stabler Tender Stage SLA"', settings)

	def test_a_blank_cell_switches_the_stage_off_instead_of_reverting(self):
		"""Frappe boş Int'i 0 saklar. Varsayılana düşmek, yöneticinin kapatma
		niyetini sessizce geri alırdı."""
		reader = (
			__import__("pathlib").Path(__file__).resolve().parents[1]
			/ "stabler/doctype/stabler_settings/stabler_settings.py"
		).read_text(encoding="utf-8")
		block = reader[reader.index("def stage_sla_for") :]
		block = block[: block.index("\ndef module_map_for")]
		self.assertIn('int(getattr(row, f"sla_{stage}_days", 0) or 0)', block)
		self.assertNotIn("DEFAULT_STAGE_SLA_DAYS.get(stage)", block)


if __name__ == "__main__":
	unittest.main()
