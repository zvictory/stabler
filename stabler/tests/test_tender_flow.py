"""Süreç akışı — adım performansı toplaması.

Ekranın tek işi "nerede takıldık" sorusuna cevap vermek, ve bu cevabın iki
yanlış yolu var: bilmediğini biliyormuş gibi sunmak, ya da boş bir adımı
tıkanmış (veya tersi) göstermek. Bu dosya ikisini de kapatıyor.
"""

import unittest

from stabler.api import _tender_flow as flow


def rows_for(deals, today="2026-08-01", overrides=None):
	return {r["stage"]: r for r in flow.step_rows(deals, today, overrides)}


class TestUnknownIsNotZero(unittest.TestCase):
	"""v66 öncesi taşınmış her anlaşmanın damgası yok. Onları ortalamaya 0 gün
	diye katmak ortalamayı aşağı çeker ve tıkanmış adımı sağlıklı gösterir."""

	def test_an_unstamped_deal_is_counted_as_open_but_not_averaged(self):
		row = rows_for(
			[
				{"stage": "sourcing", "entered_at": "2026-07-18"},
				{"stage": "sourcing", "entered_at": None},
			]
		)["sourcing"]
		self.assertEqual(row["open"], 2)
		self.assertEqual(row["unmeasured"], 1)
		self.assertEqual(row["avg_days"], 14.0)

	def test_a_stage_where_nothing_can_be_measured_says_so(self):
		row = rows_for([{"stage": "priced", "entered_at": None}])["priced"]
		self.assertEqual(row["state"], "unknown")
		self.assertIsNone(row["avg_days"])
		self.assertEqual(row["open"], 1)

	def test_unknown_is_not_reported_as_within_the_limit(self):
		"""Ekranın en dürüst olması gereken yerinde iyimser bir yalan."""
		self.assertNotEqual(rows_for([{"stage": "priced", "entered_at": None}])["priced"]["state"], "in")


class TestEmptyIsNotUnknown(unittest.TestCase):
	"""Boş adımda bekleyen iş YOK; ölçülemeyen adımda bekleyen iş VAR ama ne
	kadar beklediğini bilmiyoruz. İkisini tek kelimeye toplamak, tıkanmış
	olabilecek bir adımı boş göstermek demek."""

	def test_a_stage_with_no_deals_is_empty(self):
		row = rows_for([{"stage": "seen", "entered_at": "2026-08-01"}])["go"]
		self.assertEqual(row["open"], 0)
		self.assertEqual(row["state"], "empty")

	def test_a_stage_with_deals_but_no_stamps_is_unknown(self):
		self.assertEqual(rows_for([{"stage": "go", "entered_at": None}])["go"]["state"], "unknown")


class TestTheStateFollowsTheThreshold(unittest.TestCase):
	def test_well_inside_the_limit(self):
		self.assertEqual(
			rows_for([{"stage": "sourcing", "entered_at": "2026-07-29"}])["sourcing"]["state"], "in"
		)

	def test_the_last_quarter_is_the_edge(self):
		self.assertEqual(
			rows_for([{"stage": "sourcing", "entered_at": "2026-07-21"}])["sourcing"]["state"], "edge"
		)

	def test_past_the_limit_is_out(self):
		self.assertEqual(
			rows_for([{"stage": "sourcing", "entered_at": "2026-07-15"}])["sourcing"]["state"], "out"
		)

	def test_a_short_threshold_still_gets_an_edge(self):
		"""3 günlük eşikte tam çeyrek 0 gün eder; taban olmasa kısa adımlar
		hiç uyarmadan kırmızıya atlardı — `_tender_sla` ile aynı taban."""
		self.assertEqual(
			rows_for([{"stage": "priced", "entered_at": "2026-07-30"}])["priced"]["state"], "edge"
		)

	def test_a_tenant_override_moves_the_line(self):
		deals = [{"stage": "sourcing", "entered_at": "2026-07-15"}]
		self.assertEqual(rows_for(deals)["sourcing"]["state"], "out")
		self.assertEqual(rows_for(deals, overrides={"sourcing": 30})["sourcing"]["state"], "in")

	def test_a_switched_off_stage_is_never_out(self):
		row = rows_for([{"stage": "seen", "entered_at": "2020-01-01"}], overrides={"seen": 0})["seen"]
		self.assertIsNone(row["sla_days"])
		self.assertEqual(row["state"], "unknown")


class TestTheBottleneckIsTheWorstRatioNotTheWorstGap(unittest.TestCase):
	"""30 günlük eşiği 3 gün aşan adım ile 3 günlük eşiği 3 gün aşan adım aynı
	değil — ikincisi iki katına çıkmış demektir."""

	def test_the_proportionally_worst_step_wins(self):
		# Vaka AYIRT EDİCİ olmalı: ilk yazdığımda fark da oran da aynı adımı
		# seçiyordu, dolayısıyla "fark kullan" mutasyonu testten sağ çıktı.
		#   sourcing 20/14 → oran 1.43 · fark 6
		#   priced    7/3  → oran 2.33 · fark 4
		# Oran priced der, fark sourcing. İkisi ayrışmazsa iddia bir şey
		# kanıtlamaz.
		rows = flow.step_rows(
			[
				{"stage": "sourcing", "entered_at": "2026-07-12"},
				{"stage": "priced", "entered_at": "2026-07-25"},
			],
			"2026-08-01",
		)
		self.assertEqual(flow.bottleneck(rows), "priced")

	def test_no_bottleneck_when_everything_is_inside(self):
		rows = flow.step_rows([{"stage": "sourcing", "entered_at": "2026-07-30"}], "2026-08-01")
		self.assertIsNone(flow.bottleneck(rows))

	def test_a_stage_without_a_threshold_can_never_be_the_bottleneck(self):
		rows = flow.step_rows([{"stage": "seen", "entered_at": "2020-01-01"}], "2026-08-01", {"seen": 0})
		self.assertIsNone(flow.bottleneck(rows))


class TestTheTableShape(unittest.TestCase):
	def test_every_working_stage_gets_a_row_even_when_empty(self):
		"""Adım tablosundan bir satırın kaybolması, o adımın var olmadığı
		izlenimi verir — oysa yalnızca boştur."""
		rows = flow.step_rows([], "2026-08-01")
		self.assertEqual([r["stage"] for r in rows], list(flow.WORKING_STAGES))

	def test_finished_stages_are_not_in_the_table(self):
		"""Tablo BEKLEYEN işi anlatıyor; kazanılmış bir anlaşma beklemiyor."""
		for stage in ("won", "lost"):
			with self.subTest(stage=stage):
				self.assertNotIn(stage, flow.WORKING_STAGES)

	def test_an_unknown_stage_is_ignored_not_invented(self):
		rows = rows_for([{"stage": "bilinmeyen", "entered_at": "2026-08-01"}])
		self.assertNotIn("bilinmeyen", rows)
		self.assertEqual(sum(r["open"] for r in rows.values()), 0)

	def test_the_worst_case_is_reported_beside_the_average(self):
		"""Ortalama tek başına saklar: 1 ve 29 günün ortalaması 15, ama 29
		günlük iş bugün müdahale ister."""
		row = rows_for(
			[
				{"stage": "submitted", "entered_at": "2026-07-31"},
				{"stage": "submitted", "entered_at": "2026-07-03"},
			]
		)["submitted"]
		self.assertEqual(row["avg_days"], 15.0)
		self.assertEqual(row["worst_days"], 29)

	def test_the_stages_match_the_thresholds_that_exist(self):
		"""Eşiksiz bir çalışma adımı ya da adımsız bir eşik, ikisi de sessiz
		bir boşluk."""
		from stabler.api._tender_sla import DEFAULT_STAGE_SLA_DAYS

		self.assertEqual(set(flow.WORKING_STAGES), set(DEFAULT_STAGE_SLA_DAYS))


if __name__ == "__main__":
	unittest.main()
